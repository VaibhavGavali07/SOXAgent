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


def _controls(cfg: Any) -> dict:
    """Config helper that supports both Config class and Flask app.config dict."""
    return cfg["CONTROLS"] if isinstance(cfg, dict) else cfg.CONTROLS


def _approvers(cfg: Any) -> list:
    return cfg["AUTHORIZED_APPROVERS"] if isinstance(cfg, dict) else cfg.AUTHORIZED_APPROVERS


def _software(cfg: Any) -> list:
    return cfg["APPROVED_SOFTWARE"] if isinstance(cfg, dict) else cfg.APPROVED_SOFTWARE


def _enabled(cfg: Any, control_key: str) -> bool:
    controls = _controls(cfg)
    data = controls.get(control_key, {})
    return bool(data.get("enabled", True))


_APPROVAL_KEYWORDS = (
    "approve",
    "approved",
    "approval",
    "authorized",
    "authorised",
    "go ahead",
)

_IMPLEMENTATION_KEYWORDS = (
    "implemented",
    "implementation",
    "deployed",
    "applied",
    "fixed",
    "resolved",
    "completed",
)

_DOCUMENTATION_KEYWORDS = (
    "evidence",
    "attached",
    "document",
    "runbook",
    "test result",
    "validation",
    "closure note",
    "change record",
)


def _norm(value: Any) -> str:
    return str(value or "").strip()


def _normalize_comments(ticket: dict[str, Any]) -> list[dict[str, str]]:
    """Normalize comments into [{'author': str, 'text': str}] across source formats."""
    raw_comments = ticket.get("comments")
    candidates: list[Any] = []

    if isinstance(raw_comments, list):
        candidates.extend(raw_comments)
    elif isinstance(raw_comments, dict):
        candidates.append(raw_comments)
    elif isinstance(raw_comments, str) and raw_comments.strip():
        candidates.append({"author": "unknown", "text": raw_comments})

    # Fallback fields frequently used by ticket systems.
    for key in ("work_notes", "close_notes", "comments_and_work_notes"):
        value = ticket.get(key)
        if isinstance(value, list):
            candidates.extend(value)
        elif isinstance(value, dict):
            candidates.append(value)
        elif isinstance(value, str) and value.strip():
            candidates.append({"author": "unknown", "text": value})

    normalized: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    for entry in candidates:
        if isinstance(entry, dict):
            author = _norm(
                entry.get("author")
                or entry.get("added_by")
                or entry.get("user")
                or entry.get("created_by")
                or entry.get("sys_created_by")
                or entry.get("from")
                or "unknown"
            )
            text = _norm(
                entry.get("text")
                or entry.get("body")
                or entry.get("comment")
                or entry.get("value")
                or entry.get("message")
                or entry.get("content")
                or entry.get("note")
                or ""
            )
        else:
            author = "unknown"
            text = _norm(entry)

        if not text:
            continue

        key = (author.lower(), text.lower())
        if key in seen:
            continue
        seen.add(key)
        normalized.append({"author": author, "text": text})

    return normalized


def _contains_keyword(text: str, keywords: tuple[str, ...]) -> bool:
    text_lower = text.lower()
    return any(word in text_lower for word in keywords)


def _has_comment(
    comments: list[dict[str, str]],
    *,
    author: str | None = None,
    keywords: tuple[str, ...] | None = None,
) -> bool:
    author_lower = author.lower() if author else None

    for comment in comments:
        c_author = _norm(comment.get("author")).lower()
        c_text = _norm(comment.get("text"))

        if author_lower and c_author != author_lower:
            continue
        if keywords and not _contains_keyword(c_text, keywords):
            continue
        return True

    return False


def check_access_provisioning(ticket: dict[str, Any], config: Any) -> list[ViolationResult]:
    """ITGC-AC-01 / ITGC-AC-02 / ITGC-AC-03."""
    controls = _controls(config)
    authorized = {a.lower() for a in _approvers(config)}
    results: list[ViolationResult] = []

    requestor = ticket.get("requestor_id", "")
    approver = ticket.get("approver_id", "")
    tags = [t.lower() for t in (ticket.get("tags") or [])]

    if _enabled(config, "SELF_APPROVAL") and requestor and approver and requestor == approver:
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

    if _enabled(config, "UNAUTHORIZED_APPROVER") and approver and approver.lower() not in authorized:
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
    if _enabled(config, "PRIVILEGED_ACCESS") and is_privileged and approver and approver.lower() not in authorized:
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


