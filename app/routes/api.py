"""REST API routes – JSON responses consumed by the frontend."""
from __future__ import annotations

import json
import io
import threading
from datetime import datetime
import re

from flask import Blueprint, current_app, jsonify, request, send_file, abort
from sqlalchemy import func

from app.extensions import db
from app.models.models import AuditEvidence, CustomRule, Setting, Ticket, Violation

api_bp = Blueprint("api", __name__)


def _get_effective_controls() -> dict[str, dict]:
    controls = json.loads(json.dumps(current_app.config.get("CONTROLS", {})))
    enabled_row = Setting.query.filter_by(key="enabled_controls").first()
    if not enabled_row or not enabled_row.value:
        return controls
    enabled = {item.strip() for item in enabled_row.value.split(",") if item.strip()}
    for key, value in controls.items():
        value["enabled"] = key in enabled
    return controls


# ── Dashboard Stats ──────────────────────────────────────────────────────────

@api_bp.route("/stats")
def stats():
    total_tickets    = Ticket.query.count()
    total_violations = Violation.query.count()
    open_violations  = Violation.query.filter_by(status="Open").count()

    sev_rows = (
        db.session.query(Violation.severity, func.count())
        .group_by(Violation.severity)
        .all()
    )
    severity_counts = {sev: cnt for sev, cnt in sev_rows}

    type_rows = (
        db.session.query(Violation.violation_type, func.count())
        .group_by(Violation.violation_type)
        .all()
    )
    type_counts = {vt: cnt for vt, cnt in type_rows}

    source_rows = (
        db.session.query(Ticket.source, func.count())
        .group_by(Ticket.source)
        .all()
    )
    source_counts = {src: cnt for src, cnt in source_rows}

    # ── Compliance metrics ───────────────────────────────────────────────────
    analyzed_tickets = Ticket.query.filter(Ticket.analyzed_at.isnot(None)).count()
    total_controls   = len(current_app.config.get("CONTROLS", {})) or 9

    # Compliance Score: % of all possible ITGC checks that passed
    # (avoids the old penalty formula that hits 0 with just a handful of violations)
    total_possible = max(1, analyzed_tickets * total_controls)
    compliance_score = round(max(0, (total_possible - total_violations) / total_possible * 100))

    # Control Coverage: % of ingested tickets that have been analysed
    control_coverage = round(analyzed_tickets / max(1, total_tickets) * 100)

    # Audit Readiness: % of violations that are Acknowledged or Resolved
    addressed       = Violation.query.filter(Violation.status.in_(["Acknowledged", "Resolved"])).count()
    audit_readiness = 100 if total_violations == 0 else round(addressed / total_violations * 100)

    # Context numbers shown on the cards
    tickets_with_open = (
        db.session.query(func.count(func.distinct(Violation.ticket_id)))
        .filter(Violation.status == "Open")
        .scalar() or 0
    )
    clean_tickets = analyzed_tickets - tickets_with_open

    return jsonify(
        {
            "total_tickets":     total_tickets,
            "total_violations":  total_violations,
            "open_violations":   open_violations,
            "severity_counts":   severity_counts,
            "type_counts":       type_counts,
            "source_counts":     source_counts,
            # compliance metrics
            "compliance_score":  compliance_score,
            "control_coverage":  control_coverage,
            "audit_readiness":   audit_readiness,
            # raw context numbers for card sub-text
            "analyzed_tickets":  analyzed_tickets,
            "clean_tickets":     clean_tickets,
            "addressed":         addressed,
            "total_controls":    total_controls,
        }
    )


@api_bp.route("/alerts")
def alerts():
    """Return the 25 most recent violations for the live alert feed."""
    rows = (
        Violation.query.order_by(Violation.detected_at.desc()).limit(25).all()
    )
    return jsonify([v.to_dict() for v in rows])


# ── Analysis Trigger ─────────────────────────────────────────────────────────

