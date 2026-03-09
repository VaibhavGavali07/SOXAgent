"""LLM prompt templates for the ComplianceEngine."""
from __future__ import annotations


SYSTEM_PROMPT = """\
You are a Senior IT Compliance Auditor specializing in SOX Section 404 controls.
Operate like a forensic auditor, not a general assistant.
Use precise control language and provide defensible audit-ready reasoning.
"""


def _format_installation_log(ticket: dict) -> str:
    log = ticket.get("installation_log")
    if not log:
        return ""
    lines = ["- **System / Installation Log**:"]
    for entry in log:
        lines.append(
            f"  - `{entry.get('software', 'N/A')}` v{entry.get('version', 'N/A')}"
            f" (user: {entry.get('user', 'N/A')})"
        )
    return "\n".join(lines) + "\n"


def build_violation_analysis_prompt(violation: dict, ticket: dict) -> str:
    return f"""\
Analyze the following ITGC compliance violation and produce a structured audit evidence report.

## Violation Details
- **UUID**: {violation['id']}
- **Control ID**: {violation['control_id']}
- **Violation Type**: {violation['violation_type']}
- **Severity**: {violation['severity']}
- **Detected**: {violation['detected_at']}
- **Description**: {violation['description']}

## Ticket Data
- **Ticket Key**: {ticket.get('ticket_key', 'N/A')}
- **Source System**: {ticket.get('source', 'N/A')}
- **Title**: {ticket.get('title', 'N/A')}
- **Status**: {ticket.get('status', 'N/A')}
- **Type**: {ticket.get('ticket_type', 'N/A')}
- **Priority**: {ticket.get('priority', 'N/A')}
- **Requestor**: {ticket.get('requestor_id', 'N/A')}
- **Approver**: {ticket.get('approver_id', 'N/A')}
- **Implementer**: {ticket.get('implementer_id', 'N/A')}
- **Documentation Link**: {ticket.get('documentation_link') or 'MISSING'}
- **Approval Timestamp**: {ticket.get('approval_timestamp') or 'N/A'}
- **Closed At**: {ticket.get('closed_at') or 'N/A'}
{_format_installation_log(ticket)}
## Required Output

Provide your analysis in the following sections:

### 1. Risk Assessment
Describe the business and compliance risk posed by this violation, including potential audit impact.

### 2. Root Cause Analysis
Identify the likely root cause (process gap, missing control, system misconfiguration, etc.).

### 3. Immediate Remediation (0–48 hours)
List 3–5 concrete, actionable steps the IT team must take immediately.

### 4. Long-Term Preventive Controls
Recommend 2–3 systemic controls or process changes to prevent recurrence.

### 5. Audit Evidence Summary
Write a one-paragraph summary suitable for inclusion in an external audit report.
"""


def build_batch_summary_prompt(violations: list[dict]) -> str:
    high = sum(1 for v in violations if v["severity"] == "High")
    medium = sum(1 for v in violations if v["severity"] == "Medium")
    low = sum(1 for v in violations if v["severity"] == "Low")
    types = list({v["violation_type"] for v in violations})

    return f"""\
Provide a concise executive summary of an ITGC SOX compliance scan that detected the following:

- **Total Violations**: {len(violations)}
- **High Severity**: {high}
- **Medium Severity**: {medium}
- **Low Severity**: {low}
- **Violation Types**: {', '.join(types)}

Write 2–3 sentences suitable for a CISO or CFO briefing, emphasizing the most critical risks
and whether the current control environment is adequate for SOX certification.
"""


