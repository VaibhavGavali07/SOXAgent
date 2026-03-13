from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from backend.connectors.servicenow_connector import ServiceNowConnector
from backend.llm.embed_client import EmbeddingClient
from backend.llm.llm_evaluator import LLMEvaluator
from backend.llm.provider_factory import get_llm_provider
from backend.services.evidence_service import build_timeline, related_policy_snippets
from backend.services.notification_service import NotificationService
from backend.storage import crud
from backend.storage.db import SessionLocal


class RunStateStore:
    def __init__(self) -> None:
        self.events: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.status: dict[str, str] = {}

    def publish(self, run_id: str, event: dict[str, Any]) -> None:
        payload = {
            "run_id": run_id,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            **event,
        }
        self.events[run_id].append(payload)
        if "status" in event:
            self.status[run_id] = event["status"]

    async def stream(self, run_id: str):
        index = 0
        while True:
            while index < len(self.events[run_id]):
                payload = self.events[run_id][index]
                yield f"data: {json.dumps(payload)}\n\n"
                index += 1
            if self.status.get(run_id) in {"completed", "failed"}:
                break
            await asyncio.sleep(1)


run_state_store = RunStateStore()


class AnalyzerService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.embedding_client = EmbeddingClient()
        self.notification_service = NotificationService(db)
        compliance_config = self._load_connector_config("compliance")
        custom_rules = self._load_custom_rules()
        self.evaluator = LLMEvaluator(get_llm_provider(db), compliance_config=compliance_config, custom_rules=custom_rules)

    def _load_custom_rules(self) -> list[dict[str, Any]]:
        rules = []
        for config in crud.list_configs(self.db):
            if config.config_type == "rule":
                data = dict(config.data)
                if data.get("active", True):
                    rules.append(data)
        return rules

    def _load_connector_config(self, source: str) -> dict[str, Any]:
        for config in crud.list_configs(self.db):
            if config.config_type == source:
                return dict(config.data)
        return {}

    def run(self, run_id: str, source: str, filters: dict[str, Any] | None = None) -> dict[str, Any]:
        filters = filters or {}
        if source == "servicenow" and not filters.get("instance_url"):
            saved = self._load_connector_config("servicenow")
            filters = {**saved, **filters}
        run_state_store.publish(run_id, {"status": "running", "message": f"Starting {source} analysis"})
        crud.update_run(self.db, run_id, status="running", metadata=filters, started=True)

        connector = ServiceNowConnector()
        fetched = connector.fetch(filters)
        tickets = fetched["tickets"]
        existing_ticket_ids = crud.get_existing_ticket_ids(self.db, source, [ticket["ticket_id"] for ticket in tickets])
        new_tickets = [ticket for ticket in tickets if ticket["ticket_id"] not in existing_ticket_ids]
        crud.update_run(
            self.db,
            run_id,
            total_items=len(new_tickets),
            metadata={
                **filters,
                "source": source,
                "fetched_tickets": len(tickets),
                "existing_tickets": len(existing_ticket_ids),
                "new_tickets": len(new_tickets),
            },
        )
        run_state_store.publish(
            run_id,
            {
                "status": "running",
                "message": f"Fetched {len(tickets)} tickets; {len(new_tickets)} new tickets to analyze",
                "progress": 0,
                "total": len(new_tickets),
            },
        )

        alert_payloads: list[dict[str, Any]] = []
        for index, ticket in enumerate(new_tickets, start=1):
            self._persist_raw_records(source, fetched, ticket["ticket_id"])
            ticket_row = crud.create_ticket(self.db, ticket)
            self._persist_embeddings(ticket_row.id, ticket)

            retrieval_context = {
                "timeline": build_timeline(ticket),
                "policy_snippets": related_policy_snippets(),
                "similar_violations": self._similar_violations(ticket),
            }
            evaluation, prompt_text, prompt_hash = self.evaluator.evaluate_ticket(ticket, retrieval_context, run_id)
            crud.create_llm_response(
                self.db,
                run_id=run_id,
                ticket_id=ticket["ticket_id"],
                ticket_db_id=ticket_row.id,
                provider=self.evaluator.chat_provider.provider_name,
                model=self.evaluator.chat_provider.model_name,
                prompt_hash=prompt_hash,
                prompt_text=prompt_text,
                response_json=evaluation.model_dump(),
                overall_assessment=evaluation.overall_assessment,
            )
            results = crud.replace_rule_results(
                self.db,
                run_id=run_id,
                ticket_db_id=ticket_row.id,
                ticket_id=ticket["ticket_id"],
                source=ticket["source"],
                results=[rule.model_dump() for rule in evaluation.rules],
            )
            alerts = crud.create_alerts_for_failures(
                self.db,
                run_id=run_id,
                ticket_db_id=ticket_row.id,
                ticket_id=ticket["ticket_id"],
                source=ticket["source"],
                results=[rule.model_dump() for rule in evaluation.rules],
            )
            alert_payloads.extend(
                {
                    "ticket_id": alert.ticket_id,
                    "rule_id": alert.rule_id,
                    "severity": alert.severity,
                    "detail": alert.detail,
                }
                for alert in alerts
            )
            crud.update_run(self.db, run_id, processed_items=index)
            run_state_store.publish(
                run_id,
                {
                    "status": "running",
                    "message": f'Analyzed {ticket["ticket_id"]}',
                    "progress": index,
                    "total": len(new_tickets),
                    "ticket_db_id": ticket_row.id,
                    "failed_rules": [result.rule_id for result in results if result.status == "FAIL"],
                },
            )

        notifications = self.notification_service.notify_high_severity(run_id, alert_payloads)
        report = crud.summarize_run(self.db, run_id)
        report["notifications"] = notifications
        crud.create_audit_report(self.db, run_id, source, report)
        crud.update_run(self.db, run_id, status="completed", finished=True)
        run_state_store.publish(run_id, {"status": "completed", "message": "Analysis completed", "summary": report})
        return report

    def rerun_ticket(self, run_id: str, ticket_db_id: int) -> dict[str, Any]:
        run_state_store.publish(run_id, {"status": "running", "message": f"Re-running ticket {ticket_db_id}"})
        crud.update_run(self.db, run_id, status="running", total_items=1, processed_items=0, started=True)
        ticket_row = crud.get_ticket(self.db, ticket_db_id)
        if not ticket_row:
            crud.update_run(self.db, run_id, status="failed", finished=True)
            run_state_store.publish(run_id, {"status": "failed", "message": "Ticket not found"})
            return {"error": "Ticket not found"}

        ticket = ticket_row.canonical_json
        retrieval_context = {
            "timeline": build_timeline(ticket),
            "policy_snippets": related_policy_snippets(),
            "similar_violations": self._similar_violations(ticket),
        }
        evaluation, prompt_text, prompt_hash = self.evaluator.evaluate_ticket(ticket, retrieval_context, run_id)
        crud.create_llm_response(
            self.db,
            run_id=run_id,
            ticket_id=ticket["ticket_id"],
            ticket_db_id=ticket_row.id,
            provider=self.evaluator.chat_provider.provider_name,
            model=self.evaluator.chat_provider.model_name,
            prompt_hash=prompt_hash,
            prompt_text=prompt_text,
            response_json=evaluation.model_dump(),
            overall_assessment=evaluation.overall_assessment,
        )
        crud.replace_rule_results(
            self.db,
            run_id=run_id,
            ticket_db_id=ticket_row.id,
            ticket_id=ticket["ticket_id"],
            source=ticket["source"],
            results=[rule.model_dump() for rule in evaluation.rules],
        )
        crud.create_alerts_for_failures(
            self.db,
            run_id=run_id,
            ticket_db_id=ticket_row.id,
            ticket_id=ticket["ticket_id"],
            source=ticket["source"],
            results=[rule.model_dump() for rule in evaluation.rules],
        )
        crud.update_run(self.db, run_id, status="completed", processed_items=1, finished=True)
        run_state_store.publish(run_id, {"status": "completed", "message": f'Re-analysis finished for {ticket["ticket_id"]}'})
        return {"run_id": run_id, "ticket_id": ticket["ticket_id"]}

    def _persist_raw_records(self, source: str, fetched: dict[str, list[dict[str, Any]]], ticket_id: str) -> None:
        raw_ticket = next(
            (
                item
                for item in fetched["raw_tickets"]
                if item.get("key") == ticket_id or item.get("number") == ticket_id
            ),
            None,
        )
        if raw_ticket:
            crud.create_raw_record(self.db, source, "ticket", ticket_id, raw_ticket)
        for install in fetched.get("software_installs", []):
            if install["ticket_id"] == ticket_id:
                crud.create_raw_record(self.db, source, "software_install", install["software_name"], install)
        for identity_log in fetched.get("identity_logs", []):
            if identity_log["ticket_id"] == ticket_id:
                crud.create_raw_record(self.db, source, "identity_log", identity_log["ticket_id"], identity_log)
        for workflow_log in fetched.get("workflow_logs", []):
            if workflow_log["ticket_id"] == ticket_id:
                crud.create_raw_record(self.db, source, "workflow_log", workflow_log["ticket_id"], workflow_log)

    def _persist_embeddings(self, ticket_db_id: int, ticket: dict[str, Any]) -> None:
        text_blocks = [
            ticket["summary"] + "\n" + ticket["description"],
            *(comment["body"] for comment in ticket.get("comments", [])),
            *(
                f'{approval["decision"]} by {approval["approver"]["name"]} at {approval["timestamp"]}'
                for approval in ticket.get("approvals", [])
            ),
        ]
        for idx, text in enumerate(text_blocks):
            vector = self.embedding_client.embed_text(text)
            if not vector:
                continue
            crud.save_embedding(self.db, "ticket_text", f"{ticket_db_id}:{idx}", vector, text)

    def _similar_violations(self, ticket: dict[str, Any]) -> list[dict[str, Any]]:
        query_vector = self.embedding_client.embed_text(ticket["summary"] + "\n" + ticket["description"])
        if not query_vector:
            return []
        matches = []
        for embedding in crud.list_embeddings(self.db, "ticket_text"):
            similarity = self.embedding_client.cosine_similarity(query_vector, embedding.vector_json)
            if similarity > 0.82:
                matches.append({"entity_id": embedding.entity_id, "similarity": round(similarity, 3), "preview": embedding.text_preview})
        matches.sort(key=lambda item: item["similarity"], reverse=True)
        return matches[:5]


def run_analysis_job(run_id: str, source: str, filters: dict[str, Any] | None = None) -> None:
    with SessionLocal() as db:
        try:
            service = AnalyzerService(db)
            service.run(run_id, source, filters)
        except Exception as exc:
            crud.update_run(db, run_id, status="failed", finished=True)
            run_state_store.publish(run_id, {"status": "failed", "message": str(exc)})


def rerun_ticket_job(run_id: str, ticket_db_id: int) -> None:
    with SessionLocal() as db:
        try:
            service = AnalyzerService(db)
            service.rerun_ticket(run_id, ticket_db_id)
        except Exception as exc:
            crud.update_run(db, run_id, status="failed", finished=True)
            run_state_store.publish(run_id, {"status": "failed", "message": str(exc)})
