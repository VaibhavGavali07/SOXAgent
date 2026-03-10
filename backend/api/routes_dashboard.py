from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from backend.services.analyzer_service import run_state_store
from backend.storage import crud
from backend.storage.db import get_db


router = APIRouter(prefix="/api", tags=["dashboard"])


@router.get("/dashboard/summary")
def get_dashboard_summary(db: Session = Depends(get_db)):
    return crud.dashboard_summary(db)


@router.get("/runs/{run_id}/events")
async def stream_run_events(run_id: str):
    return StreamingResponse(run_state_store.stream(run_id), media_type="text/event-stream")

