"""
Rule-based ITGC compliance checks.

Each function receives a ticket dict and the app config (class or Flask dict),
and returns a (possibly empty) list of ViolationResult objects to be persisted.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ViolationResult:
    """Intermediate violation result before DB persistence."""
    violation_type: str
    control_id: str
    description: str
    severity: str
    metadata: dict = field(default_factory=dict)


# ── Config helpers (works with both Config class and Flask app.config dict) ──

def _controls(cfg: Any) -> dict:
    return cfg["CONTROLS"] if isinstance(cfg, dict) else cfg.CONTROLS

def _approvers(cfg: Any) -> list:
    return cfg["AUTHORIZED_APPROVERS"] if isinstance(cfg, dict) else cfg.AUTHORIZED_APPROVERS

def _software(cfg: Any) -> list:
    return cfg["APPROVED_SOFTWARE"] if isinstance(cfg, dict) else cfg.APPROVED_SOFTWARE


# ─────────────────────────────────────────────────────────────────────────────

def check_access_provisioning(
    ticket: dict[str, Any], config: Any
) -> list[ViolationResult]:
    """
    ITGC-AC-01 / ITGC-AC-02 / ITGC-AC-03
    - Self-approval: requestor_id == approver_id
    - Unauthorized approver: approver_id not in AUTHORIZED_APPROVERS
    - Privileged access: 'admin'/'privileged' tagged + unauthorized approver
    """
    controls = _controls(config)
    authorized = {a.lower() for a in _approvers(config)}
    results: list[ViolationResult] = []

    requestor = ticket.get("requestor_id", "")
    approver = ticket.get("approver_id", "")
    tags = [t.lower() for t in (ticket.get("tags") or [])]

    if requestor and approver and requestor == approver:
        results.append(
            ViolationResult(
                violation_type="SELF_APPROVAL",
                control_id=controls["SELF_APPROVAL"]["id"],
                severity=controls["SELF_APPROVAL"]["severity"],
                description=(
                    f"Self-approval detected: requestor and approver are the same user "
                    f"'{requestor}'. No individual may approve their own request."
                ),
                metadata={"requestor_id": requestor, "approver_id": approver},
            )
        )

    if approver and approver.lower() not in authorized:
        results.append(
            ViolationResult(
                violation_type="UNAUTHORIZED_APPROVER",
                control_id=controls["UNAUTHORIZED_APPROVER"]["id"],
                severity=controls["UNAUTHORIZED_APPROVER"]["severity"],
                description=(
                    f"Approver '{approver}' is not on the Authorized Owners list. "
                    "Only designated approvers may authorize access changes."
                ),
                metadata={"approver_id": approver},
            )
        )

    is_privileged = any(k in tags for k in ("admin", "privileged", "critical"))
    if is_privileged and approver and approver.lower() not in authorized:
        results.append(
            ViolationResult(
                violation_type="PRIVILEGED_ACCESS",
                control_id=controls["PRIVILEGED_ACCESS"]["id"],
                severity=controls["PRIVILEGED_ACCESS"]["severity"],
                description=(
                    f"Privileged/admin access granted via ticket tagged {tags} but approver "
                    f"'{approver}' is not on the Authorized Owners list."
                ),
                metadata={"approver_id": approver, "tags": tags},
            )
        )

    return results


def check_workflow_documentation(
    ticket: dict[str, Any], config: Any
) -> list[ViolationResult]:
    """
    ITGC-WF-01 – Closed tickets must have documentation_link populated.
    """
    controls = _controls(config)
    results: list[ViolationResult] = []

    if ticket.get("status", "").lower() in ("closed", "resolved"):
        if not ticket.get("documentation_link"):
            results.append(
                ViolationResult(
                    violation_type="MISSING_DOCUMENTATION",
                    control_id=controls["MISSING_DOCUMENTATION"]["id"],
                    severity=controls["MISSING_DOCUMENTATION"]["severity"],
                    description=(
                        f"Ticket '{ticket.get('ticket_key')}' is {ticket['status']} but "
                        "the mandatory documentation_link field is empty. "
                        "All closed/resolved tickets require a linked closure document."
                    ),
                    metadata={"status": ticket["status"]},
                )
            )
    return results


def check_sod(
    ticket: dict[str, Any], config: Any
) -> list[ViolationResult]:
    """
    ITGC-SOD-01 – Detect toxic role combinations.
    Flags when any single user occupies >1 of: Requestor, Approver, Implementer.
    """
    controls = _controls(config)
    results: list[ViolationResult] = []

    requestor = ticket.get("requestor_id", "")
    approver = ticket.get("approver_id", "")
    implementer = ticket.get("implementer_id", "")

    role_map: dict[str, list[str]] = {}
    for role, uid in [("Requestor", requestor), ("Approver", approver), ("Implementer", implementer)]:
        if uid:
            role_map.setdefault(uid, []).append(role)

    for uid, roles in role_map.items():
        if len(roles) > 1:
            if roles == ["Requestor", "Approver"]:
                continue  # already flagged by ITGC-AC-01
            toxic_combos = " + ".join(roles)
            results.append(
                ViolationResult(
                    violation_type="SOD_VIOLATION",
                    control_id=controls["SOD_VIOLATION"]["id"],
                    severity=controls["SOD_VIOLATION"]["severity"],
                    description=(
                        f"Segregation of Duties violation: user '{uid}' occupies conflicting "
                        f"roles [{toxic_combos}] within the same workflow. "
                        "These duties must be performed by separate individuals."
                    ),
                    metadata={"user": uid, "roles": roles},
                )
            )
    return results


def check_software(
    ticket: dict[str, Any], config: Any
) -> list[ViolationResult]:
    """
    ITGC-SW-01 – Flag software not on the Approved Software List.
    """
    controls = _controls(config)
    approved_lower = {s.lower() for s in _software(config)}
    results: list[ViolationResult] = []

    for entry in (ticket.get("installation_log") or []):
        sw = entry.get("software", "")
        if sw.lower() not in approved_lower:
            results.append(
                ViolationResult(
                    violation_type="UNAUTHORIZED_SOFTWARE",
                    control_id=controls["UNAUTHORIZED_SOFTWARE"]["id"],
                    severity=controls["UNAUTHORIZED_SOFTWARE"]["severity"],
                    description=(
                        f"Unauthorized software detected: '{sw}' (v{entry.get('version', 'N/A')}) "
                        f"installed by user '{entry.get('user', 'unknown')}'. "
                        "This application is not present on the Approved Software List."
                    ),
                    metadata={"software": sw, "version": entry.get("version"), "user": entry.get("user")},
                )
            )
    return results


def check_missing_approval(
    ticket: dict[str, Any], config: Any
) -> list[ViolationResult]:
    """
    ITGC-AC-04 (Task 1) – Closed/resolved ticket must have an approver assigned.
    ITGC-AC-05 (Task 1) – If approval_timestamp and closed_at are present in raw
                           data, approval must precede closure.
    """
    controls = _controls(config)
    results: list[ViolationResult] = []

    is_closed = ticket.get("status", "").lower() in ("closed", "resolved")
    approver = ticket.get("approver_id", "")

    # Missing approval
    if is_closed and not approver:
        results.append(
            ViolationResult(
                violation_type="MISSING_APPROVAL",
                control_id=controls["MISSING_APPROVAL"]["id"],
                severity=controls["MISSING_APPROVAL"]["severity"],
                description=(
                    f"Ticket '{ticket.get('ticket_key')}' is {ticket.get('status')} "
                    "but has no approver assigned. Every closed ticket requires an "
                    "explicit approval before closure."
                ),
                metadata={"status": ticket.get("status"), "approver_id": None},
            )
        )

    # Timestamp integrity (only when fields are present in raw data)
    approval_ts = ticket.get("approval_timestamp")
    closed_ts = ticket.get("closed_at")
    if approval_ts and closed_ts:
        try:
            from datetime import datetime
            fmt = "%Y-%m-%dT%H:%M:%S"
            ap = datetime.fromisoformat(str(approval_ts).replace("Z", "+00:00"))
            cl = datetime.fromisoformat(str(closed_ts).replace("Z", "+00:00"))
            if ap > cl:
                results.append(
                    ViolationResult(
                        violation_type="INVALID_APPROVAL_TIMESTAMP",
                        control_id=controls["INVALID_APPROVAL_TIMESTAMP"]["id"],
                        severity=controls["INVALID_APPROVAL_TIMESTAMP"]["severity"],
                        description=(
                            f"Ticket '{ticket.get('ticket_key')}': approval timestamp "
                            f"({approval_ts}) is after the closure timestamp ({closed_ts}). "
                            "Approval must be granted before a ticket can be closed."
                        ),
                        metadata={"approval_timestamp": approval_ts, "closed_at": closed_ts},
                    )
                )
        except (ValueError, TypeError):
            pass  # malformed timestamp – skip rather than crash

    return results


def check_missing_implementer(
    ticket: dict[str, Any], config: Any
) -> list[ViolationResult]:
    """
    ITGC-WF-02 (Task 2) – Closed/resolved ticket must have an implementer assigned.
    Catches cases where the mandatory implementation step was skipped.
    """
    controls = _controls(config)
    results: list[ViolationResult] = []

    is_closed = ticket.get("status", "").lower() in ("closed", "resolved")
    implementer = ticket.get("implementer_id", "")

    if is_closed and not implementer:
        results.append(
            ViolationResult(
                violation_type="MISSING_IMPLEMENTER",
                control_id=controls["MISSING_IMPLEMENTER"]["id"],
                severity=controls["MISSING_IMPLEMENTER"]["severity"],
                description=(
                    f"Ticket '{ticket.get('ticket_key')}' is {ticket.get('status')} "
                    "but has no implementer assigned. The implementation step is mandatory "
                    "and must be completed before closure."
                ),
                metadata={"status": ticket.get("status"), "implementer_id": None},
            )
        )
    return results


def run_custom_rules(ticket: dict, rules: list) -> list[ViolationResult]:
    """
    Evaluate user-defined CustomRule objects against a ticket.
    `rules` is a list of CustomRule ORM instances (or dicts with same keys).
    """
    results: list[ViolationResult] = []

    for rule in rules:
        # Support both ORM object and plain dict
        def _get(attr: str, default: Any = "") -> Any:
            return getattr(rule, attr, None) if not isinstance(rule, dict) else rule.get(attr, default)

        if not _get("enabled", True):
            continue

        # Scope filters
        apply_status = (_get("apply_to_status") or "").strip().lower()
        apply_type   = (_get("apply_to_type")   or "").strip().lower()
        if apply_status and ticket.get("status", "").lower() != apply_status:
            continue
        if apply_type and ticket.get("ticket_type", "").lower() != apply_type:
            continue

        field    = _get("field", "")
        operator = _get("operator", "")
        value    = (_get("value") or "").strip().lower()
        field_val = str(ticket.get(field) or "").lower()

        violated = False
        if operator == "is_empty":
            violated = not field_val
        elif operator == "is_not_empty":
            violated = bool(field_val)
        elif operator == "equals":
            violated = field_val == value
        elif operator == "not_equals":
            violated = field_val != value
        elif operator == "contains":
            violated = value in field_val
        elif operator == "not_contains":
            violated = value not in field_val

        if violated:
            rule_id   = _get("id", "custom")
            rule_name = _get("name", "Custom Rule")
            vtype = f"CUSTOM_{str(rule_id)[:8].upper()}"
            results.append(
                ViolationResult(
                    violation_type=vtype,
                    control_id=_get("control_id", "ITGC-CUSTOM"),
                    severity=_get("severity", "Medium"),
                    description=(
                        _get("description")
                        or f"Custom rule '{rule_name}' violated: field '{field}' {operator}"
                        + (f" '{_get('value')}'" if _get("value") else "")
                        + f" on ticket '{ticket.get('ticket_key', 'N/A')}'."
                    ),
                    metadata={
                        "rule_id": rule_id,
                        "rule_name": rule_name,
                        "field": field,
                        "operator": operator,
                        "value": _get("value"),
                    },
                )
            )

    return results


def run_all_checks(ticket: dict, config: Any) -> list[ViolationResult]:
    """Run all compliance checks against a single ticket."""
    violations: list[ViolationResult] = []
    violations.extend(check_access_provisioning(ticket, config))    # Task 1 (partial)
    violations.extend(check_missing_approval(ticket, config))        # Task 1 (missing approval + timestamp)
    violations.extend(check_workflow_documentation(ticket, config))  # Task 2 (missing docs)
    violations.extend(check_missing_implementer(ticket, config))     # Task 2 (missing implementer)
    violations.extend(check_sod(ticket, config))                     # Task 3
    violations.extend(check_software(ticket, config))                # Task 4
    return violations
