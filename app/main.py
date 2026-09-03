from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Request, status

from app.config import Settings, get_settings
from app.db import AlertStore
from app.models import SignozWebhook
from app.services import (
    alert_client,
    alert_fingerprint,
    alert_severity,
    alert_title,
    discord_message,
    is_critical_alert,
    send_critical_sms,
    send_to_discord,
)
from app.telemetry import (
    alerts_received,
    configure_telemetry,
    notification_failures,
    notifications_sent,
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


app = FastAPI(title="SigNoz → Discord e SMS", version="0.4.0", lifespan=lifespan)
app.state.telemetry = configure_telemetry(app)


@app.get("/health")
async def health() -> dict[str, str]:
    logger.info("Health check concluido com sucesso")
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
        alert_name = alert_title(alert)
        client = alert_client(alert)
        severity = alert_severity(alert)
        log_context = {
            "event.name": "signoz.webhook.processed",
            "alert.id": alert_id,
            "alert.name": alert_name,
            "alert.severity": severity,
            "client.id": client,
        }
        try:
            await send_to_discord(
                request.app.state.http, settings, discord_message(alert), alert, alert_id
            )
        except Exception:
            notification_failures.add(1, {"channel": "discord"})
            logger.exception(
                "Falha ao processar webhook do SigNoz: alerta %s para o cliente %s. Severidade: %s. Falha no envio ao Discord",
                alert_name,
                client,
                severity,
                extra={
                    **log_context,
                    "notification.channel": "discord",
                    "event.outcome": "failure",
                },
            )
            raise
        notifications_sent.add(1, {"channel": "discord"})
        logger.info(
            "Webhook do SigNoz processado: alerta %s para o cliente %s enviado com sucesso. Severidade: %s",
            alert_name,
            client,
            severity,
            extra={**log_context, "notification.channel": "discord", "event.outcome": "success"},
        )
        if settings.sms_enabled and is_critical_alert(alert):
            claimed = request.app.state.store.claim_sms_sending(alert_id)
            if claimed:
                try:
                    await send_critical_sms(request.app.state.http, settings, alert, alert_id)
                    request.app.state.store.set_sms_sent(alert_id)
                except Exception:
                    request.app.state.store.release_sms_sending(alert_id)
                    notification_failures.add(1, {"channel": "sms"})
                    logger.exception(
                        "Falha ao processar webhook do SigNoz: alerta %s para o cliente %s. Severidade: %s. Falha no envio do SMS",
                        alert_name,
                        client,
                        severity,
                        extra={
                            **log_context,
                            "notification.channel": "sms",
                            "event.outcome": "failure",
                        },
                    )
                    raise HTTPException(status_code=502, detail="Falha ao enviar SMS")
                else:
                    notifications_sent.add(1, {"channel": "sms"})
                    logger.info(
                        "Webhook do SigNoz processado: alerta %s para o cliente %s enviado com sucesso. Severidade: %s. SMS enviado com sucesso",
                        alert_name,
                        client,
                        severity,
                        extra={
                            **log_context,
                            "notification.channel": "sms",
                            "event.outcome": "success",
                        },
                    )
        sent += 1
    return {"received": len(payload.alerts), "sent": sent}


