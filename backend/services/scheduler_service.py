from __future__ import annotations

import logging
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)

_scheduler = BackgroundScheduler(timezone="UTC")
_scheduler.start()

JOB_ID = "scheduled_fetch"


def _run_scheduled_fetch(mode: str = "append") -> None:
    """Runs inside APScheduler's background thread — creates its own DB session."""
    from backend.services.analyzer_service import run_analysis_job
    from backend.storage import crud
    from backend.storage.db import SessionLocal

    logger.info("Scheduled fetch triggered (mode=%s)", mode)
    db = SessionLocal()
    try:
        run = crud.create_run(db, "servicenow", {"scheduled": True, "mode": mode})
        run_id = run.run_id
    finally:
        db.close()

    run_analysis_job(run_id, "servicenow", {})


def apply_schedule(config: dict[str, Any]) -> None:
    """Remove any existing job and re-schedule based on config."""
    if _scheduler.get_job(JOB_ID):
        _scheduler.remove_job(JOB_ID)

    if not config.get("enabled"):
        logger.info("Scheduled fetch disabled")
        return

    mode = config.get("mode", "append")
    interval_type = config.get("interval_type", "minutes")
    interval_value = int(config.get("interval_value", 60))
    daily_time: str = config.get("daily_time", "09:00")

    if interval_type == "daily":
        hour, minute = daily_time.split(":")
        trigger = CronTrigger(hour=int(hour), minute=int(minute), timezone="UTC")
        desc = f"daily at {daily_time} UTC"
    else:
        # "minutes" or "hours" — normalise to minutes
        minutes = interval_value if interval_type == "minutes" else interval_value * 60
        trigger = IntervalTrigger(minutes=minutes)
        desc = f"every {minutes} minute(s)"

    _scheduler.add_job(_run_scheduled_fetch, trigger, id=JOB_ID, args=[mode], replace_existing=True)
    logger.info("Scheduled fetch configured: %s (mode=%s)", desc, mode)


def get_next_run_time() -> str | None:
    job = _scheduler.get_job(JOB_ID)
    if job and job.next_run_time:
        return job.next_run_time.isoformat()
    return None


def load_schedule_from_db() -> None:
    """Called at startup — reads saved schedule config from DB and applies it."""
    from backend.storage import crud
    from backend.storage.db import SessionLocal

    db = SessionLocal()
    try:
        for cfg in crud.list_configs(db):
            if cfg.config_type == "schedule":
                apply_schedule(dict(cfg.data))
                return
    finally:
        db.close()


def shutdown() -> None:
    if _scheduler.running:
        _scheduler.shutdown(wait=False)
