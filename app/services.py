from __future__ import annotations

import hashlib
import logging
import re
import unicodedata
from typing import Any
from urllib.parse import urlparse

import httpx
from opentelemetry import trace
from opentelemetry.trace import SpanKind

from app.config import Settings
from app.models import Alert


logger = logging.getLogger(__name__)
tracer = trace.get_tracer("signoz-discord-jira.integrations")


def _integration_attributes(
    alert: Alert, alert_id: int, channel: str, provider: str
) -> dict[str, str | int]:
    return {
        "alert.id": alert_id,
        "alert.name": alert_title(alert),
        "alert.severity": alert_severity(alert),
        "client.id": alert_client(alert),
        "notification.channel": channel,
        "external.system": provider,
    }


def _set_destination(span: trace.Span, url: str) -> None:
    parsed = urlparse(url)
    # Do not attach the full URL: Discord webhook paths contain credentials.
    if parsed.hostname:
        span.set_attribute("server.address", parsed.hostname)
        span.set_attribute("destination.address", parsed.hostname)
    if parsed.port:
        span.set_attribute("server.port", parsed.port)
    if parsed.scheme:
        span.set_attribute("url.scheme", parsed.scheme)


def alert_fingerprint(alert: Alert) -> str:
    if alert.fingerprint:
        return alert.fingerprint
    stable = f"{alert.labels}|{alert.startsAt}|{alert.annotations}"
    return hashlib.sha256(stable.encode()).hexdigest()


def alert_title(alert: Alert) -> str:
    return str(alert.annotations.get("summary") or alert.labels.get("alertname") or "Alerta do SigNoz")


def alert_client(alert: Alert) -> str:
    """Return a stable client identifier without logging the full alert payload."""
    for label in ("client", "cliente", "customer", "customer_id", "host.name", "userid"):
        value = alert.labels.get(label)
        if value is not None and str(value).strip():
            return str(value).strip()
    return "nao informado"


def alert_severity(alert: Alert) -> str:
    return str(alert.labels.get("severity") or "nao informada").strip().lower()


def alert_description(alert: Alert) -> str:
    details = alert.annotations.get("description") or alert.annotations.get("message") or "Sem descrição."
    labels = "\n".join(f"- {key}: {value}" for key, value in sorted(alert.labels.items()))
    return f"{details}\n\nLabels:\n{labels or '- nenhum'}\n\nInício: {alert.startsAt or 'não informado'}"


def is_critical_alert(alert: Alert) -> bool:
    return (
        alert.status.lower() != "resolved"
        and str(alert.labels.get("severity", "")).strip().lower() == "critical"
    )


def sms_message(alert: Alert) -> str:
    service = alert.labels.get("service") or alert.labels.get("job") or "n/a"
    host_name = alert.labels.get("host.name") or "n/a"
    user_id = alert.labels.get("userid") or "n/a"
    started_at = alert.startsAt or "n/a"
    raw = (
        f"CRITICAL SigNoz; userid: {user_id}; host.name: {host_name}; "
        f"alerta: {alert_title(alert)}; servico: {service}; inicio: {started_at}"
    )
    # Mantém o SMS no alfabeto GSM básico e evita a redução para 70 caracteres do UCS-2.
    ascii_text = unicodedata.normalize("NFKD", raw).encode("ascii", "ignore").decode("ascii")
    compact = re.sub(r"\s+", " ", ascii_text).strip()
    return compact[:160].rstrip()


def discord_message(alert: Alert) -> dict[str, Any]:
    severity = str(alert.labels.get("severity", "warning")).lower()
    color = {"critical": 0xED4245, "error": 0xED4245, "warning": 0xFEE75C}.get(severity, 0x5865F2)
    fields = [
        {"name": str(key)[:256], "value": str(value)[:1024], "inline": True}
        for key, value in list(alert.labels.items())[:12]
    ]
    embed: dict[str, Any] = {
        "title": alert_title(alert)[:256],
        "description": alert_description(alert)[:4096],
        "color": color,
        "fields": fields,
        "footer": {"text": f"SigNoz • {alert.status}"},
    }
    if alert.generatorURL:
        embed["url"] = alert.generatorURL
    return {"embeds": [embed], "allowed_mentions": {"parse": []}}