def build_comment_rule_validation_prompt(ticket: dict, comments: list[dict[str, str]]) -> str:
    lines: list[str] = []
    for idx, c in enumerate(comments[:80], start=1):
        author = str(c.get("author") or "unknown")
        text = str(c.get("text") or "")
        ts = str(c.get("created_at") or "")
        lines.append(f"{idx}. [{ts}] {author}: {text}")

    comment_block = "\n".join(lines) if lines else "No comments."

    return f"""\
Evaluate this ticket comment trail semantically (not keyword-only) and determine whether control expectations are met.

Ticket metadata:
- ticket_key: {ticket.get('ticket_key', '')}
- status: {ticket.get('status', '')}
- requestor_id: {ticket.get('requestor_id', '')}
- approver_id: {ticket.get('approver_id', '')}
- closer/implementer: {ticket.get('closed_by') or ticket.get('resolved_by') or ticket.get('implementer_id') or ''}
- resolution_note: {ticket.get('resolution_note') or (ticket.get('_raw_snow') or {{}}).get('resolution_note') or ''}

Comment trail:
{comment_block}

Return strict JSON with these keys only:
{{
  "has_approval_comment": boolean,
  "has_approval_evidence": boolean,
  "approval_by_requester_only": boolean,
  "has_documentation_evidence": boolean,
  "has_resolution_note_or_equivalent": boolean,
  "has_closer_comment": boolean,
  "has_closure_outcome_comment": boolean,
  "closure_outcome": "success" | "issue" | "unknown",
  "has_duplicate_explanation": boolean
}}
"""


def build_ticket_rule_assessment_prompt(
    *,
    ticket: dict,
    comments: list[dict[str, str]],
    controls: list[dict[str, str]],
    approved_software: list[str],
    authorized_approvers: list[str],
) -> str:
    comment_lines: list[str] = []
    for idx, c in enumerate(comments[:120], start=1):
        ts = str(c.get("created_at") or "")
        author = str(c.get("author") or "unknown")
        text = str(c.get("text") or "")
        comment_lines.append(f"{idx}. [{ts}] {author}: {text}")
    comment_block = "\n".join(comment_lines) if comment_lines else "No comments available."

    controls_block = "\n".join(
        [
            (
                f"- key={c.get('control_key')} | id={c.get('control_id')} | "
                f"name={c.get('name')} | severity={c.get('severity')} | description={c.get('description')}"
            )
            for c in controls
        ]
    )

    approved_block = ", ".join(approved_software[:120]) if approved_software else "None configured"
    approver_block = ", ".join(authorized_approvers[:120]) if authorized_approvers else "None configured"

    return f"""\
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
- Authorization:
  - Require clear approval evidence from designated authority.
  - Fail if approval is missing or is self-approval by requester.
- Validation:
  - Closure must explicitly confirm the requested action outcome.
  - Weak/vague closure (for example: "Closing ticket", "Task finished") is non-compliant.
- Evidence:
  - For software install/access requests, verify alignment with Approved Software List.
  - If software evidence/log mention is expected but absent, mark missing evidence.

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

Ticket metadata:
- ticket_key: {ticket.get('ticket_key', '')}
- source: {ticket.get('source', '')}
- status: {ticket.get('status', '')}
- title: {ticket.get('title', '')}
- description: {ticket.get('description', '')}
- summary: {ticket.get('summary', '')}
- requestor_id: {ticket.get('requestor_id', '')}
- approver_id: {ticket.get('approver_id', '')}
- implementer_id: {ticket.get('implementer_id', '')}
- closed_by/resolved_by: {ticket.get('closed_by') or ticket.get('resolved_by') or ''}
- documentation_link: {ticket.get('documentation_link', '')}
- resolution_note: {ticket.get('resolution_note') or (ticket.get('_raw_snow') or {{}}).get('resolution_note') or ''}
- close_notes: {(ticket.get('_raw_snow') or {{}}).get('close_notes') or ticket.get('close_notes') or ''}

Authorized approvers:
{approver_block}

Approved software list:
{approved_block}

Controls to evaluate:
{controls_block}

Comment trail:
{comment_block}

Return ONLY strict JSON with this exact schema:
{{
  "ticket_key": "string",
  "control_domain": "User Access Management | System Change Control | Emergency Access | Other",
  "entities": {{
    "requester_or_caller": "string",
    "approver": "string",
    "fulfiller": "string"
  }},
  "final_status": "COMPLIANT | NON_COMPLIANT",
  "summary": "short forensic conclusion",
  "missing_evidence": ["short gap 1", "short gap 2"],
  "checks": [
    {{
      "control_key": "string",
      "control_id": "string",
      "applicable": true,
      "passed": false,
      "reason": "short explanation",
      "evidence": ["short evidence text 1", "short evidence text 2"]
    }}
  ]
}}
"""
