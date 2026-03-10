from __future__ import annotations


LEGACY_TO_CANONICAL_RULE_ID = {
    "R001": "ITGC-AC-01",
    "R002": "ITGC-WF-01",
    "R003": "ITGC-AP-01",
    "R004": "ITGC-SOD-01",
    "R005": "ITGC-CM-01",
    "R006": "ITGC-AC-02",
    "R007": "ITGC-DOC-01",
    "R008": "ITGC-CHG-01",
}


def canonical_rule_id(rule_id: str) -> str:
    return LEGACY_TO_CANONICAL_RULE_ID.get(rule_id, rule_id)

