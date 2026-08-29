from app.models import Alert
from app.services import (
    alert_description,
    alert_fingerprint,
    discord_message,
    is_critical_alert,
    sms_message,
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


def test_only_firing_critical_alert_triggers_sms() -> None:
    assert is_critical_alert(Alert(status="firing", labels={"severity": "CRITICAL"}))
    assert not is_critical_alert(Alert(status="resolved", labels={"severity": "critical"}))
    assert not is_critical_alert(Alert(status="firing", labels={"severity": "warning"}))


def test_sms_message_contains_alert_context() -> None:
    alert = Alert(
        labels={
            "severity": "critical",
            "service": "checkout",
            "host.name": "checkout-01",
            "userid": "usuario-123",
        },
        annotations={"summary": "CPU alta"},
        startsAt="2026-08-18T10:00:00Z",
    )
    message = sms_message(alert)
    assert "CPU alta" in message
    assert "checkout" in message
    assert "host.name: checkout-01" in message
    assert "userid: usuario-123" in message
    assert len(message) <= 160


def test_sms_message_uses_na_when_host_name_and_userid_are_missing() -> None:
    alert = Alert()

    message = sms_message(alert)

    assert "host.name: n/a" in message
    assert "userid: n/a" in message


def test_sms_message_is_single_segment_ascii() -> None:
    alert = Alert(
        labels={"severity": "critical", "service": "serviço-com-nome-muito-longo"},
        annotations={"summary": "Aplicação indisponível 🚨 " * 20},
        startsAt="2026-08-18T10:00:00Z",
    )
    message = sms_message(alert)
    assert len(message) <= 160
    assert message.isascii()
    assert "Aplicacao indisponivel" in message
