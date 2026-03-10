from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from backend.connectors.normalize import (
    normalize_identity_log,
    normalize_jira_ticket,
    normalize_software_install,
    normalize_workflow_log,
)


class JiraConnector:
    def __init__(self) -> None:
        self.sample_dir = Path(__file__).resolve().parent.parent / "sample_data"

    def fetch(self, filters: dict[str, Any] | None = None) -> dict[str, list[dict[str, Any]]]:
        filters = filters or {}
        if os.getenv("MOCK_MODE", "true").lower() == "true" or not filters.get("base_url"):
            return self._load_sample_data()
        return self._load_sample_data()

    def _load_sample_data(self) -> dict[str, list[dict[str, Any]]]:
        tickets = json.loads((self.sample_dir / "jira_sample.json").read_text(encoding="utf-8"))
        installs = json.loads((self.sample_dir / "software_installs.json").read_text(encoding="utf-8"))
        identity_logs = json.loads((self.sample_dir / "access_logs.json").read_text(encoding="utf-8"))
        workflow_logs = json.loads((self.sample_dir / "workflow_logs.json").read_text(encoding="utf-8"))
        return {
            "raw_tickets": tickets,
            "tickets": [
                normalize_jira_ticket(
                    raw,
                    {
                        "software_installs": [normalize_software_install(item) for item in installs if item["ticket_id"] == raw["key"]],
                        "identity_logs": [normalize_identity_log(item) for item in identity_logs if item["ticket_id"] == raw["key"]],
                        "workflow_logs": [normalize_workflow_log(item) for item in workflow_logs if item["ticket_id"] == raw["key"]],
                    },
                )
                for raw in tickets
            ],
            "software_installs": [normalize_software_install(item) for item in installs],
            "identity_logs": [normalize_identity_log(item) for item in identity_logs],
            "workflow_logs": [normalize_workflow_log(item) for item in workflow_logs],
        }

