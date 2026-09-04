import asyncio
import base64
from types import SimpleNamespace
from urllib.parse import parse_qs

import httpx
from pydantic import SecretStr

from app.models import Alert
from app.services import (
    alert_client,
    alert_description,
    alert_fingerprint,
    alert_severity,
    discord_message,
    is_critical_alert,
    send_critical_sms,
    sms_message,
)


def test_fingerprint_is_stable_without_upstream_fingerprint() -> None:
    alert = Alert(labels={"alertname": "HighCPU"}, annotations={"summary": "CPU alta"}, startsAt="2026-01-01")
    assert alert_fingerprint(alert) == alert_fingerprint(alert)


def test_discord_message_contains_alert_without_components() -> None:
    alert = Alert(status="firing", labels={"severity": "critical"}, annotations={"summary": "Falha"})
    message = discord_message(alert)
    assert message["embeds"][0]["title"] == "Falha"
    assert "components" not in message
    assert message["embeds"][0]["color"] == 0xED4245


def test_resolved_alert_has_no_components() -> None:
    assert "components" not in discord_message(Alert(status="resolved"))


def test_description_contains_labels() -> None:
    text = alert_description(Alert(labels={"service": "checkout"}, annotations={"description": "Erro"}))
    assert "Erro" in text
    assert "service: checkout" in text


def test_alert_client_uses_supported_labels_in_priority_order() -> None:
    alert = Alert(labels={"client": "acme", "host.name": "host-01", "userid": "fallback-user"})
    assert alert_client(alert) == "acme"
    assert alert_client(Alert(labels={"host.name": "cliente-host-01"})) == "cliente-host-01"
    assert (
        alert_client(Alert(labels={"host.name": "cliente-host-01", "userid": "user-42"}))
        == "cliente-host-01"
    )
    assert alert_client(Alert(labels={"userid": "user-42"})) == "user-42"
    assert alert_client(Alert()) == "nao informado"


def test_alert_severity_is_normalized() -> None:
    assert alert_severity(Alert(labels={"severity": "CRITICAL"})) == "critical"
    assert alert_severity(Alert()) == "nao informada"


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


def test_send_critical_sms_uses_twilio_api() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == (
            "https://api.twilio.com/2010-04-01/Accounts/"
            "AC00000000000000000000000000000000/Messages.json"
        )
        expected_auth = base64.b64encode(b"SK00000000000000000000000000000000:api-key-secret").decode()
        assert request.headers["Authorization"] == f"Basic {expected_auth}"
        form = parse_qs(request.content.decode())
        assert form["From"] == ["+15551234567"]
        assert form["To"] == ["+5511999999999"]
        assert "host.name: api-01" in form["Body"][0]
        return httpx.Response(201, json={"sid": "SM00000000000000000000000000000000"})

    settings = SimpleNamespace(
        twilio_account_sid="AC00000000000000000000000000000000",
        twilio_auth_token=SecretStr(""),
        twilio_api_key_sid="SK00000000000000000000000000000000",
        twilio_api_key_secret=SecretStr("api-key-secret"),
        twilio_from_number="+15551234567",
        twilio_recipients=["+5511999999999"],
        twilio_sms_template="",
        twilio_api_base_url="https://api.twilio.com/2010-04-01",
        twilio_enabled=True,
        critical_sms_recipients=["+5511999999999"],
    )
    alert = Alert(labels={"host.name": "api-01", "userid": "cliente-123"})

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await send_critical_sms(client, settings, alert, 42)  # type: ignore[arg-type]

    asyncio.run(run())


def test_send_critical_sms_accepts_account_auth_token() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        expected_auth = base64.b64encode(
            b"AC00000000000000000000000000000000:account-auth-token"
        ).decode()
        assert request.headers["Authorization"] == f"Basic {expected_auth}"
        form = parse_qs(request.content.decode())
        assert form["Body"] == ["sms_internal_alerts"]
        return httpx.Response(201, json={"sid": "SM00000000000000000000000000000000"})

    settings = SimpleNamespace(
        twilio_account_sid="AC00000000000000000000000000000000",
        twilio_auth_token=SecretStr("account-auth-token"),
        twilio_api_key_sid="",
        twilio_api_key_secret=SecretStr(""),
        twilio_from_number="+17372508034",
        twilio_recipients=["+5541992782701"],
        twilio_sms_template="sms_internal_alerts",
        twilio_api_base_url="https://api.twilio.com/2010-04-01",
        twilio_enabled=True,
        critical_sms_recipients=["+5541992782701"],
    )

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await send_critical_sms(client, settings, Alert(), 42)  # type: ignore[arg-type]

    asyncio.run(run())

