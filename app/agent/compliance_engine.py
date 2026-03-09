"""
ComplianceEngine â€“ orchestrates fetching, checking, persisting, and LLM analysis.
"""
from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from datetime import datetime, date
from typing import Any

from flask import current_app

from app.extensions import db
from app.models.models import AuditEvidence, Ticket, TicketRuleAssessment, Violation
from app.agent.checks import run_all_checks
from app.agent.comment_rule_evaluator import CommentRuleEvaluator
from app.agent.llm_client import LLMClient
from app.agent.prompts import SYSTEM_PROMPT, build_violation_analysis_prompt, build_batch_summary_prompt
from app.services.jira_service import JiraService
from app.services.snow_service import ServiceNowService
from app.services.notification_service import NotificationService

logger = logging.getLogger(__name__)

_LLM_WORKERS = 5  # concurrent LLM calls
_LLM_UNAVAILABLE_NOTICE = (
    "[LLM analysis unavailable - no API key configured. "
    "Add your API key on the Connections page to enable AI-powered narrative analysis.]"
)

# â”€â”€ Progress tracking (updated live, polled by frontend) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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


def _ticket_date(ticket: dict) -> date | None:
    dt = _ticket_sort_key(ticket)
    if dt == datetime.min:
        return None
    return dt.date()


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

    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    def run_analysis(
        self,
        use_llm: bool = True,
        from_date: str | None = None,
        full_scan: bool = False,
    ) -> dict[str, Any]:
        """Full pipeline â€“ fetch all tickets and analyse them."""
        if not _analysis_lock.acquire(blocking=False):
            raise RuntimeError("An analysis is already in progress. Please wait and try again.")
        _set(
            running=True, stage="Starting...",
            tickets_total=0, tickets_done=0,
            evidence_total=0, evidence_done=0,
            violations_created=0, recent_tickets=[], errors=[], result=None,
        )
        try:
            result = self._run_analysis(use_llm=use_llm, from_date=from_date, full_scan=full_scan)
            _set(running=False, stage="Done", result=result)
            return result
        except Exception as exc:
            _set(running=False, stage=f"Failed: {exc}")
            raise
        finally:
            _analysis_lock.release()

    def _run_analysis(
        self,
        use_llm: bool = True,
        from_date: str | None = None,
        full_scan: bool = False,
    ) -> dict[str, Any]:
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
        runtime_config["COMMENT_RULE_EVALUATOR"] = CommentRuleEvaluator(self.llm)
        runtime_config["TICKET_RULE_EVALUATOR"] = runtime_config["COMMENT_RULE_EVALUATOR"]

        # 1 â”€â”€ Fetch JIRA + ServiceNow tickets in parallel (both are HTTP I/O)
        _set(stage="Fetching tickets from JIRA & ServiceNow...")
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

        existing_scan_map: dict[str, Any] = {
            t.ticket_key: t.analyzed_at
            for t in Ticket.query.with_entities(Ticket.ticket_key, Ticket.analyzed_at).all()
        }

        parsed_from_date: date | None = None
        if from_date:
            try:
                parsed_from_date = date.fromisoformat(str(from_date).strip())
            except ValueError as exc:
                raise ValueError("Invalid from_date format. Use YYYY-MM-DD.") from exc

        if parsed_from_date:
            filtered_raw = [
                t for t in eligible_raw
                if (_ticket_date(t) is not None and _ticket_date(t) >= parsed_from_date)
            ]
            scan_mode = "from_date"
        elif full_scan:
            filtered_raw = eligible_raw
            scan_mode = "full_scan"
        else:
            # Default incremental mode: scan only tickets never analyzed before.
            filtered_raw = [
                t for t in eligible_raw
                if not existing_scan_map.get(str(t.get("ticket_key", "")).strip())
            ]
            scan_mode = "incremental"

        stats: dict[str, Any] = {
            "tickets_fetched":       len(all_raw),
            "tickets_eligible":      len(eligible_raw),
            "tickets_checked":       len(filtered_raw),
            "tickets_new":           sum(1 for t in filtered_raw if str(t.get("ticket_key", "")) not in existing_scan_map),
            "violations_created":    0,
            "violations_by_severity": {"High": 0, "Medium": 0, "Low": 0},
            "violations_by_type":    {},
            "llm_analyses":          0,
            "errors":                [],
            "scan_mode":             scan_mode,
            "from_date":             parsed_from_date.isoformat() if parsed_from_date else None,
        }

        _set(
            stage=f"Checking {len(filtered_raw)} closed/resolved tickets for violations...",
            tickets_total=len(filtered_raw),
            tickets_done=0,
        )

        all_violations: list[dict] = []
        for raw in filtered_raw:
            try:
                ticket_obj = self._upsert_ticket(raw)
                new_violations = self._check_and_persist(ticket_obj, raw, runtime_config)
                # â”€â”€ Commit after each ticket so the write lock is released immediately â”€â”€
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

        # 2 â”€â”€ LLM evidence generation (parallel HTTP calls, sequential DB writes)
        if use_llm:
            stats["llm_analyses"] = self._generate_evidence_parallel()

        # 3 â”€â”€ Notifications
        if all_violations:
            try:
                NotificationService(settings).notify(all_violations)
            except Exception as exc:
                logger.warning("Notification dispatch failed: %s", exc)

        # 4 â”€â”€ Executive summary
        _set(stage="Generating executive summary...")
        if all_violations:
            stats["executive_summary"] = self._batch_summary(all_violations)
        else:
            stats["executive_summary"] = "No violations detected in this analysis run."

        db.session.commit()
        return stats

    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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
        self, ticket_obj: Ticket, raw: dict, config: Any
    ) -> list[dict]:
        """Run checks and replace stored per-ticket outcomes with latest run."""
        # Re-scan semantics: replace stale violations and stale per-control assessments.
        for v in list(ticket_obj.violations):
            db.session.delete(v)
        for a in list(ticket_obj.rule_assessments):
            db.session.delete(a)
        db.session.flush()

        results = run_all_checks(raw, config)
        persisted: list[dict] = []

        assessment_payload = raw.get("_llm_rule_assessment") if isinstance(raw, dict) else None
        checks = assessment_payload.get("checks") if isinstance(assessment_payload, dict) else None
        if isinstance(checks, list):
            for entry in checks:
                if not isinstance(entry, dict):
                    continue
                ra = TicketRuleAssessment(
                    ticket_id=ticket_obj.id,
                    control_key=str(entry.get("control_key") or ""),
                    control_id=str(entry.get("control_id") or ""),
                    control_name=str(entry.get("control_name") or ""),
                    severity=str(entry.get("severity") or "Medium"),
                    applicable=bool(entry.get("applicable", True)),
                    passed=bool(entry.get("passed", False)),
                    reason=str(entry.get("reason") or "").strip() or None,
                    evidence={"items": entry.get("evidence") if isinstance(entry.get("evidence"), list) else []},
                    raw_result=entry,
                )
                db.session.add(ra)

        for r in results:
            v = Violation(
                ticket_id=ticket_obj.id,
                control_id=r.control_id,
                violation_type=r.violation_type,
                description=r.description,
                severity=r.severity,
            )
            db.session.add(v)
            db.session.flush()
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
          2. Fire LLM calls concurrently (_LLM_WORKERS at a time) â€” pure HTTP, no DB.
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
            stage=f"Generating AI evidence for {len(unevidenced)} violation(s)...",
            evidence_total=len(unevidenced),
            evidence_done=0,
        )

        # â”€â”€ Step 1: collect all data for LLM prompts (DB reads, main thread only)
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

        # â”€â”€ Step 2: fire all LLM calls in parallel (I/O-bound, no DB access)
        def _call_llm(job: dict) -> dict:
            analysis = self.llm.analyze(system=SYSTEM_PROMPT, user=job["prompt"])
            if not str(analysis or "").strip():
                analysis = _LLM_UNAVAILABLE_NOTICE
            with _progress_lock:
                _progress["evidence_done"] += 1
                _progress["stage"] = (
                    f"Generating AI evidence... "
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

        # â”€â”€ Step 3: write results to DB one at a time so a lock on one record
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

