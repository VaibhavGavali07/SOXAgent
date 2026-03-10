from __future__ import annotations

from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.services.analyzer_service import rerun_ticket_job, run_analysis_job
from backend.storage import crud
from backend.storage.db import get_db


router = APIRouter(prefix="/api", tags=["fetch"])


class FetchRequest(BaseModel):
    filters: dict[str, Any] = Field(default_factory=dict)


@router.post("/fetch/servicenow")
def fetch_servicenow(request: FetchRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    run = crud.create_run(db, "servicenow", request.filters)
    background_tasks.add_task(run_analysis_job, run.run_id, "servicenow", request.filters)
    return {"run_id": run.run_id, "status": run.status}


@router.post("/analyze/ticket/{ticket_db_id}")
def analyze_ticket(ticket_db_id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    ticket = crud.get_ticket(db, ticket_db_id)
    source = ticket.source if ticket else "manual"
    run = crud.create_run(db, source, {"ticket_db_id": ticket_db_id})
    background_tasks.add_task(rerun_ticket_job, run.run_id, ticket_db_id)
    return {"run_id": run.run_id, "status": run.status}

