from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import and_, desc, func, select
from sqlalchemy.orm import Session

from backend.storage.models import (
    AlertRecord,
    AuditReportRecord,
    ConfigRecord,
    EmbeddingRecord,
    LLMResponseRecord,
    LLMRunRecord,
    NotificationRecord,
    RawRecord,
    RuleResultRecord,
    TicketRecord,
)
from backend.llm.rule_ids import canonical_rule_id

_SECRET_TERMS = ("key", "secret", "token", "password")


def _is_secret_field(field_name: str) -> bool:
    lowered = field_name.lower()
    return any(term in lowered for term in _SECRET_TERMS)


def upsert_config(db: Session, config_type: str, name: str, data: dict[str, Any]) -> ConfigRecord:
    record = db.scalar(
        select(ConfigRecord).where(
            ConfigRecord.config_type == config_type,
            ConfigRecord.name == name,
        )
    )
    if record:
        merged = dict(record.data or {})
        for key, value in data.items():
            if _is_secret_field(key) and isinstance(value, str) and not value.strip():
                continue
            if _is_secret_field(key) and value is None:
                continue
            merged[key] = value
        record.data = merged
    else:
        record = ConfigRecord(config_type=config_type, name=name, data=data)
        db.add(record)
    db.commit()
    db.refresh(record)
    return record


def list_configs(db: Session) -> list[ConfigRecord]:
    return list(db.scalars(select(ConfigRecord).order_by(ConfigRecord.config_type, ConfigRecord.name)))


def create_run(db: Session, source: str, metadata: dict[str, Any]) -> LLMRunRecord:
    run = LLMRunRecord(source=source, metadata_json=metadata, status="queued")
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def update_run(
    db: Session,
    run_id: str,
    *,
    status: str | None = None,
    total_items: int | None = None,
    processed_items: int | None = None,
    metadata: dict[str, Any] | None = None,
    started: bool = False,
    finished: bool = False,
) -> LLMRunRecord | None:
    run = db.scalar(select(LLMRunRecord).where(LLMRunRecord.run_id == run_id))
    if not run:
        return None
    if status is not None:
        run.status = status
    if total_items is not None:
        run.total_items = total_items
    if processed_items is not None:
        run.processed_items = processed_items
    if metadata is not None:
        run.metadata_json = metadata
    now = datetime.utcnow()
    if started and not run.started_at:
        run.started_at = now
    if finished:
        run.finished_at = now
    db.commit()
    db.refresh(run)
    return run