async def send_to_discord(
    client: httpx.AsyncClient,
    settings: Settings,
    message: dict[str, Any],
    alert: Alert,
    alert_id: int,
) -> None:
    url = settings.discord_webhook_url.get_secret_value()
    with tracer.start_as_current_span(
        "notification.discord.send",
        kind=SpanKind.CLIENT,
        attributes=_integration_attributes(alert, alert_id, "discord", "discord"),
    ) as span:
        _set_destination(span, url)
        try:
            response = await client.post(url, params={"wait": "true"}, json=message)
            span.set_attribute("http.response.status_code", response.status_code)
            response.raise_for_status()
        except Exception:
            span.set_attribute("event.outcome", "failure")
            raise
        else:
            span.set_attribute("event.outcome", "success")


async def send_twilio_sms(
    client: httpx.AsyncClient, settings: Settings, alert: Alert, recipient: str
) -> None:
    auth_token = settings.twilio_auth_token.get_secret_value()
    api_key_secret = settings.twilio_api_key_secret.get_secret_value()
    if settings.twilio_api_key_sid and api_key_secret:
        username = settings.twilio_api_key_sid
        password = api_key_secret
    elif settings.twilio_account_sid and auth_token:
        username = settings.twilio_account_sid
        password = auth_token
    else:
        raise RuntimeError(
            "Configure TWILIO_AUTH_TOKEN ou o par "
            "TWILIO_API_KEY_SID/TWILIO_API_KEY_SECRET"
        )

    if (
        not settings.twilio_account_sid
        or not settings.twilio_from_number
    ):
        raise RuntimeError("Configuração do Twilio incompleta")

    url = (
        f"{settings.twilio_api_base_url.rstrip('/')}/Accounts/"
        f"{settings.twilio_account_sid}/Messages.json"
    )
    body = settings.twilio_sms_template or sms_message(alert)
    with tracer.start_as_current_span("external.twilio.http", kind=SpanKind.CLIENT) as span:
        _set_destination(span, url)
        span.set_attribute("external.system", "twilio")
        response = await client.post(
            url,
            auth=(username, password),
            data={"From": settings.twilio_from_number, "To": recipient, "Body": body},
        )
        span.set_attribute("http.response.status_code", response.status_code)
        response.raise_for_status()


async def send_critical_sms(
    client: httpx.AsyncClient, settings: Settings, alert: Alert, alert_id: int
) -> None:
    recipients = settings.critical_sms_recipients
    if not recipients:
        raise RuntimeError("Nenhum destinatário de SMS configurado")

    if not settings.twilio_enabled:
        raise RuntimeError("Twilio não está habilitado")

    with tracer.start_as_current_span(
        "notification.sms.send",
        attributes={
            **_integration_attributes(alert, alert_id, "sms", "sms"),
            "messaging.destination_count": len(recipients),
        },
    ) as sms_span:
        for recipient in recipients:
            with tracer.start_as_current_span(
                "notification.sms.provider.send",
                kind=SpanKind.CLIENT,
                attributes=_integration_attributes(alert, alert_id, "sms", "twilio"),
            ) as provider_span:
                try:
                    await send_twilio_sms(client, settings, alert, recipient)
                except Exception:
                    provider_span.set_attribute("event.outcome", "failure")
                    logger.exception("Falha no envio do alerta %s via Twilio", alert_id)
                    raise
                else:
                    provider_span.set_attribute("event.outcome", "success")
            logger.info("SMS do alerta %s enviado via Twilio", alert_id)
        sms_span.set_attribute("event.outcome", "success")


