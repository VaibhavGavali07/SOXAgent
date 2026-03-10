from __future__ import annotations

import json
import re
import uuid
from typing import Any

from backend.llm.prompts import build_ticket_prompt, prompt_hash
from backend.storage.models import LLMEvaluationModel


# ---------------------------------------------------------------------------
# Rule catalog  (4 active controls)
# tuple: (rule_id, rule_name, severity, control_mapping)
# ---------------------------------------------------------------------------

RULE_CATALOG = [
    ("ITGC-AC-01", "Self-Approval Prevention",          "HIGH",   ["SOX ITGC AC-1"]),
    ("ITGC-WF-01", "Missing Closure Documentation",     "MEDIUM", ["SOX ITGC OP-5"]),
    ("ITGC-SW-01", "Unauthorized Software Installation","MEDIUM", ["SOX ITGC CM-1"]),
    ("ITGC-AC-04", "Missing Approval",                  "HIGH",   ["SOX ITGC AC-4"]),
]

_RULE_KEY_MAP = {
    "ITGC-AC-01": "SELF_APPROVAL",
    "ITGC-WF-01": "MISSING_DOCUMENTATION",
    "ITGC-SW-01": "UNAUTHORIZED_SOFTWARE",
    "ITGC-AC-04": "MISSING_APPROVAL",
}