def check_workflow_documentation(ticket: dict[str, Any], config: Any) -> list[ViolationResult]:
    """ITGC-WF-01: Closed tickets must have documentation_link or documentation comments."""
    controls = _controls(config)
    results: list[ViolationResult] = []
    if not _enabled(config, "MISSING_DOCUMENTATION"):
        return results

    is_closed = ticket.get("status", "").lower() in ("closed", "resolved")
    if not is_closed:
        return results

    comments = _normalize_comments(ticket)
    has_doc_link = bool(_norm(ticket.get("documentation_link")))
    has_doc_comment = _has_comment(comments, keywords=_DOCUMENTATION_KEYWORDS)

    if not has_doc_link and not has_doc_comment:
        results.append(
            ViolationResult(
                violation_type="MISSING_DOCUMENTATION",
                control_id=controls["MISSING_DOCUMENTATION"]["id"],
                severity=controls["MISSING_DOCUMENTATION"]["severity"],
                description=(
                    f"Ticket '{ticket.get('ticket_key')}' is {ticket.get('status')} but has no "
                    "documentation link and no documentation/evidence comment trail."
                ),
                metadata={"status": ticket.get("status"), "comments_count": len(comments)},
            )
        )

    return results


def check_sod(ticket: dict[str, Any], config: Any) -> list[ViolationResult]:
    """ITGC-SOD-01: flag toxic role combinations."""
    controls = _controls(config)
    results: list[ViolationResult] = []
    if not _enabled(config, "SOD_VIOLATION"):
        return results

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
                continue
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


def check_software(ticket: dict[str, Any], config: Any) -> list[ViolationResult]:
    """ITGC-SW-01: flag software not on the approved software list."""
    controls = _controls(config)
    approved_lower = {s.lower() for s in _software(config)}
    results: list[ViolationResult] = []
    if not _enabled(config, "UNAUTHORIZED_SOFTWARE"):
        return results

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


def check_missing_approval(ticket: dict[str, Any], config: Any) -> list[ViolationResult]:
    """ITGC-AC-04/05: approval identity + comment trail + timestamp order."""
    controls = _controls(config)
    results: list[ViolationResult] = []

    is_closed = ticket.get("status", "").lower() in ("closed", "resolved")
    approver = _norm(ticket.get("approver_id"))
    requestor = _norm(ticket.get("requestor_id"))
    comments = _normalize_comments(ticket)

    if is_closed:
        has_approval_comment_any = _has_comment(comments, keywords=_APPROVAL_KEYWORDS)
        has_approval_comment_by_approver = bool(approver) and _has_comment(
            comments, author=approver, keywords=_APPROVAL_KEYWORDS
        )

        if _enabled(config, "MISSING_APPROVAL") and not approver and not has_approval_comment_any:
            results.append(
                ViolationResult(
                    violation_type="MISSING_APPROVAL",
                    control_id=controls["MISSING_APPROVAL"]["id"],
                    severity=controls["MISSING_APPROVAL"]["severity"],
                    description=(
                        f"Ticket '{ticket.get('ticket_key')}' is {ticket.get('status')} but has no "
                        "approver and no approval comment trail."
                    ),
                    metadata={"status": ticket.get("status"), "approver_id": None, "comments_count": len(comments)},
                )
            )

        if _enabled(config, "MISSING_APPROVAL") and approver and not has_approval_comment_by_approver:
            results.append(
                ViolationResult(
                    violation_type="MISSING_APPROVAL_COMMENT",
                    control_id=controls["MISSING_APPROVAL"]["id"],
                    severity=controls["MISSING_APPROVAL"]["severity"],
                    description=(
                        f"Ticket '{ticket.get('ticket_key')}' has approver '{approver}', but no "
                        "approval comment from that approver was found."
                    ),
                    metadata={"approver_id": approver, "comments_count": len(comments)},
                )
            )

        if _enabled(config, "SELF_APPROVAL") and requestor and _has_comment(comments, author=requestor, keywords=_APPROVAL_KEYWORDS):
            results.append(
                ViolationResult(
                    violation_type="SELF_APPROVAL_COMMENT",
                    control_id=controls["SELF_APPROVAL"]["id"],
                    severity=controls["SELF_APPROVAL"]["severity"],
                    description=(
                        f"Potential self-approval by comment trail: requestor '{requestor}' added "
                        "an approval-like comment."
                    ),
                    metadata={"requestor_id": requestor},
                )
            )

    approval_ts = ticket.get("approval_timestamp")
    closed_ts = ticket.get("closed_at")
    if _enabled(config, "INVALID_APPROVAL_TIMESTAMP") and approval_ts and closed_ts:
        try:
            from datetime import datetime

            ap = datetime.fromisoformat(str(approval_ts).replace("Z", "+00:00"))
            cl = datetime.fromisoformat(str(closed_ts).replace("Z", "+00:00"))
            if ap > cl:
                results.append(
                    ViolationResult(
                        violation_type="INVALID_APPROVAL_TIMESTAMP",
                        control_id=controls["INVALID_APPROVAL_TIMESTAMP"]["id"],
                        severity=controls["INVALID_APPROVAL_TIMESTAMP"]["severity"],
                        description=(
                            f"Ticket '{ticket.get('ticket_key')}': approval timestamp ({approval_ts}) "
                            f"is after closure timestamp ({closed_ts})."
                        ),
                        metadata={"approval_timestamp": approval_ts, "closed_at": closed_ts},
                    )
                )
        except (ValueError, TypeError):
            pass

    return results