@api_bp.route("/analyze", methods=["POST"])
def analyze():
    from app.agent.compliance_engine import get_progress
    if get_progress()["running"]:
        return jsonify({"started": False, "error": "Analysis already in progress"}), 409

    app = current_app._get_current_object()

    def _bg():
        from app.agent.compliance_engine import _set, get_progress
        try:
            with app.app_context():
                from app.extensions import db as _db
                from app.agent.compliance_engine import ComplianceEngine
                try:
                    ComplianceEngine().run_analysis(use_llm=True)
                finally:
                    try:
                        _db.session.remove()
                    except Exception:
                        pass
        except Exception as exc:
            # Safety net: if run_analysis never ran (e.g. constructor failed),
            # running would still be True — reset it now so the frontend unblocks.
            if get_progress()["running"]:
                _set(running=False, stage=f"Failed: {exc}")

    threading.Thread(target=_bg, daemon=True).start()
    return jsonify({"started": True})


@api_bp.route("/analyze/progress")
def analyze_progress():
    from app.agent.compliance_engine import get_progress
    return jsonify(get_progress())


# ── Violations ────────────────────────────────────────────────────────────────

@api_bp.route("/violations")
def list_violations():
    severity = request.args.get("severity")
    status = request.args.get("status")
    q = Violation.query.order_by(Violation.detected_at.desc())
    if severity:
        q = q.filter_by(severity=severity)
    if status:
        q = q.filter_by(status=status)
    return jsonify([v.to_dict() for v in q.limit(100).all()])


@api_bp.route("/violations/<vid>/acknowledge", methods=["POST"])
def acknowledge_violation(vid: str):
    v = Violation.query.get_or_404(vid)
    v.status = "Acknowledged"
    db.session.commit()
    return jsonify(v.to_dict())


@api_bp.route("/violations/<vid>/resolve", methods=["POST"])
def resolve_violation(vid: str):
    v = Violation.query.get_or_404(vid)
    v.status = "Resolved"
    db.session.commit()
    return jsonify(v.to_dict())


# ── Evidence ──────────────────────────────────────────────────────────────────

@api_bp.route("/evidence")
def list_evidence():
    rows = AuditEvidence.query.order_by(AuditEvidence.generated_at.desc()).limit(100).all()
    return jsonify([e.to_dict() for e in rows])


@api_bp.route("/evidence/<eid>")
def get_evidence(eid: str):
    ev = AuditEvidence.query.get_or_404(eid)
    return jsonify(ev.to_dict())


@api_bp.route("/evidence/<eid>/export/json")
def export_evidence_json(eid: str):
    ev = AuditEvidence.query.get_or_404(eid)
    payload = ev.to_dict()
    buf = io.BytesIO(json.dumps(payload, indent=2).encode())
    buf.seek(0)
    return send_file(
        buf,
        mimetype="application/json",
        as_attachment=True,
        download_name=f"audit_evidence_{eid[:8]}.json",
    )


def _safe_text(text: str) -> str:
    """Sanitise text for fpdf's built-in Latin-1 fonts.

    LLM output routinely contains Unicode punctuation that Helvetica can't
    render.  Replace the most common offenders with ASCII equivalents, then
    drop anything still outside Latin-1 so fpdf never throws.
    """
    replacements = {
        "\u2013": "-",    # en dash  –
        "\u2014": "--",   # em dash  —
        "\u2018": "'",    # left single quote  '
        "\u2019": "'",    # right single quote  '
        "\u201c": '"',    # left double quote  "
        "\u201d": '"',    # right double quote  "
        "\u2026": "...",  # ellipsis  …
        "\u00a0": " ",    # non-breaking space
        "\u2022": "*",    # bullet  •
        "\u2192": "->",   # right arrow  →
        "\u2190": "<-",   # left arrow  ←
        "\u00b7": "*",    # middle dot  ·
        "\u2212": "-",    # minus sign  −
    }
    for ch, replacement in replacements.items():
        text = text.replace(ch, replacement)
    # Drop anything still outside Latin-1 rather than crashing
    return text.encode("latin-1", errors="replace").decode("latin-1")


