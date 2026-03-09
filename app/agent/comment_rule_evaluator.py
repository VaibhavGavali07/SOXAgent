"""LLM-based semantic evaluator for ticket comment trails."""
from __future__ import annotations

import json
from typing import Any

from app.agent.llm_client import LLMClient
from app.agent.prompts import (
    build_comment_rule_validation_prompt,
    build_ticket_rule_assessment_prompt,
)


class CommentRuleEvaluator:
    """Uses the configured LLM to semantically evaluate compliance comment rules."""

    def __init__(self, llm: LLMClient):
        self.llm = llm

    def evaluate(self, ticket: dict[str, Any], comments: list[dict[str, str]]) -> dict[str, Any]:
        if not self.llm or not self.llm.is_available():
            return {}

        prompt = build_comment_rule_validation_prompt(ticket=ticket, comments=comments)
        raw = self.llm.analyze(
            system=(
                "You are a strict ITSM/SOX comment-trail validator. "
                "Return only valid JSON with no prose."
            ),
            user=prompt,
            max_tokens=700,
        )
        return self._parse_json(raw)

    def assess_ticket_rules(
        self,
        *,
        ticket: dict[str, Any],
        comments: list[dict[str, str]],
        controls: list[dict[str, str]],
        approved_software: list[str],
        authorized_approvers: list[str],
    ) -> dict[str, Any]:
        if not self.llm or not self.llm.is_available():
            return {}

        prompt = build_ticket_rule_assessment_prompt(
            ticket=ticket,
            comments=comments,
            controls=controls,
            approved_software=approved_software,
            authorized_approvers=authorized_approvers,
        )
        raw = self.llm.analyze(
            system=(
                "You are a strict ITGC/SOX rule assessor. "
                "Return only valid JSON following the requested schema."
            ),
            user=prompt,
            max_tokens=2200,
        )
        data = self._parse_json(raw)
        if not data:
            return {}
        return self._normalize_assessment_payload(data, controls)

    @staticmethod
    def _parse_json(raw: str) -> dict[str, Any]:
        if not raw:
            return {}
        text = str(raw).strip()
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return {}
        try:
            data = json.loads(text[start : end + 1])
        except Exception:
            return {}
        if not isinstance(data, dict):
            return {}
        return data

    @staticmethod
    def _normalize_assessment_payload(payload: dict[str, Any], controls: list[dict[str, str]]) -> dict[str, Any]:
        checks = payload.get("checks")
        if not isinstance(checks, list):
            checks = []

        control_map = {
            str(c.get("control_key") or "").strip(): c
            for c in controls
            if str(c.get("control_key") or "").strip()
        }
        normalized_checks: list[dict[str, Any]] = []
        seen: set[str] = set()

        for item in checks:
            if not isinstance(item, dict):
                continue
            key = str(item.get("control_key") or "").strip()
            if not key or key in seen or key not in control_map:
                continue
            meta = control_map[key]
            applicable = bool(item.get("applicable", True))
            passed = bool(item.get("passed", False))
            if not applicable:
                passed = True

            evidence = item.get("evidence")
            if not isinstance(evidence, list):
                evidence = []
            evidence = [str(x).strip() for x in evidence if str(x).strip()][:6]

            normalized_checks.append(
                {
                    "control_key": key,
                    "control_id": str(item.get("control_id") or meta.get("control_id") or "").strip(),
                    "control_name": str(meta.get("name") or "").strip(),
                    "severity": str(meta.get("severity") or "Medium").strip() or "Medium",
                    "applicable": applicable,
                    "passed": passed,
                    "reason": str(item.get("reason") or "").strip(),
                    "evidence": evidence,
                }
            )
            seen.add(key)

        # Ensure every enabled control has a row, even if model omitted it.
        for key, meta in control_map.items():
            if key in seen:
                continue
            normalized_checks.append(
                {
                    "control_key": key,
                    "control_id": str(meta.get("control_id") or "").strip(),
                    "control_name": str(meta.get("name") or "").strip(),
                    "severity": str(meta.get("severity") or "Medium").strip() or "Medium",
                    "applicable": False,
                    "passed": True,
                    "reason": "No explicit assessment returned by model.",
                    "evidence": [],
                }
            )

        entities = payload.get("entities")
        if not isinstance(entities, dict):
            entities = {}

        missing_evidence = payload.get("missing_evidence")
        if not isinstance(missing_evidence, list):
            missing_evidence = []

        return {
            "ticket_key": str(payload.get("ticket_key") or "").strip(),
            "control_domain": str(payload.get("control_domain") or "").strip(),
            "entities": {
                "requester_or_caller": str(entities.get("requester_or_caller") or "").strip(),
                "approver": str(entities.get("approver") or "").strip(),
                "fulfiller": str(entities.get("fulfiller") or "").strip(),
            },
            "final_status": str(payload.get("final_status") or "").strip(),
            "summary": str(payload.get("summary") or "").strip(),
            "missing_evidence": [str(x).strip() for x in missing_evidence if str(x).strip()][:12],
            "checks": normalized_checks,
        }
