"""
Rule-based ITGC compliance checks.

Each function receives a ticket dict and the app config (class or Flask dict),
and returns a (possibly empty) list of ViolationResult objects to be persisted.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import re
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


def _cfg_value(cfg: Any, key: str, default: Any = None) -> Any:
    if isinstance(cfg, dict):
        return cfg.get(key, default)
    return getattr(cfg, key, default)


_APPROVAL_KEYWORDS = (
    "approve",
    "approved",
    "approval",
    "authorized",
    "authorised",
    "go ahead",
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
    "screenshot",
    "screen shot",
    "attaced",
)

_RESOLUTION_NOTE_KEYWORDS = (
    "resolution",
    "resolved",
    "fix",
    "fixed",
    "root cause",
    "closure note",
    "close note",
)

_CLOSER_COMMENT_KEYWORDS = (
    "approval provided",
    "approved",
    "access provided",
    "access granted",
    "provisioned",
    "implemented",
    "resolved",
    "completed",
    "closed",
    "granted",
)

_CLOSURE_SUCCESS_KEYWORDS = (
    "success",
    "successfully",
    "completed",
    "resolved",
    "implemented",
    "fixed",
    "access provided",
    "access granted",
    "granted",
)

_CLOSURE_ISSUE_KEYWORDS = (
    "issue",
    "failed",
    "failure",
    "error",
    "blocked",
    "pending",
    "rollback",
    "reopened",
    "exception",
)

_DUPLICATE_EXPLANATION_KEYWORDS = (
    "duplicate",
    "already exists",
    "existing ticket",
    "same issue",
    "linked ticket",
    "merged with",
    "see inc",
    "see req",
    "refer to",
)

_SOFTWARE_CONTEXT_KEYWORDS = (
    "install",
    "installed",
    "installation",
    "software",
    "tool",
    "application",
    "app",
    "package",
    "access",
    "provide access",
    "grant access",
    "use",
    "deploy",
)


def _norm(value: Any) -> str:
    return str(value or "").strip()


def _normalize_comments(ticket: dict[str, Any]) -> list[dict[str, str]]:
    """Normalize comments into [{'author': str, 'text': str, 'created_at': str}] across source formats."""
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
        created_at = ""
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
            created_at = _norm(
                entry.get("created_at")
                or entry.get("created")
                or entry.get("timestamp")
                or entry.get("sys_created_on")
                or entry.get("time")
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
        normalized.append({"author": author, "text": text, "created_at": created_at})

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


def _llm_comment_result(
    ticket: dict[str, Any],
    config: Any,
    comments: list[dict[str, str]],
) -> dict[str, Any]:
    cache_key = "_llm_rule_eval"
    if cache_key in ticket:
        return ticket.get(cache_key) or {}

    evaluator = _cfg_value(config, "COMMENT_RULE_EVALUATOR")
    if evaluator is None or not hasattr(evaluator, "evaluate"):
        ticket[cache_key] = {}
        return {}

    try:
        result = evaluator.evaluate(ticket=ticket, comments=comments)
        ticket[cache_key] = result if isinstance(result, dict) else {}
        return ticket[cache_key]
    except Exception:
        ticket[cache_key] = {}
        return {}


def _canon_user(value: Any) -> str:
    user = _norm(value).lower()
    if not user:
        return ""
    if "@" in user:
        user = user.split("@", 1)[0]
    return "".join(ch for ch in user if ch.isalnum())


def _author_matches(author: str, expected_user: str) -> bool:
    a = _canon_user(author)
    e = _canon_user(expected_user)
    if not a or not e:
        return False
    return a == e or e in a or a in e


def _find_comments(
    comments: list[dict[str, str]],
    *,
    author: str | None = None,
    keywords: tuple[str, ...] | None = None,
) -> list[dict[str, str]]:
    matched: list[dict[str, str]] = []
    for comment in comments:
        c_author = _norm(comment.get("author"))
        c_text = _norm(comment.get("text"))
        if author and not _author_matches(c_author, author):
            continue
        if keywords and not _contains_keyword(c_text, keywords):
            continue
        matched.append(comment)
    return matched


def _all_ticket_text(ticket: dict[str, Any], comments: list[dict[str, str]]) -> str:
    chunks = [
        _norm(ticket.get("title")),
        _norm(ticket.get("description")),
        _norm(ticket.get("summary")),
    ]
    chunks.extend(_norm(c.get("text")) for c in comments)
    return "\n".join(x for x in chunks if x)


def _extract_software_candidates(text: str) -> set[str]:
    candidates: set[str] = set()
    # Explicit forms like "software: xyz", "tool - abc", "install xyz".
    patterns = [
        r"(?:software|tool|application|app|package)\s*[:\-]\s*([A-Za-z0-9][A-Za-z0-9 ._+\-/]{1,60}?)(?=\s(?:for|to|by|on|in|with|from|user|requestor|requester|employee|account|id|role|group|permission|permissions|access|license|licence|environment|env)\b|[.,;:()\[\]{}]|$)",
        r"(?:install|use|deploy|grant access to|provide access to)\s+([A-Za-z0-9][A-Za-z0-9 ._+\-/]{1,60}?)(?=\s(?:for|to|by|on|in|with|from|user|requestor|requester|employee|account|id|role|group|permission|permissions|access|license|licence|environment|env)\b|[.,;:()\[\]{}]|$)",
    ]
    for pat in patterns:
        for m in re.finditer(pat, text, flags=re.IGNORECASE):
            raw = _norm(m.group(1)).strip(" .,:;()[]{}")
            if raw:
                candidates.add(raw)
    return candidates


def _is_approved_software(candidate: str, approved_lower: set[str]) -> bool:
    c = candidate.lower()
    if not c:
        return True
    if c in approved_lower:
        return True
    # Allow close matches for version/tag differences.
    if any(c in approved or approved in c for approved in approved_lower):
        return True

    def _core_tokens(name: str) -> set[str]:
        generic = {
            "software",
            "tool",
            "tools",
            "application",
            "app",
            "package",
            "client",
            "desktop",
            "agent",
            "suite",
            "platform",
            "system",
            "access",
        }
        tokens = re.findall(r"[a-z0-9]+", name.lower())
        return {t for t in tokens if t and t not in generic}

    cand_tokens = _core_tokens(c)
    if not cand_tokens:
        return True

    for approved in approved_lower:
        app_tokens = _core_tokens(approved)
        if not app_tokens:
            continue
        if cand_tokens == app_tokens:
            return True
        if cand_tokens.issubset(app_tokens) or app_tokens.issubset(cand_tokens):
            return True

        # Single-keyword alias match: e.g., "jira tool" vs "jira software".
        if len(cand_tokens) == 1:
            tok = next(iter(cand_tokens))
            if len(tok) >= 4 and tok in app_tokens:
                return True

    return False


def _parse_dt(raw: Any):
    if not raw:
        return None
    try:
        from datetime import datetime

        s = str(raw).strip().replace("Z", "+00:00")
        if " " in s and "T" not in s:
            s = s.replace(" ", "T")
        return datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None


def check_access_provisioning(ticket: dict[str, Any], config: Any) -> list[ViolationResult]:
    """ITGC-AC-01 / ITGC-AC-02 / ITGC-AC-03."""
    controls = _controls(config)
    authorized = {a.lower() for a in _approvers(config)}
    results: list[ViolationResult] = []

    requestor = ticket.get("requestor_id", "")
    approver = ticket.get("approver_id", "")
    tags = [t.lower() for t in (ticket.get("tags") or [])]

    if _enabled(config, "SELF_APPROVAL") and requestor and approver and _author_matches(approver, requestor):
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
    """ITGC-WF-01: Closed tickets need closure documentation and outcome comment trail."""
    controls = _controls(config)
    results: list[ViolationResult] = []
    if not _enabled(config, "MISSING_DOCUMENTATION"):
        return results

    is_closed = ticket.get("status", "").lower() in ("closed", "resolved")
    if not is_closed:
        return results

    comments = _normalize_comments(ticket)
    llm_eval = _llm_comment_result(ticket, config, comments)
    has_doc_link = bool(_norm(ticket.get("documentation_link")))
    has_doc_comment = _has_comment(comments, keywords=_DOCUMENTATION_KEYWORDS)
    raw_snow = ticket.get("_raw_snow") or {}
    # Primary requirement from ServiceNow: dedicated resolution note field.
    resolution_note = (
        _norm(ticket.get("resolution_note"))
        or _norm(raw_snow.get("resolution_note"))
        or _norm(raw_snow.get("resolution_notes"))
        or _norm(raw_snow.get("u_resolution_note"))
    )
    has_resolution_note = bool(resolution_note)

    closer = _norm(ticket.get("closed_by") or ticket.get("resolved_by") or ticket.get("implementer_id"))
    closer_comments = (
        _find_comments(comments, author=closer, keywords=_CLOSER_COMMENT_KEYWORDS)
        if closer
        else _find_comments(comments, keywords=_CLOSER_COMMENT_KEYWORDS)
    )
    has_closer_comment = bool(closer_comments)
    closer_outcome_comments = (
        _find_comments(
            comments,
            author=closer if closer else None,
            keywords=_CLOSURE_SUCCESS_KEYWORDS + _CLOSURE_ISSUE_KEYWORDS,
        )
    )
    has_closer_outcome_comment = bool(closer_outcome_comments)
    has_success_outcome = any(_contains_keyword(_norm(c.get("text")), _CLOSURE_SUCCESS_KEYWORDS) for c in closer_outcome_comments)
    has_issue_outcome = any(_contains_keyword(_norm(c.get("text")), _CLOSURE_ISSUE_KEYWORDS) for c in closer_outcome_comments)

    duplicate_markers = " ".join(
        [
            _norm(ticket.get("title")).lower(),
            _norm(ticket.get("description")).lower(),
            _norm(ticket.get("close_code")).lower(),
            _norm(raw_snow.get("close_code")).lower(),
            _norm(raw_snow.get("close_notes")).lower(),
            _norm(raw_snow.get("close_reason")).lower(),
        ]
    )
    is_duplicate_issue = "duplicate" in duplicate_markers
    duplicate_expl_comments = (
        _find_comments(comments, author=closer, keywords=_DUPLICATE_EXPLANATION_KEYWORDS)
        if closer
        else _find_comments(comments, keywords=_DUPLICATE_EXPLANATION_KEYWORDS)
    )
    has_duplicate_explanation = bool(duplicate_expl_comments)

    # LLM semantic overrides for writing style variability.
    has_doc_comment = has_doc_comment or bool(llm_eval.get("has_documentation_evidence"))
    has_resolution_note = has_resolution_note or bool(llm_eval.get("has_resolution_note_or_equivalent"))
    has_closer_comment = has_closer_comment or bool(llm_eval.get("has_closer_comment"))
    has_closer_outcome_comment = has_closer_outcome_comment or bool(llm_eval.get("has_closure_outcome_comment"))
    has_duplicate_explanation = has_duplicate_explanation or bool(llm_eval.get("has_duplicate_explanation"))
    closure_outcome = str(llm_eval.get("closure_outcome") or "").strip().lower()
    has_success_outcome = has_success_outcome or closure_outcome == "success"
    has_issue_outcome = has_issue_outcome or closure_outcome == "issue"

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
    if not has_closer_outcome_comment:
        results.append(
            ViolationResult(
                violation_type="MISSING_CLOSURE_OUTCOME_COMMENT",
                control_id=controls["MISSING_DOCUMENTATION"]["id"],
                severity=controls["MISSING_DOCUMENTATION"]["severity"],
                description=(
                    f"Ticket '{ticket.get('ticket_key')}' is {ticket.get('status')} but has no closure outcome "
                    + (f"comment from closer '{closer}'" if closer else "comment in trail")
                    + " indicating whether the incident was completed successfully or closed with an issue."
                ),
                metadata={"status": ticket.get("status"), "closer_id": closer or None, "comments_count": len(comments)},
            )
        )
    if has_success_outcome and not has_doc_link and not has_doc_comment and not has_resolution_note:
        results.append(
            ViolationResult(
                violation_type="MISSING_SUCCESS_CLOSURE_EVIDENCE",
                control_id=controls["MISSING_DOCUMENTATION"]["id"],
                severity=controls["MISSING_DOCUMENTATION"]["severity"],
                description=(
                    f"Ticket '{ticket.get('ticket_key')}' has a successful closure comment but lacks "
                    "resolution note/documented evidence."
                ),
                metadata={"status": ticket.get("status"), "closer_id": closer or None},
            )
        )
    if has_issue_outcome and not has_resolution_note and not has_duplicate_explanation:
        results.append(
            ViolationResult(
                violation_type="MISSING_ISSUE_CLOSURE_EXPLANATION",
                control_id=controls["MISSING_DOCUMENTATION"]["id"],
                severity=controls["MISSING_DOCUMENTATION"]["severity"],
                description=(
                    f"Ticket '{ticket.get('ticket_key')}' indicates issue-based closure, but no resolution note "
                    "or issue explanation comment was found."
                ),
                metadata={"status": ticket.get("status"), "closer_id": closer or None},
            )
        )
    if not has_resolution_note:
        results.append(
            ViolationResult(
                violation_type="MISSING_RESOLUTION_NOTE",
                control_id=controls["MISSING_DOCUMENTATION"]["id"],
                severity=controls["MISSING_DOCUMENTATION"]["severity"],
                description=(
                    f"Ticket '{ticket.get('ticket_key')}' is {ticket.get('status')} but ServiceNow "
                    "resolution note field is empty."
                ),
                metadata={"status": ticket.get("status"), "comments_count": len(comments)},
            )
        )
    if not has_resolution_note and not has_closer_comment:
        results.append(
            ViolationResult(
                violation_type="MISSING_CLOSER_COMMENT",
                control_id=controls["MISSING_DOCUMENTATION"]["id"],
                severity=controls["MISSING_DOCUMENTATION"]["severity"],
                description=(
                    f"Ticket '{ticket.get('ticket_key')}' is {ticket.get('status')} but has no closer comment "
                    + (f"from closer '{closer}'" if closer else "in comments")
                    + " (e.g., 'approval provided' / 'access provided')."
                ),
                metadata={"status": ticket.get("status"), "closer_id": closer or None, "comments_count": len(comments)},
            )
        )
    if is_duplicate_issue and not has_duplicate_explanation:
        results.append(
            ViolationResult(
                violation_type="MISSING_DUPLICATE_EXPLANATION_COMMENT",
                control_id=controls["MISSING_DOCUMENTATION"]["id"],
                severity=controls["MISSING_DOCUMENTATION"]["severity"],
                description=(
                    f"Ticket '{ticket.get('ticket_key')}' appears marked as duplicate, but no explanatory "
                    "duplicate/linked-ticket closure comment was found."
                ),
                metadata={"status": ticket.get("status"), "closer_id": closer or None, "comments_count": len(comments)},
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
    approved_lower = {str(s).strip().lower() for s in _software(config) if str(s).strip()}
    results: list[ViolationResult] = []
    if not _enabled(config, "UNAUTHORIZED_SOFTWARE"):
        return results

    for entry in (ticket.get("installation_log") or []):
        sw = entry.get("software", "")
        if not _is_approved_software(sw, approved_lower):
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

    comments = _normalize_comments(ticket)
    corpus = _all_ticket_text(ticket, comments)
    if _contains_keyword(corpus, _SOFTWARE_CONTEXT_KEYWORDS):
        for sw in sorted(_extract_software_candidates(corpus)):
            if _is_approved_software(sw, approved_lower):
                continue
            results.append(
                ViolationResult(
                    violation_type="UNAUTHORIZED_SOFTWARE_REQUEST",
                    control_id=controls["UNAUTHORIZED_SOFTWARE"]["id"],
                    severity=controls["UNAUTHORIZED_SOFTWARE"]["severity"],
                    description=(
                        f"Ticket '{ticket.get('ticket_key')}' requests or references unauthorized software/tool "
                        f"'{sw}' in description/comments."
                    ),
                    metadata={"software": sw},
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
    llm_eval = _llm_comment_result(ticket, config, comments)

    if is_closed:
        approval_comments_any = _find_comments(comments, keywords=_APPROVAL_KEYWORDS)
        approval_comments_by_approver = _find_comments(comments, author=approver, keywords=_APPROVAL_KEYWORDS) if approver else []
        approval_comments_by_requestor = _find_comments(comments, author=requestor, keywords=_APPROVAL_KEYWORDS) if requestor else []
        approval_comments_evidence = [
            c for c in approval_comments_any
            if _contains_keyword(
                _norm(c.get("text")),
                ("manager", "mgr", "lead", "approved by", "approval from", "screenshot", "mail", "email"),
            )
        ]

        has_approval_comment_any = bool(approval_comments_any)
        has_approval_comment_by_approver = bool(approval_comments_by_approver)
        has_approval_evidence_comment = bool(approval_comments_evidence)

        # LLM semantic overrides for approval interpretation.
        has_approval_comment_any = has_approval_comment_any or bool(llm_eval.get("has_approval_comment"))
        has_approval_evidence_comment = has_approval_evidence_comment or bool(llm_eval.get("has_approval_evidence"))

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

        if (
            _enabled(config, "MISSING_APPROVAL")
            and approver
            and not has_approval_comment_by_approver
            and not has_approval_evidence_comment
        ):
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

        explicit_self_approval = bool(
            requestor and _has_comment(
                comments,
                author=requestor,
                keywords=("i approve", "approved by me", "my approval", "self-approve", "self approve"),
            )
        )
        if (
            _enabled(config, "SELF_APPROVAL")
            and requestor
            and approver
            and _author_matches(approver, requestor)
            and (approval_comments_by_requestor or explicit_self_approval)
        ):
            results.append(
                ViolationResult(
                    violation_type="SELF_APPROVAL_COMMENT",
                    control_id=controls["SELF_APPROVAL"]["id"],
                    severity=controls["SELF_APPROVAL"]["severity"],
                    description=(
                        f"Potential self-approval by comment trail: requestor '{requestor}' added "
                        "approval-like comment(s). Approval must be recorded by a different approver."
                    ),
                    metadata={"requestor_id": requestor, "approver_id": approver or None},
                )
            )

        closed_ts = _parse_dt(ticket.get("closed_at"))
        if (
            _enabled(config, "MISSING_APPROVAL")
            and closed_ts
            and has_approval_comment_by_approver
            and all(
                (dt is None) or (dt > closed_ts)
                for dt in (_parse_dt(c.get("created_at")) for c in approval_comments_by_approver)
            )
        ):
            results.append(
                ViolationResult(
                    violation_type="LATE_APPROVAL_COMMENT",
                    control_id=controls["MISSING_APPROVAL"]["id"],
                    severity=controls["MISSING_APPROVAL"]["severity"],
                    description=(
                        f"Ticket '{ticket.get('ticket_key')}' has approval comment(s) from approver '{approver}', "
                        "but all of them were added after closure/resolution."
                    ),
                    metadata={"approver_id": approver, "closed_at": ticket.get("closed_at")},
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
    """Run enabled controls using LLM as the primary compliance decision engine."""
    controls = _controls(config)
    evaluator = _cfg_value(config, "TICKET_RULE_EVALUATOR") or _cfg_value(config, "COMMENT_RULE_EVALUATOR")
    approved_software = [str(x).strip() for x in (_software(config) or []) if str(x).strip()]
    authorized_approvers = [str(x).strip() for x in (_approvers(config) or []) if str(x).strip()]
    enabled_controls: list[dict[str, str]] = []
    for control_key, data in controls.items():
        if not _enabled(config, control_key):
            continue
        enabled_controls.append(
            {
                "control_key": control_key,
                "control_id": str(data.get("id") or control_key),
                "name": str(data.get("name") or control_key.replace("_", " ").title()),
                "severity": str(data.get("severity") or "Medium"),
                "description": str(data.get("description") or ""),
            }
        )

    comments = _normalize_comments(ticket)
    eval_result: dict[str, Any] = {}
    if evaluator and hasattr(evaluator, "assess_ticket_rules"):
        try:
            eval_result = evaluator.assess_ticket_rules(
                ticket=ticket,
                comments=comments,
                controls=enabled_controls,
                approved_software=approved_software,
                authorized_approvers=authorized_approvers,
            ) or {}
        except Exception:
            eval_result = {}

    checks = eval_result.get("checks") if isinstance(eval_result, dict) else None
    if not isinstance(checks, list):
        checks = []
    if not checks and enabled_controls:
        checks = [
            {
                "control_key": c["control_key"],
                "control_id": c["control_id"],
                "control_name": c["name"],
                "severity": c["severity"],
                "applicable": True,
                "passed": False,
                "reason": "LLM evaluation unavailable or invalid response.",
                "evidence": [],
            }
            for c in enabled_controls
        ]

    # Persist full check payload on the ticket object for DB persistence in compliance_engine.
    ticket["_llm_rule_assessment"] = {
        "control_domain": str(eval_result.get("control_domain") or "").strip() if isinstance(eval_result, dict) else "",
        "entities": eval_result.get("entities") if isinstance(eval_result, dict) and isinstance(eval_result.get("entities"), dict) else {},
        "final_status": str(eval_result.get("final_status") or "").strip() if isinstance(eval_result, dict) else "",
        "summary": str(eval_result.get("summary") or "").strip() if isinstance(eval_result, dict) else "",
        "missing_evidence": eval_result.get("missing_evidence") if isinstance(eval_result, dict) and isinstance(eval_result.get("missing_evidence"), list) else [],
        "checks": checks,
    }

    violations: list[ViolationResult] = []
    for check in checks:
        if not isinstance(check, dict):
            continue
        applicable = bool(check.get("applicable", True))
        passed = bool(check.get("passed", False))
        if not applicable or passed:
            continue

        control_id = str(check.get("control_id") or "").strip()
        control_key = str(check.get("control_key") or "").strip()
        severity = str(check.get("severity") or "Medium").strip() or "Medium"
        reason = str(check.get("reason") or "").strip() or "Control failed per LLM assessment."
        evidence = check.get("evidence")
        if not isinstance(evidence, list):
            evidence = []
        evidence = [str(x).strip() for x in evidence if str(x).strip()]

        violations.append(
            ViolationResult(
                violation_type=f"{control_key}_FAILED" if control_key else "CONTROL_FAILED",
                control_id=control_id or "ITGC-UNKNOWN",
                severity=severity,
                description=(
                    f"LLM rule assessment failed for ticket '{ticket.get('ticket_key', 'N/A')}' "
                    f"on control '{control_id or control_key}'. Reason: {reason}"
                ),
                metadata={
                    "control_key": control_key or None,
                    "reason": reason,
                    "evidence": evidence,
                    "llm_based": True,
                },
            )
        )
    return violations
