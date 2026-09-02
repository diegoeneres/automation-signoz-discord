from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional, Union

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse

from app.config import Settings, get_settings
from app.db import AlertStore
from app.models import Alert, SignozWebhook
from app.services import (
    alert_fingerprint,
    create_jira_issue,
    discord_message,
    is_critical_alert,
    send_critical_sms,
    send_to_discord,
    ticket_signature,
    valid_ticket_signature,
)
from app.telemetry import (
    alerts_received,
    configure_telemetry,
    notification_failures,
    notifications_sent,
    tickets_created,
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    app.state.store = AlertStore(settings.database_path)
    app.state.http = httpx.AsyncClient(timeout=15)
    yield
    await app.state.http.aclose()
    if app.state.telemetry:
        app.state.telemetry.shutdown()


app = FastAPI(title="SigNoz → Discord, Jira e SMS", version="0.4.0", lifespan=lifespan)
app.state.telemetry = configure_telemetry(app)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/webhooks/signoz", status_code=status.HTTP_202_ACCEPTED)
async def signoz_webhook(
    payload: SignozWebhook,
    request: Request,
    authorization: Optional[str] = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> dict[str, int]:
    expected = f"Bearer {settings.signoz_webhook_token.get_secret_value()}"
    if authorization != expected:
        raise HTTPException(status_code=401, detail="Token do webhook inválido")

    sent = 0
    alerts_received.add(len(payload.alerts), {"webhook.status": payload.status})
    for alert in payload.alerts:
        alert_id = request.app.state.store.put(alert_fingerprint(alert), alert.model_dump())
        signature = ticket_signature(alert_id, settings.ticket_signing_secret.get_secret_value())
        ticket_url = f"{settings.public_base_url.rstrip('/')}/tickets/{alert_id}/create?signature={signature}"
        try:
            await send_to_discord(
                request.app.state.http, settings, discord_message(alert, alert_id, ticket_url)
            )
        except Exception:
            notification_failures.add(1, {"channel": "discord"})
            logger.exception("Falha ao enviar o alerta %s ao Discord", alert_id)
            raise
        notifications_sent.add(1, {"channel": "discord"})
        if settings.sms_enabled and is_critical_alert(alert):
            claimed = request.app.state.store.claim_sms_sending(alert_id)
            if claimed:
                try:
                    await send_critical_sms(request.app.state.http, settings, alert, alert_id)
                    request.app.state.store.set_sms_sent(alert_id)
                except Exception:
                    request.app.state.store.release_sms_sending(alert_id)
                    notification_failures.add(1, {"channel": "sms"})
                    logger.exception("Falha em todos os provedores de SMS para o alerta crítico %s", alert_id)
                    raise HTTPException(status_code=502, detail="Falha ao enviar SMS")
                else:
                    notifications_sent.add(1, {"channel": "sms"})
        sent += 1
    return {"received": len(payload.alerts), "sent": sent}


@app.get("/tickets/{alert_id}/create", response_model=None)
async def create_ticket_from_discord(
    alert_id: int,
    signature: str,
    request: Request,
    settings: Settings = Depends(get_settings),
) -> Union[RedirectResponse, HTMLResponse]:
    if not valid_ticket_signature(alert_id, signature, settings.ticket_signing_secret.get_secret_value()):
        raise HTTPException(status_code=401, detail="Assinatura do link inválida")

    claimed = False
    try:
        creation_status, record = request.app.state.store.claim_jira_creation(alert_id)
        if creation_status == "missing" or not record:
            raise HTTPException(status_code=404, detail="Alerta não encontrado")
        if creation_status == "created":
            return RedirectResponse(record["jira_url"], status_code=303)
        elif creation_status == "creating":
            return HTMLResponse(
                "<h1>Ticket em criação</h1><p>Aguarde alguns segundos e clique novamente no botão.</p>",
                status_code=202,
            )
        else:
            claimed = True
            key, url = await create_jira_issue(
                request.app.state.http, settings, Alert.model_validate(record["payload"])
            )
            request.app.state.store.set_jira(alert_id, key, url)
            tickets_created.add(1)
            return RedirectResponse(url, status_code=303)
    except HTTPException:
        raise
    except Exception:
        if claimed:
            request.app.state.store.release_jira_creation(alert_id)
        logger.exception("Falha ao criar ticket para o alerta %s", alert_id)
        notification_failures.add(1, {"channel": "jira"})
        return HTMLResponse(
            "<h1>Falha ao criar ticket</h1><p>Consulte os logs do serviço e tente novamente.</p>",
            status_code=502,
        )
