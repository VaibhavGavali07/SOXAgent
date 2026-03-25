"""LLM prompt construction for SOX ITGC compliance analysis.

Key design decisions
--------------------
1. **Prompt ordering for OpenAI prefix caching**
   Static content (instructions, controls, schema, software list) is placed
   BEFORE dynamic content (ticket metadata, comments, retrieved context).
   OpenAI caches prompt prefixes ≥ 1 024 tokens at 50 % cost — keeping the
   static prefix identical across all tickets maximises cache hits.

2. **Retrieval context is now actually used**
   `build_ticket_prompt` previously accepted `retrieval_context` but silently
   discarded it.  It now injects:
     - Policy snippets retrieved by PolicyRAG (relevant SOX clauses)
     - Similar past violations as few-shot examples (improves consistency)

3. **Controls stay fixed (all 4 evaluated every time)**
   This is correct by design — the LLM must at minimum consider each control
   and mark inapplicable ones as such.
"""
from __future__ import annotations

import hashlib
from typing import Any

# ---------------------------------------------------------------------------
# Default approved-software list (override via "compliance" config in DB)
# ---------------------------------------------------------------------------

DEFAULT_APPROVED_SOFTWARE: list[str] = [
    "Microsoft Office 365", "Zoom", "Slack", "Google Chrome", "Visual Studio Code",
    "Python 3.11", "Python 3.12", "Node.js LTS", "Docker Desktop", "Git", "Postman",
    "Confluence", "Jira Software", "ServiceNow Agent", "McAfee Endpoint Security",
    "CrowdStrike Falcon", "Okta Verify", "LastPass Enterprise", "Microsoft Teams",
    "Windows Defender", "7-Zip", "Adobe Acrobat Reader", "Notepad++",
]

# ---------------------------------------------------------------------------
# Static sections  (placed first so OpenAI prefix cache covers them)
# ---------------------------------------------------------------------------

_CONTROLS_TEXT = """\
- key=SELF_APPROVAL | id=ITGC-AC-01 | name=Self-Approval Prevention | severity=High | description=Requestor and approval provider must be different individuals.
- key=MISSING_DOCUMENTATION | id=ITGC-WF-01 | name=Missing Closure Documentation | severity=Medium | description=Closed tickets must include a meaningful closer resolution comment or equivalent closure evidence.
- key=UNAUTHORIZED_SOFTWARE | id=ITGC-SW-01 | name=Unauthorized Software Installation | severity=Medium | description=Check the Approved Software List only for tickets related to software installation or software/application access.
- key=MISSING_APPROVAL | id=ITGC-AC-04 | name=Missing Approval | severity=High | description=Closed/resolved tickets must show approval evidence from an approver comment or alternate proof such as screenshot/email evidence documented in the ticket."""

_RETURN_SCHEMA = """\
{
  "ticket_key": "string",
  "control_domain": "User Access Management | System Change Control | Emergency Access | Other",
  "entities": {
    "requester_or_caller": "string",
    "approver": "string",
    "fulfiller": "string"
  },
  "final_status": "COMPLIANT | NON_COMPLIANT",
  "summary": "short forensic conclusion",
  "missing_evidence": ["short gap 1", "short gap 2"],
  "checks": [
    {
      "control_key": "string",
      "control_id": "string",
      "applicable": true,
      "passed": false,
      "reason": "short explanation",
      "evidence": ["short evidence text 1", "short evidence text 2"]
    }
  ]
}"""