@api_bp.route("/evidence/<eid>/export/pdf")
def export_evidence_pdf(eid: str):
    ev = AuditEvidence.query.get_or_404(eid)
    try:
        from fpdf import FPDF
    except ImportError:
        abort(501, description="fpdf2 not installed – run: pip install fpdf2")

    v = ev.violation
    t = v.ticket if v else None

    pdf = FPDF()
    pdf.set_margins(20, 20, 20)
    pdf.add_page()

    # ── Header ──────────────────────────────────────────────────────────────
    pdf.set_font("Helvetica", "B", 16)
    pdf.set_fill_color(30, 41, 59)   # slate-800
    pdf.set_text_color(255, 255, 255)
    pdf.cell(0, 12, "ITGC SOX Compliance - Audit Evidence Report", fill=True, ln=True, align="C")

    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(100, 116, 139)
    pdf.cell(0, 6, f"Report UUID: {ev.id}   |   Generated: {ev.generated_at.strftime('%Y-%m-%d %H:%M UTC')}", ln=True, align="C")
    pdf.ln(4)

    # ── Control Badge ────────────────────────────────────────────────────────
    sev_color = {"High": (239, 68, 68), "Medium": (245, 158, 11), "Low": (59, 130, 246)}.get(
        v.severity if v else "Low", (100, 116, 139)
    )
    pdf.set_fill_color(*sev_color)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(60, 8, f"  Control: {v.control_id if v else 'N/A'}", fill=True)
    pdf.cell(40, 8, f"  Severity: {v.severity if v else 'N/A'}", fill=True)
    pdf.cell(0, 8, f"  Status: {v.status if v else 'N/A'}", fill=True, ln=True)
    pdf.ln(4)

    def section(title: str):
        pdf.set_fill_color(241, 245, 249)
        pdf.set_text_color(15, 23, 42)
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(0, 8, f"  {_safe_text(title)}", fill=True, ln=True)
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(30, 41, 59)
        pdf.ln(1)

    def kv(label: str, value: str):
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_text_color(71, 85, 105)
        pdf.cell(50, 6, label + ":", ln=False)
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(15, 23, 42)
        pdf.multi_cell(0, 6, _safe_text(str(value) if value else "N/A"))

    # ── Ticket Details ────────────────────────────────────────────────────────
    section("Ticket Details")
    if t:
        kv("Ticket Key", t.ticket_key)
        kv("Source", t.source)
        kv("Title", t.title)
        kv("Status", t.status)
        kv("Type", t.ticket_type or "N/A")
        kv("Priority", t.priority or "N/A")
        kv("Requestor", t.requestor_id or "N/A")
        kv("Approver", t.approver_id or "N/A")
        kv("Implementer", t.implementer_id or "N/A")
        kv("Documentation Link", t.documentation_link or "MISSING")
    pdf.ln(3)

    # ── Violation Details ─────────────────────────────────────────────────────
    section("Violation Details")
    if v:
        kv("Violation UUID", v.id)
        kv("Violation Type", v.violation_type)
        kv("Detected At", v.detected_at.strftime("%Y-%m-%d %H:%M UTC"))
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_text_color(71, 85, 105)
        pdf.cell(50, 6, "Description:", ln=False)
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(15, 23, 42)
        pdf.multi_cell(0, 6, _safe_text(v.description))
    pdf.ln(3)

    # ── LLM Analysis ─────────────────────────────────────────────────────────
    section("AI-Powered Audit Analysis")
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(30, 41, 59)
    analysis = _safe_text(ev.llm_analysis or "[No LLM analysis available]")
    pdf.multi_cell(0, 5, analysis)

    # ── Footer ────────────────────────────────────────────────────────────────
    pdf.set_y(-20)
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(148, 163, 184)
    pdf.cell(0, 5, "CONFIDENTIAL - ITGC SOX Compliance Agent | For Internal Use Only", align="C")

    buf = io.BytesIO(pdf.output())
    buf.seek(0)
    return send_file(
        buf,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"audit_evidence_{eid[:8]}.pdf",
    )


