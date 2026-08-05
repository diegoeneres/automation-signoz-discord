from app.models import Alert
from app.services import (
    alert_description,
    alert_fingerprint,
    discord_message,
    ticket_signature,
    valid_ticket_signature,
)


def test_fingerprint_is_stable_without_upstream_fingerprint() -> None:
    alert = Alert(labels={"alertname": "HighCPU"}, annotations={"summary": "CPU alta"}, startsAt="2026-01-01")
    assert alert_fingerprint(alert) == alert_fingerprint(alert)


def test_discord_message_has_jira_button_for_firing_alert() -> None:
    alert = Alert(status="firing", labels={"severity": "critical"}, annotations={"summary": "Falha"})
    message = discord_message(alert, 42, "https://alerts.example.com/tickets/42/create?signature=abc")
    button = message["components"][0]["components"][0]
    assert button["style"] == 5
    assert button["url"].startswith("https://alerts.example.com/tickets/42/create")
    assert message["embeds"][0]["color"] == 0xED4245


def test_resolved_alert_has_no_ticket_button() -> None:
    assert discord_message(Alert(status="resolved"), 1, "https://example.com")["components"] == []


def test_description_contains_labels() -> None:
    text = alert_description(Alert(labels={"service": "checkout"}, annotations={"description": "Erro"}))
    assert "Erro" in text
    assert "service: checkout" in text


def test_ticket_link_signature() -> None:
    signature = ticket_signature(42, "secret")
    assert valid_ticket_signature(42, signature, "secret")
    assert not valid_ticket_signature(43, signature, "secret")