_SYSTEM_INSTRUCTIONS = """\
Role:
You are a Senior IT Compliance Auditor specializing in SOX Section 404 controls.
Your task is to audit this ITSM ticket for mandatory evidence quality.

Workflow (perform in this order):
1) Classification:
- Determine control_domain from ticket title/description/comments:
  - User Access Management
  - System Change Control
  - Emergency Access
  - Other

2) Entity identification:
- requester_or_caller: person asking for the change
- approver: person granting authority (must not be requester)
- fulfiller: person who executed/closed the work

3) Rule mapping:
Evaluate these top 4 controls first and treat the rest as disabled/background only:
- Rule 1: Self Approval
  - The requester of the ticket and the person providing approval in comments/evidence must not be the same person.
  - Fail if the requester approves their own request directly or indirectly.
- Rule 2: Missing Closure Documentation
  - Closed/resolved tickets must contain a meaningful closer comment or equivalent closure evidence, not just a generic closure note.
  - Accept closure documentation when it clearly states what was done and the outcome, similar to examples such as hardware replacement completed, password reset completed, software deployed and verified, access granted after approval, duplicate ticket reference, or no-response closure explanation.
  - Weak/vague closure like "closing ticket" or "task finished" is non-compliant.
- Rule 3: Unauthorized Software Installation
  - Check the Approved Software List only if the ticket is related to software installation or software/application access.
  - If the ticket is unrelated to software installation or software/application access, mark this control not applicable.
- Rule 4: Missing Approval
  - Require approval evidence on the ticket before closure.
  - Approval may be shown by a direct approver comment, an approval copied into comments, or evidence referenced by the implementer such as screenshot/email proof from the approver.
  - Fail only when no credible approval evidence exists.

All other controls:
- Keep them listed in output only as disabled/non-primary controls.
- Do not let them override the decision on the top 4 rules.

4) Gap analysis:
- List missing_evidence items such as:
  - missing approval timestamp
  - no explicit completion confirmation
  - segregation of duties conflict
  - no approved software evidence

Decision quality rules:
- Use semantic reasoning, not literal keyword matching.
- Be robust to typos and style variation.
- Decide applicability per control:
  - If not applicable: applicable=false and passed=true.
  - If applicable: passed=true/false with concise, specific reason.
- Output must be one valid JSON object only.
- Do not wrap JSON in markdown fences.
- Do not add commentary before or after JSON."""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _format_comment_trail(comments: list[dict[str, Any]]) -> str:
    if not comments:
        return "No comments found."
    lines = []
    for i, comment in enumerate(comments, start=1):
        author = comment.get("author", {}).get("name", "Unknown")
        timestamp = comment.get("timestamp", "")
        body = (comment.get("body") or "").strip()
        lines.append(f"{i}. [{timestamp}] {author}: {body}")
    return "\n".join(lines)


def _format_list(items: list[str]) -> str:
    return ", ".join(items) if items else "Not configured"


def _format_policy_snippets(snippets: list[dict[str, str]]) -> str:
    if not snippets:
        return ""
    lines = []
    for s in snippets:
        lines.append(f"- [{s.get('control_id', '')}] {s.get('title', '')}: {s.get('snippet', '')}")
    return "Relevant SOX policy references:\n" + "\n".join(lines)


def _format_screenshot_approvals(approvals: list[dict[str, Any]]) -> str:
    """Format vision-extracted screenshot approval data for LLM context.

    This section appears before ticket metadata so the LLM can reference it
    when evaluating ITGC-AC-04 (Missing Approval) and ITGC-AC-01 (Self-Approval).
    """
    if not approvals:
        return ""
    lines = ["Screenshot evidence found in ticket attachments (extracted by vision AI):"]
    for apv in approvals:
        filename = apv.get("filename", "screenshot")
        approver = apv.get("approver") or "unknown"
        approval_text = apv.get("approval_text") or ""
        timestamp = apv.get("timestamp") or ""
        status = apv.get("approval_status", "unknown")
        confidence = apv.get("confidence", 0.0)
        summary = apv.get("summary", "")
        line = f"- [{filename}] Approver: {approver} | Status: {status} | Confidence: {confidence:.0%}"
        if timestamp:
            line += f" | Time: {timestamp}"
        if approval_text:
            line += f'\n  Approval text: "{approval_text}"'
        if summary:
            line += f"\n  Summary: {summary}"
        lines.append(line)
    lines.append(
        "Use the above screenshot evidence when evaluating ITGC-AC-04 (Missing Approval) "
        "and ITGC-AC-01 (Self-Approval Prevention)."
    )
    return "\n".join(lines)


