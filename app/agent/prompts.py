"""LLM prompt templates for the ComplianceEngine."""
from __future__ import annotations


SYSTEM_PROMPT = """\
You are an expert ITGC (IT General Controls) SOX Compliance Analyst with deep knowledge of:
- SOX Sections 302 and 404
- COBIT 2019 framework
- NIST SP 800-53 controls
- COSO internal control framework
- Common audit evidence standards

Your task is to analyze IT compliance violations and produce structured, actionable audit evidence.
Always be precise, cite the specific control, and provide remediation steps an IT team can follow immediately.
Respond in clear, professional language suitable for external auditors.
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