# ── Custom Validation Rules ───────────────────────────────────────────────────

@api_bp.route("/rules", methods=["GET"])
def list_rules():
    rules = CustomRule.query.order_by(CustomRule.created_at.desc()).all()
    return jsonify([r.to_dict() for r in rules])


@api_bp.route("/rules", methods=["POST"])
def create_rule():
    payload = request.get_json(force=True)
    required = ("name", "control_id", "severity", "field", "operator")
    missing = [f for f in required if not payload.get(f)]
    if missing:
        return jsonify({"success": False, "error": f"Missing fields: {', '.join(missing)}"}), 400

    rule = CustomRule(
        name=payload["name"],
        description=payload.get("description", ""),
        control_id=payload["control_id"],
        severity=payload["severity"],
        field=payload["field"],
        operator=payload["operator"],
        value=payload.get("value") or None,
        apply_to_status=payload.get("apply_to_status") or None,
        apply_to_type=payload.get("apply_to_type") or None,
        enabled=payload.get("enabled", True),
    )
    db.session.add(rule)
    db.session.commit()
    return jsonify({"success": True, "rule": rule.to_dict()}), 201


def _infer_rule_from_text(text: str) -> dict:
    """Heuristic parser: plain-English rule text -> CustomRule shape."""
    raw = (text or "").strip()
    low = raw.lower()
    if not raw:
        return {}

    field_map = [
        ("approver", "approver_id"),
        ("requestor", "requestor_id"),
        ("requester", "requestor_id"),
        ("implementer", "implementer_id"),
        ("status", "status"),
        ("priority", "priority"),
        ("documentation", "documentation_link"),
        ("doc link", "documentation_link"),
        ("source", "source"),
        ("title", "title"),
        ("comment author", "comments.author"),
        ("comment by", "comments.author"),
        ("comments", "comments.text"),
        ("comment", "comments.text"),
        ("ticket type", "ticket_type"),
        ("type", "ticket_type"),
    ]

    field = ""
    for needle, mapped in field_map:
        if needle in low:
            field = mapped
            break
    if not field:
        field = "title"

    operator = "contains"
    value = ""

    quoted = re.findall(r'"([^"]+)"|\'([^\']+)\'', raw)
    quoted_vals = [a or b for a, b in quoted if (a or b)]
    first_quoted = quoted_vals[0] if quoted_vals else ""

    if any(k in low for k in ("must have", "should have", "required", "is required", "not empty", "cannot be empty")):
        operator = "is_empty"
    elif any(k in low for k in ("must be empty", "should be empty")):
        operator = "is_not_empty"
    elif "must not contain" in low or "should not contain" in low or "cannot contain" in low:
        operator = "contains"
        value = first_quoted or ""
    elif "must contain" in low or "should contain" in low or "must include" in low:
        operator = "not_contains"
        value = first_quoted or ""
    elif "must not equal" in low or "should not equal" in low:
        operator = "equals"
        value = first_quoted or ""
    elif "must equal" in low or "should equal" in low or "equals" in low:
        operator = "not_equals"
        value = first_quoted or ""
    else:
        m = re.search(r"(contains|equals|is)\s+([a-zA-Z0-9_.-]+)", low)
        if m:
            token = m.group(2).strip()
            operator = "contains" if m.group(1) == "contains" else "not_equals"
            value = first_quoted or token

    severity = "Medium"
    if "high" in low or "critical" in low:
        severity = "High"
    elif "low" in low:
        severity = "Low"

    apply_to_status = ""
    if "resolved" in low:
        apply_to_status = "Resolved"
    elif "closed" in low:
        apply_to_status = "Closed"
    elif "open" in low:
        apply_to_status = "Open"

    apply_to_type = ""
    if "incident" in low:
        apply_to_type = "Incident"
    elif "change request" in low:
        apply_to_type = "Change Request"
    elif "access request" in low:
        apply_to_type = "Access Request"

    name = raw.split(".")[0].strip()
    if len(name) > 80:
        name = name[:80].rstrip() + "..."

    return {
        "name": name or "Custom validation rule",
        "description": raw,
        "control_id": "ITGC-CUSTOM-001",
        "severity": severity,
        "field": field,
        "operator": operator,
        "value": value,
        "apply_to_status": apply_to_status,
        "apply_to_type": apply_to_type,
        "enabled": True,
    }


