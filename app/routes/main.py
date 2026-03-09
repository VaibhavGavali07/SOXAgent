"""Page routes – all rendered HTML views."""
from __future__ import annotations

from flask import Blueprint, render_template, current_app
from sqlalchemy import func
from sqlalchemy.orm import joinedload

from app.extensions import db
from app.models.models import AuditEvidence, Setting, Ticket, Violation

main_bp = Blueprint("main", __name__)


def _source_urls() -> dict[str, str]:
    """Return jira_url and snow_url from settings for building deep-links."""
    rows = Setting.query.filter(Setting.key.in_(["jira_url", "snow_url"])).all()
    m = {r.key: r.value for r in rows}
    return {"jira_url": m.get("jira_url", "").rstrip("/"),
            "snow_url": m.get("snow_url", "").rstrip("/")}


@main_bp.route("/")
def dashboard():
    return render_template("dashboard.html", **_source_urls())


@main_bp.route("/tickets")
def tickets():
    all_tickets = (
        Ticket.query
        .options(joinedload(Ticket.rule_assessments), joinedload(Ticket.violations))
        .order_by(Ticket.ticket_key.desc())
        .all()
    )

    enabled_row = Setting.query.filter_by(key="enabled_controls").first()
    enabled_keys = {item.strip() for item in (enabled_row.value if enabled_row else "").split(",") if item.strip()}
    controls_cfg = current_app.config.get("CONTROLS", {})
    enabled_controls: list[dict[str, str]] = []
    for key, value in controls_cfg.items():
        is_enabled = (key in enabled_keys) if enabled_keys else bool(value.get("enabled", True))
        if not is_enabled:
            continue
        enabled_controls.append({
            "id": value.get("id", key),
            "name": value.get("name", key.replace("_", " ").title()),
        })

    return render_template("tickets.html", tickets=all_tickets, enabled_controls=enabled_controls, **_source_urls())


@main_bp.route("/violations")
def violations():
    all_violations = (
        Violation.query
        .join(Ticket, Ticket.id == Violation.ticket_id)
        .order_by(Ticket.ticket_key.desc(), Violation.detected_at.desc())
        .all()
    )
    return render_template("violations.html", violations=all_violations, **_source_urls())


@main_bp.route("/evidence")
def evidence():
    all_evidence = (
        AuditEvidence.query
        .join(Violation)
        .order_by(AuditEvidence.generated_at.desc())
        .all()
    )
    return render_template("evidence.html", evidence=all_evidence)


@main_bp.route("/connections")
def connections():
    from app.models.models import Setting
    settings = {s.key: s.value for s in Setting.query.all()}
    return render_template("connections.html", settings=settings)


@main_bp.route("/validations")
def validations():
    from app.models.models import CustomRule
    rules = CustomRule.query.order_by(CustomRule.created_at.desc()).all()
    setting = Setting.query.filter_by(key="approved_software_list").first()
    enabled_row = Setting.query.filter_by(key="enabled_controls").first()
    enabled = {item.strip() for item in (enabled_row.value if enabled_row else "").split(",") if item.strip()}
    controls_cfg = current_app.config.get("CONTROLS", {})
    controls = []
    for key, value in controls_cfg.items():
        controls.append({"key": key, **value, "enabled": (key in enabled) if enabled else value.get("enabled", True)})
    approved_software = (
        setting.value
        if setting and setting.value
        else "\n".join(current_app.config.get("APPROVED_SOFTWARE", []))
    )
    return render_template("validations.html", rules=rules, approved_software=approved_software, controls=controls)
