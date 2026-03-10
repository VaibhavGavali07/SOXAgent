from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.llm.rule_ids import canonical_rule_id
from backend.storage import crud
from backend.storage.db import get_db


router = APIRouter(prefix="/api", tags=["violations"])


@router.get("/violations")
def get_violations(
    severity: str | None = Query(default=None),
    rule_id: str | None = Query(default=None),
    source: str | None = Query(default=None),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    alerts = crud.list_alerts(db, severity=severity, rule_id=rule_id, source=source, date_from=date_from, date_to=date_to)
    return [
        {
            "id": alert.id,
            "run_id": alert.run_id,
            "ticket_db_id": alert.ticket_db_id,
            "ticket_id": alert.ticket_id,
            "source": alert.source,
            "rule_id": canonical_rule_id(alert.rule_id),
            "severity": alert.severity,
            "status": alert.status,
            "title": alert.title,
            "detail": alert.detail,
            "evidence": alert.evidence_json,
            "created_at": alert.created_at.isoformat(),
        }
        for alert in alerts
    ]


@router.get("/violations/{alert_id}")
def get_violation(alert_id: int, db: Session = Depends(get_db)):
    alert = crud.get_alert(db, alert_id)
    if not alert:
        return {"error": "Alert not found"}
    ticket_detail = crud.get_ticket_detail(db, alert.ticket_db_id)
    return {
        "id": alert.id,
        "ticket_id": alert.ticket_id,
        "ticket_db_id": alert.ticket_db_id,
        "source": alert.source,
        "rule_id": canonical_rule_id(alert.rule_id),
        "severity": alert.severity,
        "detail": alert.detail,
        "evidence": alert.evidence_json,
        "ticket": ticket_detail["ticket"].canonical_json if ticket_detail else None,
        "rule_results": [
            {
                "rule_id": canonical_rule_id(result.rule_id),
                "rule_name": result.rule_name,
                "severity": result.severity,
                "status": result.status,
                "confidence": result.confidence,
                "why": result.why,
                "evidence": result.evidence_json,
                "recommended_action": result.recommended_action,
            }
            for result in (ticket_detail["rule_results"] if ticket_detail else [])
        ],
        "llm_response": None
        if not ticket_detail or not ticket_detail["llm_response"]
        else {
            "provider": ticket_detail["llm_response"].provider,
            "deployment_name": ticket_detail["llm_response"].model,
            "prompt_hash": ticket_detail["llm_response"].prompt_hash,
            "run_id": ticket_detail["llm_response"].run_id,
            "response_json": ticket_detail["llm_response"].response_json,
        },
    }