@api_bp.route("/rules/interpret", methods=["POST"])
def interpret_rule():
    payload = request.get_json(force=True) or {}
    rule_text = payload.get("rule_text", "")
    inferred = _infer_rule_from_text(rule_text)
    if not inferred:
        return jsonify({"success": False, "error": "Rule text is empty"}), 400
    return jsonify({"success": True, "rule": inferred})


@api_bp.route("/rules/<rid>", methods=["PUT"])
def update_rule(rid: str):
    rule = CustomRule.query.get_or_404(rid)
    payload = request.get_json(force=True)
    for attr in ("name", "description", "control_id", "severity", "field", "operator"):
        if attr in payload:
            setattr(rule, attr, payload[attr])
    for attr in ("value", "apply_to_status", "apply_to_type"):
        if attr in payload:
            setattr(rule, attr, payload[attr] or None)
    if "enabled" in payload:
        rule.enabled = bool(payload["enabled"])
    db.session.commit()
    return jsonify({"success": True, "rule": rule.to_dict()})


@api_bp.route("/rules/<rid>", methods=["DELETE"])
def delete_rule(rid: str):
    rule = CustomRule.query.get_or_404(rid)
    db.session.delete(rule)
    db.session.commit()
    return jsonify({"success": True})


@api_bp.route("/rules/<rid>/toggle", methods=["POST"])
def toggle_rule(rid: str):
    rule = CustomRule.query.get_or_404(rid)
    rule.enabled = not rule.enabled
    db.session.commit()
    return jsonify({"success": True, "enabled": rule.enabled})


@api_bp.route("/controls", methods=["GET"])
def list_controls():
    controls = _get_effective_controls()
    payload = [{"key": k, **v} for k, v in controls.items()]
    return jsonify(payload)


@api_bp.route("/controls", methods=["POST"])
def save_controls():
    payload = request.get_json(force=True) or {}
    enabled = payload.get("enabled", [])
    if not isinstance(enabled, list):
        return jsonify({"success": False, "error": "enabled must be a list"}), 400

    controls = current_app.config.get("CONTROLS", {})
    valid_keys = {k for k in controls.keys()}
    enabled_keys = [k for k in enabled if k in valid_keys]

    row = Setting.query.filter_by(key="enabled_controls").first()
    value = ",".join(enabled_keys)
    if row:
        row.value = value
        row.updated_at = datetime.utcnow()
    else:
        db.session.add(Setting(key="enabled_controls", value=value))
    db.session.commit()
    return jsonify({"success": True, "enabled": enabled_keys})


# ── Data Reset ────────────────────────────────────────────────────────────────

@api_bp.route("/data/reset", methods=["POST"])
def reset_data():
    """Delete all tickets, violations, and evidence records (settings are preserved)."""
    try:
        AuditEvidence.query.delete()
        Violation.query.delete()
        Ticket.query.delete()
        db.session.commit()
        return jsonify({"success": True, "message": "All compliance data cleared."})
    except Exception as exc:
        db.session.rollback()
        return jsonify({"success": False, "error": str(exc)}), 500

