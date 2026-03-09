"""
ComplianceEngine – orchestrates fetching, checking, persisting, and LLM analysis.
"""
from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from datetime import datetime
from typing import Any

from flask import current_app

from app.extensions import db
from app.models.models import AuditEvidence, CustomRule, Ticket, Violation
from app.agent.checks import run_all_checks, run_custom_rules
from app.agent.llm_client import LLMClient
from app.agent.prompts import SYSTEM_PROMPT, build_violation_analysis_prompt, build_batch_summary_prompt
from app.services.jira_service import JiraService
from app.services.snow_service import ServiceNowService
from app.services.notification_service import NotificationService

logger = logging.getLogger(__name__)

_LLM_WORKERS = 5  # concurrent LLM calls

# ── Progress tracking (updated live, polled by frontend) ─────────────────────
_progress_lock = threading.Lock()
_progress: dict = {
    "running":           False,
    "stage":             "idle",
    "tickets_total":     0,
    "tickets_done":      0,
    "evidence_total":    0,
    "evidence_done":     0,
    "violations_created": 0,
    "recent_tickets":    [],
    "errors":            [],
    "result":            None,
}

# Prevent concurrent analysis runs (scheduler + manual trigger can overlap)
_analysis_lock = threading.Lock()


def _set(**kwargs) -> None:
    with _progress_lock:
        _progress.update(kwargs)


def get_progress() -> dict:
    with _progress_lock:
        return dict(_progress)


def _get_settings() -> dict[str, str]:
    from app.models.models import Setting
    rows = Setting.query.all()
    return {r.key: r.value for r in rows}


def _parse_software_list(raw: str) -> list[str]:
    """Parse comma/newline-separated software list from settings."""
    if not raw:
        return []
    parts: list[str] = []
    for line in raw.replace("\r", "\n").split("\n"):
        for item in line.split(","):
            val = item.strip()
            if val:
                parts.append(val)
    # preserve order while de-duplicating
    return list(dict.fromkeys(parts))


def _parse_enabled_controls(raw: str) -> set[str]:
    if not raw:
        return set()
    return {item.strip() for item in str(raw).split(",") if item.strip()}


def _ticket_sort_key(ticket: dict) -> datetime:
    """Best-effort timestamp extraction for newest-first processing."""
    candidates = [
        ticket.get("updated_at"),
        ticket.get("closed_at"),
        ticket.get("created_at"),
        (ticket.get("_raw_snow") or {}).get("sys_updated_on"),
        (ticket.get("_raw_snow") or {}).get("closed_at"),
        (ticket.get("_raw_snow") or {}).get("sys_created_on"),
    ]
    for raw in candidates:
        if not raw:
            continue
        try:
            s = str(raw).strip().replace("Z", "+00:00")
            if " " in s and "T" not in s:
                s = s.replace(" ", "T")
            return datetime.fromisoformat(s)
        except Exception:
            continue
    return datetime.min


