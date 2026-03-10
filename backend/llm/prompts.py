from __future__ import annotations

import hashlib
from typing import Any

# ---------------------------------------------------------------------------
# Default compliance reference data (override via "compliance" config in DB)
# ---------------------------------------------------------------------------

DEFAULT_APPROVED_SOFTWARE: list[str] = [
    "Microsoft Office 365", "Zoom", "Slack", "Google Chrome", "Visual Studio Code",
    "Python 3.11", "Python 3.12", "Node.js LTS", "Docker Desktop", "Git", "Postman",
    "Confluence", "Jira Software", "ServiceNow Agent", "McAfee Endpoint Security",
    "CrowdStrike Falcon", "Okta Verify", "LastPass Enterprise", "Microsoft Teams",
    "Windows Defender", "7-Zip", "Adobe Acrobat Reader", "Notepad++",
]

# Controls injected into every prompt
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
    if not items:
        return "Not configured"
    return ", ".join(items)


def build_ticket_prompt(
    ticket: dict[str, Any],
    retrieval_context: dict[str, Any] | None = None,
    compliance_config: dict[str, Any] | None = None,
) -> str:
    compliance_config = compliance_config or {}
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

    metadata_block = f"""\
Ticket metadata:
- ticket_key: {ticket.get("ticket_id", "")}
- source: ServiceNow
- status: {ticket.get("status", "")}
- title: {ticket.get("summary", "")}
- description: {ticket.get("description", "")}
- summary: {ticket.get("summary", "")}
- requestor_id: {requestor_name}
- approver_id: {approver_name}
- implementer_id: {implementer_name}
- closed_by/resolved_by: {resolved_by}
- documentation_link: {doc_link}
- resolution_note: {resolution_note}
- close_notes: {close_notes}"""

    software_block = f"Approved software list:\n{_format_list(approved_software)}"
    controls_block = f"Controls to evaluate:\n{_CONTROLS_TEXT}"
    comments_block = f"Comment trail:\n{_format_comment_trail(comments)}"
    schema_block = f"Return ONLY strict JSON with this exact schema:\n{_RETURN_SCHEMA}"

    sections = [
        _SYSTEM_INSTRUCTIONS,
        metadata_block,
        software_block,
        controls_block,
        comments_block,
        schema_block,
    ]
    return "\n\n".join(sections)


def prompt_hash(prompt_text: str) -> str:
    return hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()