@api_bp.route("/data/reset-all", methods=["POST"])
def reset_all_data():
    """Delete all persisted records, then reseed default settings."""
    try:
        from app import _seed_default_settings

        AuditEvidence.query.delete()
        Violation.query.delete()
        Ticket.query.delete()
        CustomRule.query.delete()
        Setting.query.delete()
        db.session.commit()

        _seed_default_settings()
        return jsonify({"success": True, "message": "All database entries cleared and default settings restored."})
    except Exception as exc:
        db.session.rollback()
        return jsonify({"success": False, "error": str(exc)}), 500

# ── Settings ──────────────────────────────────────────────────────────────────

@api_bp.route("/settings", methods=["GET"])
def get_settings():
    rows = Setting.query.all()
    data = {r.key: r.value for r in rows}
    # Never expose secrets – mask sensitive fields
    if data.get("llm_api_key"):
        data["llm_api_key"] = "sk-" + "*" * 20
    if data.get("snow_client_secret"):
        data["snow_client_secret"] = "*" * 20
    if data.get("smtp_password"):
        data["smtp_password"] = "*" * 20
    return jsonify(data)


_SECRET_KEYS = {"llm_api_key", "jira_api_token", "snow_client_secret", "smtp_password"}


@api_bp.route("/settings", methods=["POST"])
def save_settings():
    payload: dict = request.get_json(force=True)
    for key, value in payload.items():
        # Don't overwrite any secret/token with an empty or masked value
        if key in _SECRET_KEYS and not value:
            continue
        if key == "llm_api_key" and str(value).startswith("sk-***"):
            continue
        if key == "snow_client_secret" and set(str(value)) == {"*"}:
            continue
        if key == "smtp_password" and set(str(value)) == {"*"}:
            continue
        row = Setting.query.filter_by(key=key).first()
        if row:
            row.value = str(value)
            row.updated_at = datetime.utcnow()
        else:
            db.session.add(Setting(key=key, value=str(value)))
    db.session.commit()

    # Reconfigure scheduler if monitoring settings changed
    if "monitor_interval_minutes" in payload or "monitor_enabled" in payload:
        from app.scheduler import reconfigure
        row = Setting.query.filter_by(key="monitor_interval_minutes").first()
        interval = int(row.value) if row and row.value.isdigit() else 60
        reconfigure(current_app._get_current_object(), interval)

    return jsonify({"success": True})


@api_bp.route("/scheduler/status")
def scheduler_status():
    from app.scheduler import get_status
    return jsonify(get_status())


@api_bp.route("/health")
def health():
    from app.services.jira_service import JiraService
    from app.services.snow_service import ServiceNowService
    settings = {r.key: r.value for r in Setting.query.all()}
    jira_h = JiraService(settings.get("jira_url", ""), settings.get("jira_username", ""), settings.get("jira_api_token", "")).health_check()
    snow_h = ServiceNowService(settings.get("snow_url", ""), settings.get("snow_client_id", ""), settings.get("snow_client_secret", ""), settings.get("snow_client_name", "")).health_check()
    return jsonify({"jira": jira_h, "servicenow": snow_h})