class ComplianceEngine:
    """
    Orchestrates the full ITGC compliance analysis pipeline:
      1. Fetch tickets from JIRA + ServiceNow  (parallel)
      2. Upsert into Ticket table
      3. Run all rule-based checks
      4. Persist Violation records  (commit per ticket)
      5. Call LLM for narrative audit evidence  (parallel)
      6. Persist AuditEvidence records
      7. Return analysis summary
    """

    def __init__(self):
        settings = _get_settings()
        self.llm = LLMClient.from_settings(settings)
        config = current_app.config

        self.jira = JiraService(
            url=settings.get("jira_url", ""),
            username=settings.get("jira_username", ""),
            api_token=settings.get("jira_api_token", ""),
        )
        self.snow = ServiceNowService(
            url=settings.get("snow_url", ""),
            client_id=settings.get("snow_client_id", ""),
            client_secret=settings.get("snow_client_secret", ""),
            client_name=settings.get("snow_client_name", ""),
        )

    # ─────────────────────────────────────────────────────────────────────────
    def run_analysis(self, use_llm: bool = True) -> dict[str, Any]:
        """Full pipeline – fetch all tickets and analyse them."""
        if not _analysis_lock.acquire(blocking=False):
            raise RuntimeError("An analysis is already in progress. Please wait and try again.")
        _set(
            running=True, stage="Starting…",
            tickets_total=0, tickets_done=0,
            evidence_total=0, evidence_done=0,
            violations_created=0, recent_tickets=[], errors=[], result=None,
        )
        try:
            result = self._run_analysis(use_llm)
            _set(running=False, stage="Done", result=result)
            return result
        except Exception as exc:
            _set(running=False, stage=f"Failed: {exc}")
            raise
        finally:
            _analysis_lock.release()

    def _run_analysis(self, use_llm: bool = True) -> dict[str, Any]:
        settings = _get_settings()
        config = current_app.config
        runtime_config = dict(config)
        runtime_controls = deepcopy(config.get("CONTROLS", {}))

        enabled_controls = _parse_enabled_controls(settings.get("enabled_controls", ""))
        if enabled_controls:
            for key, value in runtime_controls.items():
                value["enabled"] = key in enabled_controls
        runtime_config["CONTROLS"] = runtime_controls

        approved_software = _parse_software_list(settings.get("approved_software_list", ""))
        if approved_software:
            runtime_config["APPROVED_SOFTWARE"] = approved_software

        # 1 ── Fetch JIRA + ServiceNow tickets in parallel (both are HTTP I/O)
        _set(stage="Fetching tickets from JIRA & ServiceNow…")
        with ThreadPoolExecutor(max_workers=2) as pool:
            jira_future = pool.submit(self.jira.get_tickets)
            snow_future = pool.submit(self.snow.get_tickets)
            jira_tickets = jira_future.result()
            snow_tickets = snow_future.result()

        all_raw = [
            *[{**t, "source": "JIRA"} for t in jira_tickets],
            *[{**t, "source": "ServiceNow"} for t in snow_tickets],
        ]
        all_raw.sort(key=_ticket_sort_key, reverse=True)
        eligible_raw = [t for t in all_raw if str(t.get("status", "")).strip().lower() in ("closed", "resolved")]

        stats: dict[str, Any] = {
            "tickets_fetched":       len(all_raw),
            "tickets_checked":       len(eligible_raw),
            "tickets_new":           0,
            "violations_created":    0,
            "violations_by_severity": {"High": 0, "Medium": 0, "Low": 0},
            "violations_by_type":    {},
            "llm_analyses":          0,
            "errors":                [],
        }

        _set(
            stage=f"Checking {len(eligible_raw)} closed/resolved tickets for violations…",
            tickets_total=len(eligible_raw),
            tickets_done=0,
        )

        all_violations: list[dict] = []
        custom_rules = CustomRule.query.filter_by(enabled=True).all()

        for raw in eligible_raw:
            try:
                ticket_obj = self._upsert_ticket(raw)
                new_violations = self._check_and_persist(ticket_obj, raw, runtime_config, custom_rules)
                # ── Commit after each ticket so the write lock is released immediately ──
                db.session.commit()
                all_violations.extend(new_violations)
                stats["violations_created"] += len(new_violations)
                for v in new_violations:
                    sev = v["severity"]
                    stats["violations_by_severity"][sev] = stats["violations_by_severity"].get(sev, 0) + 1
                    vt = v["violation_type"]
                    stats["violations_by_type"][vt] = stats["violations_by_type"].get(vt, 0) + 1
            except Exception as exc:
                logger.error("Error processing ticket %s: %s", raw.get("ticket_key"), exc)
                stats["errors"].append(str(exc))
                try:
                    db.session.rollback()
                except Exception:
                    pass
            finally:
                with _progress_lock:
                    _progress["tickets_done"] += 1
                    _progress["violations_created"] = stats["violations_created"]
                    recent = list(_progress.get("recent_tickets") or [])
                    recent.insert(
                        0,
                        {
                            "ticket_key": raw.get("ticket_key"),
                            "title": raw.get("title", ""),
                            "source": raw.get("source", ""),
                            "status": raw.get("status", ""),
                        },
                    )
                    _progress["recent_tickets"] = recent[:30]

        # 2 ── LLM evidence generation (parallel HTTP calls, sequential DB writes)
        if use_llm and self.llm.is_available():
            stats["llm_analyses"] = self._generate_evidence_parallel()

        # 3 ── Notifications
        if all_violations:
            try:
                NotificationService(settings).notify(all_violations)
            except Exception as exc:
                logger.warning("Notification dispatch failed: %s", exc)

        # 4 ── Executive summary
        _set(stage="Generating executive summary…")
        if all_violations:
            stats["executive_summary"] = self._batch_summary(all_violations)
        else:
            stats["executive_summary"] = "No violations detected in this analysis run."

        db.session.commit()
        return stats

    # ─────────────────────────────────────────────────────────────────────────
    def _upsert_ticket(self, raw: dict) -> Ticket:
        existing = Ticket.query.filter_by(ticket_key=raw["ticket_key"]).first()
        if existing:
            existing.status = raw.get("status", existing.status)
            existing.title = raw.get("title", existing.title)
            existing.approver_id = raw.get("approver_id")
            existing.requestor_id = raw.get("requestor_id")
            existing.implementer_id = raw.get("implementer_id")
            existing.documentation_link = raw.get("documentation_link")
            existing.raw_data = raw
            return existing

        ticket = Ticket(
            source=raw["source"],
            ticket_key=raw["ticket_key"],
            title=raw.get("title", ""),
            status=raw.get("status", ""),
            requestor_id=raw.get("requestor_id"),
            approver_id=raw.get("approver_id"),
            implementer_id=raw.get("implementer_id"),
            documentation_link=raw.get("documentation_link"),
            ticket_type=raw.get("ticket_type"),
            priority=raw.get("priority"),
            raw_data=raw,
        )
        db.session.add(ticket)
        db.session.flush()
        return ticket

    def _check_and_persist(
        self, ticket_obj: Ticket, raw: dict, config: Any, custom_rules: list = ()
    ) -> list[dict]:
        """Run all checks; skip violation types already recorded for this ticket."""
        existing_types = {v.violation_type for v in ticket_obj.violations}
        results = run_all_checks(raw, config)
        results.extend(run_custom_rules(raw, custom_rules))
        persisted: list[dict] = []

        for r in results:
            if r.violation_type in existing_types:
                continue
            v = Violation(
                ticket_id=ticket_obj.id,
                control_id=r.control_id,
                violation_type=r.violation_type,
                description=r.description,
                severity=r.severity,
            )
            db.session.add(v)
            db.session.flush()
            existing_types.add(r.violation_type)
            persisted.append({
                **v.to_dict(),
                "ticket_key":   ticket_obj.ticket_key,
                "ticket_title": ticket_obj.title,
            })

        ticket_obj.analyzed_at = datetime.utcnow()
        db.session.flush()
        return persisted

    def _generate_evidence_parallel(self) -> int:
        """
        Generate evidence for all violations that have none yet.

        Strategy:
          1. Read all needed data from DB in the main thread.
          2. Fire LLM calls concurrently (_LLM_WORKERS at a time) — pure HTTP, no DB.
          3. Write all results to DB sequentially in the main thread.

        Returns the number of evidence records created.
        """
        unevidenced = (
            db.session.query(Violation)
            .outerjoin(AuditEvidence, AuditEvidence.violation_id == Violation.id)
            .filter(AuditEvidence.id.is_(None))
            .all()
        )
        if not unevidenced:
            return 0

        _set(
            stage=f"Generating AI evidence for {len(unevidenced)} violation(s)…",
            evidence_total=len(unevidenced),
            evidence_done=0,
        )

        # ── Step 1: collect all data for LLM prompts (DB reads, main thread only)
        jobs: list[dict] = []
        for v_obj in unevidenced:
            ticket_obj = Ticket.query.get(v_obj.ticket_id)
            v_dict = v_obj.to_dict()
            ticket_dict = ticket_obj.to_dict() if ticket_obj else {}
            ticket_raw = (ticket_obj.raw_data or {}) if ticket_obj else {}
            jobs.append({
                "violation_id": v_obj.id,
                "v_dict":       v_dict,
                "ticket_dict":  ticket_dict,
                "prompt":       build_violation_analysis_prompt(v_dict, ticket_raw),
            })

        # ── Step 2: fire all LLM calls in parallel (I/O-bound, no DB access)
        def _call_llm(job: dict) -> dict:
            analysis = self.llm.analyze(system=SYSTEM_PROMPT, user=job["prompt"])
            with _progress_lock:
                _progress["evidence_done"] += 1
                _progress["stage"] = (
                    f"Generating AI evidence… "
                    f"{_progress['evidence_done']}/{_progress['evidence_total']}"
                )
            return {**job, "analysis": analysis}

        results: list[dict] = []
        with ThreadPoolExecutor(max_workers=_LLM_WORKERS) as pool:
            futures = {pool.submit(_call_llm, job): job for job in jobs}
            for future in as_completed(futures):
                try:
                    results.append(future.result())
                except Exception as exc:
                    logger.warning("LLM evidence call failed: %s", exc)

        # ── Step 3: write results to DB one at a time so a lock on one record
        #           doesn't discard the entire batch.
        count = 0
        for res in results:
            try:
                evidence = AuditEvidence(
                    violation_id=res["violation_id"],
                    report_data={
                        "violation":    res["v_dict"],
                        "ticket":       res["ticket_dict"],
                        "generated_at": datetime.utcnow().isoformat(),
                    },
                    llm_analysis=res["analysis"],
                )
                db.session.add(evidence)
                db.session.commit()
                count += 1
            except Exception as exc:
                logger.warning("Failed to save evidence for violation %s: %s",
                               res.get("violation_id"), exc)
                try:
                    db.session.rollback()
                except Exception:
                    pass

        logger.info("Evidence generated for %d violation(s)", count)
        return count

    def _batch_summary(self, violations: list[dict]) -> str:
        if not self.llm.is_available():
            high = sum(1 for v in violations if v["severity"] == "High")
            return (
                f"Analysis complete: {len(violations)} violation(s) detected "
                f"({high} High severity). Configure an LLM API key for AI-generated narratives."
            )
        prompt = build_batch_summary_prompt(violations)
        return self.llm.analyze(system=SYSTEM_PROMPT, user=prompt, max_tokens=400)
