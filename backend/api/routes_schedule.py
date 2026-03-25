from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.services import scheduler_service
from backend.storage import crud
from backend.storage.db import get_db

router = APIRouter(prefix="/api", tags=["schedule"])


class ScheduleConfig(BaseModel):
    enabled: bool = False
    interval_type: str = "minutes"   # "minutes" | "hours" | "daily"
    interval_value: int = 60          # value for minutes/hours
    daily_time: str = "09:00"         # HH:MM — used when interval_type == "daily"
    mode: str = "append"              # "append" | "clean"


@router.get("/schedule")
def get_schedule(db: Session = Depends(get_db)):
    for cfg in crud.list_configs(db):
        if cfg.config_type == "schedule":
            data = dict(cfg.data)
            return {**data, "next_run_time": scheduler_service.get_next_run_time()}
    return {
        "enabled": False,
        "interval_type": "minutes",
        "interval_value": 60,
        "daily_time": "09:00",
        "mode": "append",
        "next_run_time": None,
    }


@router.post("/schedule")
def save_schedule(payload: ScheduleConfig, db: Session = Depends(get_db)):
    data = payload.model_dump()
    crud.upsert_config(db, "schedule", "schedule-default", data)
    scheduler_service.apply_schedule(data)
    return {**data, "next_run_time": scheduler_service.get_next_run_time()}


@router.delete("/schedule")
def disable_schedule(db: Session = Depends(get_db)):
    data = {"enabled": False, "interval_type": "minutes", "interval_value": 60, "daily_time": "09:00", "mode": "append"}
    crud.upsert_config(db, "schedule", "schedule-default", data)
    scheduler_service.apply_schedule(data)
    return {"enabled": False, "next_run_time": None}