def create_raw_record(db: Session, source: str, record_type: str, external_id: str, payload: dict[str, Any]) -> RawRecord:
    record = RawRecord(source=source, record_type=record_type, external_id=external_id, payload=payload)
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def create_ticket(db: Session, canonical_ticket: dict[str, Any]) -> TicketRecord:
    requestor = canonical_ticket.get("requestor") or {}
    record = TicketRecord(
        source=canonical_ticket["source"],
        ticket_id=canonical_ticket["ticket_id"],
        ticket_type=canonical_ticket["type"],
        status=canonical_ticket["status"],
        summary=canonical_ticket["summary"],
        requestor_name=requestor.get("name"),
        requestor_email=requestor.get("email"),
        severity_hint=canonical_ticket.get("custom_fields", {}).get("risk_hint"),
        canonical_json=canonical_ticket,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def get_existing_ticket_ids(db: Session, source: str, ticket_ids: list[str]) -> set[str]:
    if not ticket_ids:
        return set()
    rows = db.scalars(
        select(TicketRecord.ticket_id).where(
            and_(
                TicketRecord.source == source,
                TicketRecord.ticket_id.in_(ticket_ids),
            )
        )
    )
    return set(rows)


def get_ticket(db: Session, ticket_db_id: int) -> TicketRecord | None:
    return db.get(TicketRecord, ticket_db_id)


def list_tickets(
    db: Session,
    *,
    source: str | None = None,
    q: str | None = None,
    status: str | None = None,
    ticket_type: str | None = None,
) -> list[TicketRecord]:
    stmt = select(TicketRecord).order_by(desc(TicketRecord.created_at))
    if source:
        stmt = stmt.where(TicketRecord.source == source)
    if status:
        stmt = stmt.where(TicketRecord.status == status)
    if ticket_type:
        stmt = stmt.where(TicketRecord.ticket_type == ticket_type)
    if q:
        stmt = stmt.where(
            (TicketRecord.ticket_id.contains(q)) | (TicketRecord.summary.contains(q))
        )
    return list(db.scalars(stmt))


def list_ticket_summaries(
    db: Session,
    *,
    source: str | None = None,
    q: str | None = None,
    status: str | None = None,
    ticket_type: str | None = None,
) -> list[dict[str, Any]]:
    tickets = list_tickets(db, source=source, q=q, status=status, ticket_type=ticket_type)
    items: list[dict[str, Any]] = []
    for ticket in tickets:
        latest = db.scalar(
            select(LLMResponseRecord)
            .where(LLMResponseRecord.ticket_db_id == ticket.id)
            .order_by(desc(LLMResponseRecord.created_at))
        )
        passed = 0
        failed = 0
        review = 0
        analyzed_at: str | None = None
        priority = ticket.severity_hint or "LOW"
        if latest:
            analyzed_at = latest.created_at.isoformat()
            results = list(
                db.scalars(
                    select(RuleResultRecord).where(
                        and_(
                            RuleResultRecord.ticket_db_id == ticket.id,
                            RuleResultRecord.run_id == latest.run_id,
                        )
                    )
                )
            )
            for result in results:
                if result.status == "PASS":
                    passed += 1
                elif result.status == "FAIL":
                    failed += 1
                    if result.severity == "HIGH":
                        priority = "HIGH"
                    elif result.severity == "MEDIUM" and priority != "HIGH":
                        priority = "MEDIUM"
                elif result.status == "NEEDS_REVIEW":
                    review += 1

        custom = ticket.canonical_json.get("custom_fields", {}) if ticket.canonical_json else {}
        items.append(
            {
                "id": ticket.id,
                "ticket_id": ticket.ticket_id,
                "source": ticket.source,
                "type": ticket.ticket_type,
                "status": ticket.status,
                "summary": ticket.summary,
                "priority": priority,
                "passed": passed,
                "failed": failed,
                "violations": failed,
                "needs_review": review,
                "analyzed_at": analyzed_at,
                "created_at": ticket.created_at.isoformat(),
                "servicenow_url": custom.get("servicenow_url") or "",
            }
        )
    return items


def save_embedding(db: Session, entity_type: str, entity_id: str, vector: list[float], text_preview: str) -> EmbeddingRecord:
    record = EmbeddingRecord(entity_type=entity_type, entity_id=entity_id, vector_json=vector, text_preview=text_preview[:500])
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def list_embeddings(db: Session, entity_type: str) -> list[EmbeddingRecord]:
    return list(db.scalars(select(EmbeddingRecord).where(EmbeddingRecord.entity_type == entity_type)))


def create_llm_response(
    db: Session,
    *,
    run_id: str,
    ticket_id: str,
    ticket_db_id: int,
    provider: str,
    model: str,
    prompt_hash: str,
    prompt_text: str,
    response_json: dict[str, Any],
    overall_assessment: str,
) -> LLMResponseRecord:
    record = LLMResponseRecord(
        run_id=run_id,
        ticket_id=ticket_id,
        ticket_db_id=ticket_db_id,
        provider=provider,
        model=model,
        prompt_hash=prompt_hash,
        prompt_text=prompt_text,
        response_json=response_json,
        overall_assessment=overall_assessment,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def replace_rule_results(
    db: Session,
    *,
    run_id: str,
    ticket_db_id: int,
    ticket_id: str,
    source: str,
    results: list[dict[str, Any]],
) -> list[RuleResultRecord]:
    existing = list(
        db.scalars(
            select(RuleResultRecord).where(
                and_(
                    RuleResultRecord.ticket_db_id == ticket_db_id,
                    RuleResultRecord.run_id == run_id,
                )
            )
        )
    )
    for item in existing:
        db.delete(item)
    db.commit()

    rows: list[RuleResultRecord] = []
    for result in results:
        row = RuleResultRecord(
            run_id=run_id,
            ticket_db_id=ticket_db_id,
            ticket_id=ticket_id,
            source=source,
            rule_id=result["rule_id"],
            rule_name=result["rule_name"],
            severity=result["severity"],
            status=result["status"],
            confidence=result["confidence"],
            why=result["why"],
            evidence_json=result["evidence"],
            recommended_action=result["recommended_action"],
            control_mapping=result["control_mapping"],
        )
        db.add(row)
        rows.append(row)
    db.commit()
    for row in rows:
        db.refresh(row)
    return rows


def create_alerts_for_failures(
    db: Session,
    *,
    run_id: str,
    ticket_db_id: int,
    ticket_id: str,
    source: str,
    results: list[dict[str, Any]],
) -> list[AlertRecord]:
    alerts: list[AlertRecord] = []
    for result in results:
        if result["status"] != "FAIL":
            continue
        row = AlertRecord(
            run_id=run_id,
            ticket_db_id=ticket_db_id,
            ticket_id=ticket_id,
            source=source,
            rule_id=result["rule_id"],
            severity=result["severity"],
            status=result["status"],
            title=f'{result["rule_id"]} {result["rule_name"]}',
            detail=result["why"],
            evidence_json=result["evidence"],
        )
        db.add(row)
        alerts.append(row)
    db.commit()
    for row in alerts:
        db.refresh(row)
    return alerts


def create_audit_report(db: Session, run_id: str, source: str, summary_json: dict[str, Any]) -> AuditReportRecord:
    existing = db.scalar(select(AuditReportRecord).where(AuditReportRecord.run_id == run_id))
    if existing:
        existing.summary_json = summary_json
        db.commit()
        db.refresh(existing)
        return existing
    record = AuditReportRecord(run_id=run_id, source=source, summary_json=summary_json)
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def create_notification(db: Session, run_id: str, channel: str, severity: str, payload: dict[str, Any], status: str) -> NotificationRecord:
    record = NotificationRecord(run_id=run_id, channel=channel, severity=severity, payload=payload, status=status)
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def get_ticket_detail(db: Session, ticket_db_id: int) -> dict[str, Any] | None:
    ticket = db.get(TicketRecord, ticket_db_id)
    if not ticket:
        return None
    llm_response = db.scalar(
        select(LLMResponseRecord)
        .where(LLMResponseRecord.ticket_db_id == ticket_db_id)
        .order_by(desc(LLMResponseRecord.created_at))
    )
    results = []
    if llm_response:
        results = list(
            db.scalars(
                select(RuleResultRecord)
                .where(
                    and_(
                        RuleResultRecord.ticket_db_id == ticket_db_id,
                        RuleResultRecord.run_id == llm_response.run_id,
                    )
                )
                .order_by(RuleResultRecord.rule_id)
            )
        )
    return {
        "ticket": ticket,
        "rule_results": results,
        "llm_response": llm_response,
    }


def list_alerts(
    db: Session,
    *,
    severity: str | None = None,
    rule_id: str | None = None,
    source: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[AlertRecord]:
    stmt = select(AlertRecord).order_by(desc(AlertRecord.created_at))
    if severity:
        stmt = stmt.where(AlertRecord.severity == severity)
    if rule_id:
        stmt = stmt.where(AlertRecord.rule_id == rule_id)
    if source:
        stmt = stmt.where(AlertRecord.source == source)
    if date_from:
        stmt = stmt.where(AlertRecord.created_at >= datetime.fromisoformat(date_from))
    if date_to:
        stmt = stmt.where(AlertRecord.created_at <= datetime.fromisoformat(date_to))
    return list(db.scalars(stmt))


def get_alert(db: Session, alert_id: int) -> AlertRecord | None:
    return db.get(AlertRecord, alert_id)


def acknowledge_alert(db: Session, alert_id: int) -> AlertRecord | None:
    alert = db.get(AlertRecord, alert_id)
    if not alert:
        return None
    if not alert.acknowledged_at:
        alert.acknowledged_at = datetime.utcnow()
        db.commit()
        db.refresh(alert)
    return alert


def resolve_alert(db: Session, alert_id: int) -> AlertRecord | None:
    alert = db.get(AlertRecord, alert_id)
    if not alert:
        return None
    now = datetime.utcnow()
    if not alert.acknowledged_at:
        alert.acknowledged_at = now
    if not alert.resolved_at:
        alert.resolved_at = now
        db.commit()
        db.refresh(alert)
    return alert


def dashboard_summary(db: Session) -> dict[str, Any]:
    ticket_summaries = list_ticket_summaries(db)
    tickets_analyzed = len(ticket_summaries)
    violations_detected = db.scalar(select(func.count()).select_from(AlertRecord)) or 0
    high_risk = sum(1 for item in ticket_summaries if item["failed"] > 0 and item["priority"] == "HIGH")
    medium_risk = sum(1 for item in ticket_summaries if item["failed"] > 0 and item["priority"] == "MEDIUM")
    sod_conflicts = db.scalar(
        select(func.count()).select_from(AlertRecord).where(
            AlertRecord.rule_id.in_(["ITGC-SOD-01", "R004"])
        )
    ) or 0
    unauthorized_installs = db.scalar(
        select(func.count()).select_from(AlertRecord).where(
            AlertRecord.rule_id.in_(["ITGC-CM-01", "R005"])
        )
    ) or 0
    passed_checks = db.scalar(
        select(func.count()).select_from(RuleResultRecord).where(RuleResultRecord.status == "PASS")
    ) or 0
    failed_checks = db.scalar(
        select(func.count()).select_from(RuleResultRecord).where(RuleResultRecord.status == "FAIL")
    ) or 0
    review_checks = db.scalar(
        select(func.count()).select_from(RuleResultRecord).where(RuleResultRecord.status == "NEEDS_REVIEW")
    ) or 0
    total_checks = passed_checks + failed_checks + review_checks
    recent_alerts = list_alerts(db)[:5]

    severity_breakdown = [
        {"name": "HIGH", "value": high_risk},
        {"name": "MEDIUM", "value": medium_risk},
        {"name": "LOW", "value": 0},
    ]
    control_rows = db.execute(
        select(RuleResultRecord.rule_id, func.count())
        .where(RuleResultRecord.status == "FAIL")
        .group_by(RuleResultRecord.rule_id)
        .order_by(RuleResultRecord.rule_id)
    ).all()
    folded: dict[str, int] = {}
    for rule_id, count in control_rows:
        key = canonical_rule_id(rule_id)
        folded[key] = folded.get(key, 0) + count
    control_breakdown = [{"rule_id": rule_id, "count": count} for rule_id, count in sorted(folded.items())]

    today = datetime.utcnow().date()
    trend: list[dict[str, Any]] = []
    for day_offset in range(6, -1, -1):
        day = today - timedelta(days=day_offset)
        next_day = day + timedelta(days=1)
        count = db.scalar(
            select(func.count()).select_from(AlertRecord).where(
                and_(AlertRecord.created_at >= day, AlertRecord.created_at < next_day)
            )
        ) or 0
        trend.append({"date": day.isoformat(), "violations": count})

    resolved_count = db.scalar(
        select(func.count()).select_from(AlertRecord).where(AlertRecord.resolved_at.isnot(None))
    ) or 0
    acked_count = db.scalar(
        select(func.count()).select_from(AlertRecord).where(
            and_(AlertRecord.acknowledged_at.isnot(None), AlertRecord.resolved_at.is_(None))
        )
    ) or 0
    open_violations = violations_detected - resolved_count - acked_count

    if violations_detected > 0:
        audit_readiness = round((resolved_count * 1.0 + acked_count * 0.5) / violations_detected * 100)
    else:
        audit_readiness = 100 if total_checks > 0 else 100

    run = db.scalar(select(LLMRunRecord).order_by(desc(LLMRunRecord.created_at)))
    return {
        "stats": {
            "tickets_analyzed": tickets_analyzed,
            "violations_detected": violations_detected,
            "high_risk_violations": high_risk,
            "medium_risk_violations": medium_risk,
            "sod_conflicts": sod_conflicts,
            "unauthorized_software_installs": unauthorized_installs,
            "passed_checks": passed_checks,
            "failed_checks": failed_checks,
            "needs_review_checks": review_checks,
            "total_checks": total_checks,
            "resolved_violations": resolved_count,
            "acknowledged_violations": acked_count,
            "open_violations": open_violations,
            "audit_readiness": audit_readiness,
        },
        "severity_breakdown": severity_breakdown,
        "control_breakdown": control_breakdown,
        "trend": trend,
        "recent_alerts": [
            {
                "id": alert.id,
                "ticket_id": alert.ticket_id,
                "rule_id": alert.rule_id,
                "severity": alert.severity,
                "title": alert.title,
                "created_at": alert.created_at.isoformat(),
                "acknowledged_at": alert.acknowledged_at.isoformat() if alert.acknowledged_at else None,
                "resolved_at": alert.resolved_at.isoformat() if alert.resolved_at else None,
            }
            for alert in recent_alerts
        ],
        "latest_run": None
        if not run
        else {
            "run_id": run.run_id,
            "status": run.status,
            "processed_items": run.processed_items,
            "total_items": run.total_items,
            "source": run.source,
        },
    }


def summarize_run(db: Session, run_id: str) -> dict[str, Any]:
    results = list(db.scalars(select(RuleResultRecord).where(RuleResultRecord.run_id == run_id)))
    counts = Counter(result.status for result in results)
    return {
        "run_id": run_id,
        "result_counts": counts,
        "tickets": len({result.ticket_id for result in results}),
    }


def clear_compliance_data(db: Session, *, include_configs: bool = False) -> dict[str, int]:
    delete_order = [
        NotificationRecord,
        AuditReportRecord,
        AlertRecord,
        RuleResultRecord,
        LLMResponseRecord,
        LLMRunRecord,
        EmbeddingRecord,
        TicketRecord,
        RawRecord,
    ]
    counts: dict[str, int] = {}
    for model in delete_order:
        deleted = db.query(model).delete(synchronize_session=False)
        counts[model.__tablename__] = deleted

    if include_configs:
        deleted = db.query(ConfigRecord).delete(synchronize_session=False)
        counts[ConfigRecord.__tablename__] = deleted

    db.commit()
    return counts