@api_bp.route("/health/llm", methods=["POST"])
def health_llm():
    body = request.get_json(force=True) or {}

    api_key = body.get("llm_api_key", "")
    # Masked value from form — read real key from DB
    if not api_key or (api_key.startswith("sk-") and set(api_key[3:]) == {"*"}):
        settings = {r.key: r.value for r in Setting.query.all()}
        api_key = settings.get("llm_api_key", "")

    if not api_key:
        return jsonify({"connected": False, "error": "No API key saved — enter your key and save first"})

    provider = body.get("llm_provider", "anthropic")
    model = body.get("llm_model") or None
    azure_endpoint = body.get("azure_endpoint", "")
    azure_api_version = body.get("azure_api_version", "2024-02-15-preview")

    try:
        if provider == "anthropic":
            import anthropic as _ant
            c = _ant.Anthropic(api_key=api_key)
            resp = c.messages.create(
                model=model or "claude-sonnet-4-6",
                max_tokens=10,
                messages=[{"role": "user", "content": "Say OK"}],
            )
            reply = resp.content[0].text.strip()

        elif provider == "openai":
            import openai as _oai
            c = _oai.OpenAI(api_key=api_key)
            resp = c.chat.completions.create(
                model=model or "gpt-4o",
                max_completion_tokens=10,
                messages=[{"role": "user", "content": "Say OK"}],
            )
            reply = resp.choices[0].message.content.strip()

        elif provider == "azure_openai":
            import openai as _oai
            c = _oai.AzureOpenAI(
                api_key=api_key,
                azure_endpoint=azure_endpoint,
                api_version=azure_api_version,
            )
            resp = c.chat.completions.create(
                model=model or "gpt-4o",
                max_completion_tokens=10,
                messages=[{"role": "user", "content": "Say OK"}],
            )
            reply = resp.choices[0].message.content.strip()

        elif provider == "google":
            import google.genai as _genai
            c = _genai.Client(api_key=api_key)
            resp = c.models.generate_content(
                model=model or "gemini-2.0-flash",
                contents="Say OK",
            )
            reply = resp.text.strip()

        else:
            return jsonify({"connected": False, "error": f"Unknown provider: {provider}"})

        return jsonify({"connected": True, "model": model, "reply": reply})

    except ImportError as exc:
        pkg = {"anthropic": "anthropic", "openai": "openai",
               "azure_openai": "openai", "google": "google-generativeai"}.get(provider, "unknown")
        return jsonify({"connected": False, "error": f"SDK not installed — run: pip install {pkg} ({exc})"})
    except Exception as exc:
        return jsonify({"connected": False, "error": str(exc)})


@api_bp.route("/health/jira", methods=["GET", "POST"])
def health_jira():
    from app.services.jira_service import JiraService
    if request.is_json and request.json:
        body = request.json
    else:
        settings = {r.key: r.value for r in Setting.query.all()}
        body = settings
    return jsonify(JiraService(
        body.get("jira_url", ""),
        body.get("jira_username", ""),
        body.get("jira_api_token", ""),
    ).health_check())


@api_bp.route("/health/servicenow", methods=["GET", "POST"])
def health_servicenow():
    from app.services.snow_service import ServiceNowService
    if request.is_json and request.json:
        body = request.json
    else:
        settings = {r.key: r.value for r in Setting.query.all()}
        body = settings
    return jsonify(ServiceNowService(
        body.get("snow_url", ""),
        body.get("snow_client_id", ""),
        body.get("snow_client_secret", ""),
        body.get("snow_client_name", ""),
    ).health_check())


@api_bp.route("/health/smtp", methods=["POST"])
def health_smtp():
    from app.services.notification_service import NotificationService
    body = request.get_json(force=True) or {}
    settings = {r.key: r.value for r in Setting.query.all()}

    # Merge: use saved password if form field is empty or masked
    smtp_password = body.get("smtp_password", "")
    if not smtp_password or set(smtp_password) == {"*"}:
        smtp_password = settings.get("smtp_password", "")

    cfg = {**settings, **body, "smtp_password": smtp_password}
    svc = NotificationService(cfg)
    return jsonify(svc.test_email(override=cfg))


@api_bp.route("/health/webhook", methods=["POST"])
def health_webhook():
    from app.services.notification_service import NotificationService
    body = request.get_json(force=True) or {}
    settings = {r.key: r.value for r in Setting.query.all()}
    url = body.get("webhook_url") or settings.get("webhook_url", "")
    svc = NotificationService(settings)
    return jsonify(svc.test_webhook(url=url))

