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
                sms_status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )"""
        )
        columns = {
            row["name"] for row in self.connection.execute("PRAGMA table_info(alerts)").fetchall()
        }
        if "sms_status" not in columns:
            self.connection.execute(
                "ALTER TABLE alerts ADD COLUMN sms_status TEXT NOT NULL DEFAULT 'pending'"
            )
        self.connection.commit()

    def claim_sms_sending(self, alert_id: int) -> bool:
        """Reserva atomicamente o envio de SMS e evita duplicação em retries."""
        with self.lock:
            self.connection.execute("BEGIN IMMEDIATE")
            row = self.connection.execute(
                "SELECT sms_status FROM alerts WHERE id = ?", (alert_id,)
            ).fetchone()
            if not row or row["sms_status"] != "pending":
                self.connection.commit()
                return False
            self.connection.execute(
                "UPDATE alerts SET sms_status = 'sending' WHERE id = ?", (alert_id,)
            )
            self.connection.commit()
            return True

    def set_sms_sent(self, alert_id: int) -> None:
        with self.lock:
            self.connection.execute(
                "UPDATE alerts SET sms_status = 'sent' WHERE id = ?", (alert_id,)
            )
            self.connection.commit()

    def release_sms_sending(self, alert_id: int) -> None:
        with self.lock:
            self.connection.execute(
                "UPDATE alerts SET sms_status = 'pending' WHERE id = ? AND sms_status = 'sending'",
                (alert_id,),
            )
            self.connection.commit()

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

