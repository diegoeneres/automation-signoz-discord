from app.db import AlertStore


def test_sms_can_only_be_claimed_once(tmp_path) -> None:
    store = AlertStore(str(tmp_path / "test.db"))
    alert_id = store.put("critical-alert", {"status": "firing"})

    assert store.claim_sms_sending(alert_id)
    assert not store.claim_sms_sending(alert_id)

    store.release_sms_sending(alert_id)
    assert store.claim_sms_sending(alert_id)

    store.set_sms_sent(alert_id)
    assert not store.claim_sms_sending(alert_id)