def _format_similar_violations(violations: list[dict[str, Any]]) -> str:
    """Format past similar violations as few-shot examples.

    These help the LLM produce consistent verdicts by showing how comparable
    tickets were handled in the past.
    """
    if not violations:
        return ""
    lines = ["Precedents from similar past tickets (use as guidance, not rules):"]
    for v in violations[:3]:
        ticket_id = v.get("ticket_id") or v.get("entity_id") or v.get("id", "unknown")
        sim = v.get("similarity", 0)
        failed = v.get("failed_rules", "")
        preview = v.get("preview") or v.get("text", "")[:150]
        if failed:
            lines.append(f"- {ticket_id} (similarity {sim:.2f}): {preview!r} → FAILed: {failed}")
        else:
            lines.append(f"- {ticket_id} (similarity {sim:.2f}): {preview!r}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------

def build_ticket_prompt(
    ticket: dict[str, Any],
    retrieval_context: dict[str, Any] | None = None,
    compliance_config: dict[str, Any] | None = None,
    extra_rules: list[dict[str, Any]] | None = None,
) -> str:
    compliance_config = compliance_config or {}
    retrieval_context = retrieval_context or {}
    approved_software = compliance_config.get("approved_software") or DEFAULT_APPROVED_SOFTWARE

    requestor = ticket.get("requestor") or {}
    approvals = ticket.get("approvals") or []
    implementers = ticket.get("implementers") or []
    comments = ticket.get("comments") or []
    custom = ticket.get("custom_fields") or {}

    requestor_name = requestor.get("name") or "Unknown"
    approver_name = approvals[0]["approver"]["name"] if approvals else "Not Yet Requested"
    implementer_name = implementers[0]["name"] if implementers else ""
    resolved_by = custom.get("resolved_by") or custom.get("closed_by") or ""
    close_notes = custom.get("close_notes") or ""
    resolution_note = custom.get("resolution_note") or ticket.get("status") or ""
    doc_link = custom.get("documentation_link") or ticket.get("status") or ""

    # Build controls text — fixed 4 + any active custom rules
    extra_controls = ""
    if extra_rules:
        for rule in extra_rules:
            if not rule.get("active", True):
                continue
            rid = rule.get("rule_id", "")
            rname = rule.get("rule_name", rid)
            rsev = rule.get("severity", "MEDIUM")
            rdesc = rule.get("description") or "Evaluate this control for the given ticket."
            extra_controls += f"\n- key={rid} | id={rid} | name={rname} | severity={rsev} | description={rdesc}"
    controls_text = _CONTROLS_TEXT + extra_controls if extra_controls else _CONTROLS_TEXT

    # ---------------------------------------------------------------
    # Section assembly — STATIC FIRST (maximises OpenAI prefix cache)
    # ---------------------------------------------------------------

    # 1. Static: system instructions (rarely changes)
    # 2. Static: controls definition (changes only when custom rules added)
    # 3. Static: return schema (never changes)
    # 4. Semi-static: approved software list (changes occasionally)
    # 5. Dynamic: retrieved policy context (varies per ticket)
    # 6. Dynamic: few-shot similar violations (varies per ticket)
    # 7. Dynamic: ticket metadata (unique per ticket)
    # 8. Dynamic: comment trail (unique per ticket)

    sections: list[str] = [
        _SYSTEM_INSTRUCTIONS,
        f"Controls to evaluate:\n{controls_text}",
        f"Return ONLY strict JSON with this exact schema:\n{_RETURN_SCHEMA}",
        f"Approved software list:\n{_format_list(approved_software)}",
    ]

    # Retrieved policy snippets (from PolicyRAG)
    policy_snippets = retrieval_context.get("policy_snippets") or []
    if policy_snippets:
        policy_block = _format_policy_snippets(policy_snippets)
        if policy_block:
            sections.append(policy_block)

    # Few-shot similar violations (from ChromaDB)
    similar_violations = retrieval_context.get("similar_violations") or []
    if similar_violations:
        violations_block = _format_similar_violations(similar_violations)
        if violations_block:
            sections.append(violations_block)

    # Screenshot approval evidence (vision AI extraction)
    screenshot_approvals = retrieval_context.get("screenshot_approvals") or []
    if screenshot_approvals:
        screenshot_block = _format_screenshot_approvals(screenshot_approvals)
        if screenshot_block:
            sections.append(screenshot_block)

    # Ticket metadata
    sections.append(
        f"Ticket metadata:\n"
        f"- ticket_key: {ticket.get('ticket_id', '')}\n"
        f"- source: ServiceNow\n"
        f"- status: {ticket.get('status', '')}\n"
        f"- title: {ticket.get('summary', '')}\n"
        f"- description: {ticket.get('description', '')}\n"
        f"- summary: {ticket.get('summary', '')}\n"
        f"- requestor_id: {requestor_name}\n"
        f"- approver_id: {approver_name}\n"
        f"- implementer_id: {implementer_name}\n"
        f"- closed_by/resolved_by: {resolved_by}\n"
        f"- documentation_link: {doc_link}\n"
        f"- resolution_note: {resolution_note}\n"
        f"- close_notes: {close_notes}"
    )

    # Comment trail
    sections.append(f"Comment trail:\n{_format_comment_trail(comments)}")

    return "\n\n".join(sections)


def prompt_hash(prompt_text: str) -> str:
    return hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()
