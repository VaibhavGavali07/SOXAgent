"""Page routes – all rendered HTML views."""
from __future__ import annotations

from flask import Blueprint, render_template
from sqlalchemy import func

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
    all_tickets = Ticket.query.order_by(Ticket.created_at.desc()).all()
    return render_template("tickets.html", tickets=all_tickets, **_source_urls())


@main_bp.route("/violations")
def violations():
    all_violations = Violation.query.order_by(Violation.detected_at.desc()).all()
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
    return render_template("validations.html", rules=rules)
