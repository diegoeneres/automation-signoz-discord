from app.db import AlertStore


def test_jira_creation_can_only_be_claimed_once(tmp_path) -> None:
    store = AlertStore(str(tmp_path / "test.db"))
    alert_id = store.put("fingerprint", {"status": "firing"})

    first_status, _ = store.claim_jira_creation(alert_id)
    second_status, _ = store.claim_jira_creation(alert_id)

    assert first_status == "claimed"
    assert second_status == "creating"

    store.set_jira(alert_id, "OPS-1", "https://example.atlassian.net/browse/OPS-1")
    final_status, record = store.claim_jira_creation(alert_id)
    assert final_status == "created"
    assert record and record["jira_key"] == "OPS-1"