class LLMEvaluator:
    def __init__(self, chat_provider, compliance_config: dict[str, Any] | None = None) -> None:
        self.chat_provider = chat_provider
        self.compliance_config = compliance_config or {}

    def evaluate_ticket(
        self,
        ticket: dict[str, Any],
        retrieval_context: dict[str, Any] | None = None,
        run_id: str | None = None,
    ) -> tuple[LLMEvaluationModel, str, str]:
        resolved_run_id = run_id or str(uuid.uuid4())
        prompt_text = build_ticket_prompt(ticket, retrieval_context, self.compliance_config)

        if self.chat_provider.provider_name == "mock":
            raise ValueError(
                "LLM provider is not configured. Please configure an LLM provider "
                "(OpenAI, Azure OpenAI, or Gemini) in the Connections page to run compliance analysis."
            )

        raw_response = self.chat_provider.complete_json(prompt_text)
        payload = self._parse_llm_response(raw_response, ticket["ticket_id"], resolved_run_id)

        validated = LLMEvaluationModel.model_validate(payload)
        return validated, prompt_text, prompt_hash(prompt_text)

    # ------------------------------------------------------------------ LLM response parsing

    def _parse_llm_response(self, raw: str, ticket_id: str, run_id: str) -> dict[str, Any]:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
            data = json.loads(match.group(0)) if match else {}

        if "checks" in data:
            return self._parse_new_schema(data, ticket_id, run_id)
        return self._parse_legacy_schema(data, ticket_id, run_id)

    def _parse_new_schema(self, data: dict[str, Any], ticket_id: str, run_id: str) -> dict[str, Any]:
        """Convert the new audit schema → LLMEvaluationModel-compatible dict."""
        lookup = {item[0]: item for item in RULE_CATALOG}
        final_status = (data.get("final_status") or "COMPLIANT").upper()
        overall = "non_compliant" if "NON_COMPLIANT" in final_status else "compliant"

        checks = data.get("checks") or []
        seen_ids: set[str] = set()
        rules: list[dict[str, Any]] = []

        for check in checks:
            control_id = check.get("control_id") or ""
            if control_id not in lookup:
                continue
            seen_ids.add(control_id)
            _, rule_name, severity, controls = lookup[control_id]

            applicable = bool(check.get("applicable", True))
            passed = bool(check.get("passed", True))
            reason = check.get("reason") or ""

            if not applicable:
                status = "PASS"
                why = f"Not applicable — {reason}" if reason else "Not applicable for this ticket type."
            elif passed:
                status = "PASS"
                why = reason or "Control requirements met."
            else:
                status = "FAIL"
                why = reason or "Control requirements not met."

            evidence_items = self._build_evidence_items(check.get("evidence") or [], status, control_id, why)

            rules.append({
                "rule_id": control_id,
                "rule_name": rule_name,
                "severity": severity,
                "status": status,
                "confidence": 0.90 if status == "FAIL" else 0.85,
                "why": why,
                "evidence": evidence_items,
                "recommended_action": "Review and remediate the identified control gap.",
                "control_mapping": controls,
            })

        # Ensure every catalog rule is present
        for rule_id, rule_name, severity, controls in RULE_CATALOG:
            if rule_id not in seen_ids:
                rules.append(self._needs_review_rule(rule_id, rule_name, severity, controls, ticket_id))

        return {
            "run_id": run_id,
            "ticket_id": ticket_id,
            "overall_assessment": overall,
            "rules": rules,
            "red_flags": data.get("missing_evidence") or [],
            "assumptions": [],
            "missing_info": data.get("missing_evidence") or [],
            "control_domain": data.get("control_domain"),
            "entities": data.get("entities"),
            "missing_evidence": data.get("missing_evidence") or [],
        }

    def _parse_legacy_schema(self, data: dict[str, Any], ticket_id: str, run_id: str) -> dict[str, Any]:
        """Fallback parser for old 8-rule schema or malformed responses."""
        lookup = {item[0]: item for item in RULE_CATALOG}
        data.setdefault("run_id", run_id)
        data.setdefault("ticket_id", ticket_id)
        data.setdefault("overall_assessment", "needs_review")
        data.setdefault("rules", [])
        data.setdefault("red_flags", [])
        data.setdefault("assumptions", [])
        data.setdefault("missing_info", [])

        repaired: list[dict[str, Any]] = []
        for rule_id, rule_name, severity, controls in RULE_CATALOG:
            candidate = next((r for r in data["rules"] if r.get("rule_id") == rule_id), None)
            if not candidate:
                candidate = self._needs_review_rule(rule_id, rule_name, severity, controls, ticket_id)
            else:
                candidate["rule_name"] = candidate.get("rule_name") or rule_name
                candidate["severity"] = (candidate.get("severity") or severity).upper()
                candidate["status"] = (candidate.get("status") or "NEEDS_REVIEW").upper()
                candidate["confidence"] = float(candidate.get("confidence", 0.3))
                candidate["evidence"] = self._build_evidence_items(
                    candidate.get("evidence") or [], candidate["status"], rule_id,
                    candidate.get("why") or ticket_id
                )
                candidate.setdefault("control_mapping", controls)
                candidate.setdefault("recommended_action", "Review the ticket manually.")
            repaired.append(candidate)

        data["rules"] = repaired
        return data

    # ------------------------------------------------------------------ helpers

    def _needs_review_rule(
        self, rule_id: str, rule_name: str, severity: str, controls: list[str], ticket_id: str
    ) -> dict[str, Any]:
        return {
            "rule_id": rule_id,
            "rule_name": rule_name,
            "severity": severity,
            "status": "NEEDS_REVIEW",
            "confidence": 0.3,
            "why": "LLM response did not include this rule — manual review required.",
            "evidence": [{"type": "field", "ref_id": f"field:{rule_id}", "timestamp": None, "snippet": ticket_id}],
            "recommended_action": "Re-run analysis or review manually.",
            "control_mapping": controls,
        }

    @staticmethod
    def _build_evidence_items(
        raw_evidence: list, status: str, rule_id: str, fallback_why: str
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for i, ev in enumerate(raw_evidence):
            if isinstance(ev, str) and ev.strip():
                items.append({"type": "field", "ref_id": f"ev_{i}", "timestamp": None, "snippet": ev[:200]})
            elif isinstance(ev, dict):
                items.append({
                    "type": ev.get("type", "field"),
                    "ref_id": ev.get("ref_id", f"ev_{i}"),
                    "timestamp": ev.get("timestamp"),
                    "snippet": str(ev.get("snippet", ""))[:200],
                })
        if status in {"FAIL", "NEEDS_REVIEW"} and not items:
            items = [{"type": "field", "ref_id": f"field:{rule_id}", "timestamp": None, "snippet": fallback_why[:200]}]
        return items

