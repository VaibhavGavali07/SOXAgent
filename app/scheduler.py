"""Background scheduler – runs compliance analysis automatically on a configurable interval."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)

_scheduler = BackgroundScheduler(daemon=True, timezone="UTC")
_last_run:  Optional[datetime] = None
_last_status: str = "never"


# ── Job ────────────────────────────────────────────────────────────────────────

def _compliance_job(app) -> None:
    """Runs in the scheduler thread – pushes its own Flask app context."""
    global _last_run, _last_status
    with app.app_context():
        from app.models.models import Setting
        settings = {r.key: r.value for r in Setting.query.all()}

        if settings.get("monitor_enabled", "false").lower() not in ("true", "1"):
            logger.debug("Scheduler: auto-monitoring is disabled – skipping run.")
            return

        logger.info("Scheduler: starting automatic compliance analysis…")
        from app.extensions import db
        try:
            from app.agent.compliance_engine import ComplianceEngine
            engine = ComplianceEngine()
            result  = engine.run_analysis(use_llm=True)
            db.session.commit()
            _last_run    = datetime.now(timezone.utc)
            _last_status = (
                f"{result.get('tickets_fetched', 0)} tickets · "
                f"{result.get('violations_created', 0)} new violation(s)"
            )
            logger.info("Scheduler: analysis done – %s", _last_status)
        except Exception as exc:
            _last_status = f"error: {exc}"
            logger.error("Scheduler: analysis failed – %s", exc)
            try:
                db.session.rollback()
            except Exception:
                pass
        finally:
            # Return the connection to the pool so it doesn't hold any locks
            db.session.remove()


# ── Public API ─────────────────────────────────────────────────────────────────

def init_scheduler(app) -> None:
    """Initialise and start the background scheduler (safe to call once at startup)."""
    with app.app_context():
        from app.models.models import Setting
        settings   = {r.key: r.value for r in Setting.query.all()}
        interval   = _safe_interval(settings.get("monitor_interval_minutes", "60"))

    if not _scheduler.running:
        _scheduler.start()

    _scheduler.add_job(
        func=_compliance_job,
        args=[app],
        trigger=IntervalTrigger(minutes=interval),
        id="compliance_auto",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    logger.info("Scheduler initialised – interval: %d min", interval)


def reconfigure(app, interval_minutes: int) -> None:
    """Update the job interval at runtime (called when settings are saved)."""
    interval = _safe_interval(interval_minutes)
    if not _scheduler.running:
        init_scheduler(app)
        return
    _scheduler.reschedule_job(
        "compliance_auto",
        trigger=IntervalTrigger(minutes=interval),
    )
    logger.info("Scheduler reconfigured – new interval: %d min", interval)


def get_status() -> dict:
    """Return a JSON-serialisable status snapshot for the API."""
    job = _scheduler.get_job("compliance_auto") if _scheduler.running else None
    next_run = None
    if job and job.next_run_time:
        next_run = job.next_run_time.isoformat()

    return {
        "running":      _scheduler.running,
        "next_run":     next_run,
        "last_run":     _last_run.isoformat() if _last_run else None,
        "last_status":  _last_status,
    }


# ── Helpers ────────────────────────────────────────────────────────────────────

def _safe_interval(value) -> int:
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return 60
