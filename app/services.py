from __future__ import annotations

import hashlib
import hmac
from typing import Any

import httpx

from app.config import Settings
from app.models import Alert


def alert_fingerprint(alert: Alert) -> str:
    if alert.fingerprint:
        return alert.fingerprint
    stable = f"{alert.labels}|{alert.startsAt}|{alert.annotations}"
    return hashlib.sha256(stable.encode()).hexdigest()


def alert_title(alert: Alert) -> str:
    return str(alert.annotations.get("summary") or alert.labels.get("alertname") or "Alerta do SigNoz")


def alert_description(alert: Alert) -> str:
    details = alert.annotations.get("description") or alert.annotations.get("message") or "Sem descrição."
    labels = "\n".join(f"- {key}: {value}" for key, value in sorted(alert.labels.items()))
    return f"{details}\n\nLabels:\n{labels or '- nenhum'}\n\nInício: {alert.startsAt or 'não informado'}"


def ticket_signature(alert_id: int, secret: str) -> str:
    return hmac.new(secret.encode(), str(alert_id).encode(), hashlib.sha256).hexdigest()


def valid_ticket_signature(alert_id: int, signature: str, secret: str) -> bool:
    return hmac.compare_digest(ticket_signature(alert_id, secret), signature)


def discord_message(alert: Alert, alert_id: int, ticket_url: str) -> dict[str, Any]:
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
    components = []
    if alert.status.lower() != "resolved":
        components = [{
            "type": 1,
            "components": [{"type": 2, "style": 5, "label": "Criar ticket no Jira", "url": ticket_url}],
        }]
    return {"embeds": [embed], "components": components, "allowed_mentions": {"parse": []}}


async def send_to_discord(client: httpx.AsyncClient, settings: Settings, message: dict[str, Any]) -> None:
    response = await client.post(
        settings.discord_webhook_url.get_secret_value(),
        params={"with_components": "true", "wait": "true"},
        json=message,
    )
    response.raise_for_status()


async def create_jira_issue(client: httpx.AsyncClient, settings: Settings, alert: Alert) -> tuple[str, str]:
    payload = {
        "fields": {
            "project": {"key": settings.jira_project_key},
            "issuetype": {"name": settings.jira_issue_type},
            "summary": alert_title(alert)[:255],
            "description": {
                "type": "doc",
                "version": 1,
                "content": [{
                    "type": "paragraph",
                    "content": [{"type": "text", "text": alert_description(alert)[:30000]}],
                }],
            },
            "labels": ["signoz", "monitoring"],
        }
    }
    response = await client.post(
        f"{settings.jira_base_url.rstrip('/')}/rest/api/3/issue",
        auth=(settings.jira_email, settings.jira_api_token.get_secret_value()),
        headers={"Accept": "application/json"},
        json=payload,
    )
    response.raise_for_status()
    key = response.json()["key"]
    return key, f"{settings.jira_base_url.rstrip('/')}/browse/{key}"
