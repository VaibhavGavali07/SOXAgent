from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.llm.rule_ids import canonical_rule_id
from backend.storage import crud
from backend.storage.db import get_db


router = APIRouter(prefix="/api", tags=["tickets"])


@router.get("/tickets")
def list_tickets(
    source: str | None = Query(default=None),
    status: str | None = Query(default=None),
    ticket_type: str | None = Query(default=None),
    q: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    return crud.list_ticket_summaries(db, source=source, q=q, status=status, ticket_type=ticket_type)


@router.get("/tickets/{ticket_db_id}")
def get_ticket(ticket_db_id: int, db: Session = Depends(get_db)):
    detail = crud.get_ticket_detail(db, ticket_db_id)
    if not detail:
        return {"error": "Ticket not found"}
    llm_response = detail["llm_response"]
    return {
        "ticket": {
            "id": detail["ticket"].id,
            "ticket_id": detail["ticket"].ticket_id,
            "source": detail["ticket"].source,
            "type": detail["ticket"].ticket_type,
            "status": detail["ticket"].status,
            "summary": detail["ticket"].summary,
            "canonical_json": detail["ticket"].canonical_json,
        },
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
                "control_mapping": result.control_mapping,
            }
            for result in detail["rule_results"]
        ],
        "llm_response": None
        if not llm_response
        else {
            "provider": llm_response.provider,
            "deployment_name": llm_response.model,
            "prompt_hash": llm_response.prompt_hash,
            "response_json": llm_response.response_json,
        },
    }
