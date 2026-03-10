from __future__ import annotations

import os
from typing import Any

from sqlalchemy.orm import Session

from backend.storage import crud


class NotificationService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def notify_high_severity(self, run_id: str, alerts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        sent: list[dict[str, Any]] = []
        for alert in alerts:
            if alert["severity"] != "HIGH":
                continue
            status = "mock_sent" if os.getenv("MOCK_MODE", "true").lower() == "true" else "queued"
            payload = {
                "ticket_id": alert["ticket_id"],
                "rule_id": alert["rule_id"],
                "severity": alert["severity"],
                "detail": alert["detail"],
            }
            crud.create_notification(self.db, run_id, "webhook", alert["severity"], payload, status)
            sent.append({"channel": "webhook", "status": status, "payload": payload})
        return sent

