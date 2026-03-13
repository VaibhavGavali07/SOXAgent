from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

from fastapi.testclient import TestClient


def load_app(tmp_path: Path):
    os.environ["DB_PATH"] = str(tmp_path / "test_agent.db")
    os.environ["MOCK_MODE"] = "true"
    os.environ["MOCK_LLM"] = "true"
    os.environ["ENABLE_EMBEDDINGS"] = "true"

    for name in list(sys.modules.keys()):
        if name.startswith("backend"):
            sys.modules.pop(name)

    module = importlib.import_module("backend.main")
    return module.app


def test_fetch_and_store_results(tmp_path: Path):
    app = load_app(tmp_path)
    client = TestClient(app)

    health = client.get("/api/health")
    assert health.status_code == 200

    run = client.post("/api/fetch/servicenow", json={"filters": {}})
    assert run.status_code == 200
    run_id = run.json()["run_id"]

    summary = client.get("/api/dashboard/summary")
    assert summary.status_code == 200
    assert summary.json()["stats"]["tickets_analyzed"] >= 3
    first_ticket_count = summary.json()["stats"]["tickets_analyzed"]

    violations = client.get("/api/violations")
    assert violations.status_code == 200
    assert len(violations.json()) >= 3

    tickets = client.get("/api/tickets")
    assert tickets.status_code == 200
    ticket_id = tickets.json()[0]["id"]

    ticket = client.get(f"/api/tickets/{ticket_id}")
    assert ticket.status_code == 200
    assert ticket.json()["ticket"]["canonical_json"]["comments"]
    assert len(ticket.json()["rule_results"]) == 8

    rerun = client.post(f"/api/analyze/ticket/{ticket_id}")
    assert rerun.status_code == 200
    assert rerun.json()["run_id"] != run_id

    second_run = client.post("/api/fetch/servicenow", json={"filters": {}})
    assert second_run.status_code == 200

    summary_after_second_fetch = client.get("/api/dashboard/summary")
    assert summary_after_second_fetch.status_code == 200
    assert summary_after_second_fetch.json()["stats"]["tickets_analyzed"] == first_ticket_count
