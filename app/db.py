from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Optional


class AlertStore:
    def __init__(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.lock = threading.Lock()
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fingerprint TEXT NOT NULL UNIQUE,
                payload TEXT NOT NULL,
                jira_key TEXT,
                jira_url TEXT,
                jira_status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )"""
        )
        self.connection.commit()

    def claim_jira_creation(self, alert_id: int) -> tuple[str, Optional[dict[str, Any]]]:
        """Reserva atomicamente a criação; retorna claimed, creating, created ou missing."""
        with self.lock:
            self.connection.execute("BEGIN IMMEDIATE")
            row = self.connection.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,)).fetchone()
            if not row:
                self.connection.rollback()
                return "missing", None
            record = dict(row)
            record["payload"] = json.loads(record["payload"])
            if record["jira_key"]:
                self.connection.commit()
                return "created", record
            if record["jira_status"] == "creating":
                self.connection.commit()
                return "creating", record
            self.connection.execute("UPDATE alerts SET jira_status = 'creating' WHERE id = ?", (alert_id,))
            self.connection.commit()
            return "claimed", record

    def put(self, fingerprint: str, payload: dict[str, Any]) -> int:
        with self.lock:
            self.connection.execute(
                "INSERT OR IGNORE INTO alerts(fingerprint, payload) VALUES (?, ?)",
                (fingerprint, json.dumps(payload)),
            )
            row = self.connection.execute(
                "SELECT id FROM alerts WHERE fingerprint = ?", (fingerprint,)
            ).fetchone()
            self.connection.commit()
            return int(row["id"])

    def get(self, alert_id: int) -> Optional[dict[str, Any]]:
        with self.lock:
            row = self.connection.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,)).fetchone()
        if not row:
            return None
        result = dict(row)
        result["payload"] = json.loads(result["payload"])
        return result

    def set_jira(self, alert_id: int, key: str, url: str) -> None:
        with self.lock:
            self.connection.execute(
                "UPDATE alerts SET jira_key = ?, jira_url = ?, jira_status = 'created' WHERE id = ? AND jira_key IS NULL",
                (key, url, alert_id),
            )
            self.connection.commit()

    def release_jira_creation(self, alert_id: int) -> None:
        with self.lock:
            self.connection.execute(
                "UPDATE alerts SET jira_status = 'pending' WHERE id = ? AND jira_key IS NULL", (alert_id,)
            )
            self.connection.commit()