def check_missing_implementer(ticket: dict[str, Any], config: Any) -> list[ViolationResult]:
    """ITGC-WF-02: implementer identity + implementation comment trail."""
    controls = _controls(config)
    results: list[ViolationResult] = []
    if not _enabled(config, "MISSING_IMPLEMENTER"):
        return results

    is_closed = ticket.get("status", "").lower() in ("closed", "resolved")
    implementer = _norm(ticket.get("implementer_id"))
    comments = _normalize_comments(ticket)

    if is_closed and not implementer:
        results.append(
            ViolationResult(
                violation_type="MISSING_IMPLEMENTER",
                control_id=controls["MISSING_IMPLEMENTER"]["id"],
                severity=controls["MISSING_IMPLEMENTER"]["severity"],
                description=(
                    f"Ticket '{ticket.get('ticket_key')}' is {ticket.get('status')} but has no "
                    "implementer assigned."
                ),
                metadata={"status": ticket.get("status"), "implementer_id": None},
            )
        )

    if is_closed and implementer and not _has_comment(
        comments, author=implementer, keywords=_IMPLEMENTATION_KEYWORDS
    ):
        results.append(
            ViolationResult(
                violation_type="MISSING_IMPLEMENTER_COMMENT",
                control_id=controls["MISSING_IMPLEMENTER"]["id"],
                severity=controls["MISSING_IMPLEMENTER"]["severity"],
                description=(
                    f"Ticket '{ticket.get('ticket_key')}' has implementer '{implementer}', but no "
                    "implementation/closure comment from that implementer was found."
                ),
                metadata={"implementer_id": implementer, "comments_count": len(comments)},
            )
        )

    return results


def run_custom_rules(ticket: dict, rules: list) -> list[ViolationResult]:
    """Evaluate user-defined CustomRule objects against a ticket."""
    results: list[ViolationResult] = []
    comments = _normalize_comments(ticket)

    for rule in rules:
        def _get(attr: str, default: Any = "") -> Any:
            return getattr(rule, attr, None) if not isinstance(rule, dict) else rule.get(attr, default)

        if not _get("enabled", True):
            continue

        apply_status = (_get("apply_to_status") or "").strip().lower()
        apply_type = (_get("apply_to_type") or "").strip().lower()
        if apply_status and ticket.get("status", "").lower() != apply_status:
            continue
        if apply_type and ticket.get("ticket_type", "").lower() != apply_type:
            continue

        field = (_get("field") or "").strip()
        operator = (_get("operator") or "").strip()
        value = (_get("value") or "").strip().lower()

        field_lower = field.lower()
        if field_lower in {"comments", "comment", "comments.text", "comment_text"}:
            field_val = "\n".join(c["text"].lower() for c in comments)
        elif field_lower in {"comments.author", "comment_author", "comment.by", "added_by"}:
            field_val = ",".join(c["author"].lower() for c in comments)
        else:
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
            rule_id = _get("id", "custom")
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
    # Primary focus controls (requested order)
    violations.extend(check_access_provisioning(ticket, config))   # ITGC-AC-01 (others gated by enable flags)
    violations.extend(check_workflow_documentation(ticket, config))
    violations.extend(check_software(ticket, config))
    violations.extend(check_missing_approval(ticket, config))       # ITGC-AC-04 (AC-05 gated by enable flag)
    violations.extend(check_missing_implementer(ticket, config))
    # Secondary controls (kept visible, executed only if enabled)
    violations.extend(check_sod(ticket, config))
    return violations
