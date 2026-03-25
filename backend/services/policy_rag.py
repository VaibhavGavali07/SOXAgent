"""SOX/ITGC Policy Knowledge Base with RAG retrieval.

Maintains an in-memory index of SOX policy snippets.  At query time it
retrieves the TOP-K most relevant policy chunks based on the ticket's
summary + description, so only *pertinent* policies are injected into the
LLM prompt rather than a single hardcoded pair of sentences.

Uses the bag-of-words fallback embedder internally — no API calls, zero
latency, safe to call at server startup.
"""
from __future__ import annotations

import logging
import math
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Expanded policy knowledge base
# ---------------------------------------------------------------------------

_POLICY_CHUNKS: list[dict[str, str]] = [
    {
        "id": "AC-SELF-APPROVAL",
        "control_id": "ITGC-AC-01",
        "title": "Self-Approval Prevention",
        "text": (
            "SOX Section 404 requires segregation of duties. The person requesting access "
            "or a change must not be the same person who approves it. Self-approval "
            "invalidates the approval control and is a Segregation of Duties (SoD) "
            "violation. Auditors must verify that requester and approver are distinct "
            "individuals with no reporting relationship conflict."
        ),
    },
    {
        "id": "AC-MISSING-APPROVAL",
        "control_id": "ITGC-AC-04",
        "title": "Missing Approval Evidence",
        "text": (
            "All changes to production systems, user access, and configurations must have "
            "documented approval prior to or at closure. Approval may be evidenced by: "
            "(1) a direct approver comment in the ticket, (2) email or screenshot "
            "evidence referenced in comments, or (3) a linked approval workflow record. "
            "Tickets closed without any approval evidence are non-compliant under "
            "PCAOB AS 2201."
        ),
    },
    {
        "id": "AC-PRIVILEGED-ACCESS",
        "control_id": "ITGC-AC-02",
        "title": "Privileged Access Management",
        "text": (
            "Privileged accounts (admin, root, service accounts) require enhanced approval "
            "controls. Emergency access must follow break-glass procedures with post-event "
            "review within 24 hours. Time-limited access grants must be revoked after the "
            "approved window. All privileged access grants must be logged and reviewed "
            "quarterly."
        ),
    },
    {
        "id": "CM-CLOSURE-DOC",
        "control_id": "ITGC-WF-01",
        "title": "Change Closure Documentation",
        "text": (
            "COSO Information & Communication requires all changes be documented with: "
            "(1) what was changed, (2) who made the change, (3) when it was made, "
            "(4) the outcome. Vague closure notes like 'task done' or 'closing ticket' "
            "do not satisfy requirements. Acceptable examples: 'Installed Python 3.11 on "
            "workstation WS-042, verified with python --version output'; 'Password reset "
            "completed for user jsmith, user confirmed access restored at 14:32 UTC'."
        ),
    },
    {
        "id": "CM-SOFTWARE-CONTROL",
        "control_id": "ITGC-SW-01",
        "title": "Software Installation Control",
        "text": (
            "Only software on the organisation's Approved Software List (ASL) may be "
            "installed on company systems. Installation of unlisted software requires a "
            "formal exception request and management approval. Unauthorized software "
            "installations must be flagged as non-compliant and the software removed or "
            "exception-approved. The ASL is reviewed quarterly by IT Security."
        ),
    },
    {
        "id": "CM-EMERGENCY-CHANGE",
        "control_id": "ITGC-CM-03",
        "title": "Emergency Change Procedures",
        "text": (
            "Emergency changes that bypass standard approval due to time constraints must "
            "be ratified post-implementation within 24–48 hours. Post-implementation "
            "review must document: the business justification, who authorised the "
            "emergency, what was changed, and the outcome. Failure to complete "
            "post-implementation review is a control deficiency."
        ),
    },
    {
        "id": "AT-AUDIT-TRAIL",
        "control_id": "ITGC-AT-01",
        "title": "Audit Trail Requirements",
        "text": (
            "SOX Section 404 requires all significant system events be logged and those "
            "logs protected from modification. ITSM tickets serve as the audit trail for "
            "IT changes and access. Comments must not be deleted. Timestamps must be "
            "system-generated, not manually entered. Log retention must meet the "
            "organisation's retention policy (typically 7 years for SOX)."
        ),
    },
    {
        "id": "AT-EVIDENCE-QUALITY",
        "control_id": "ITGC-WF-01",
        "title": "Evidence Quality Standards",
        "text": (
            "For SOX compliance, evidence must be: (1) Specific — naming actual systems, "
            "users, and actions; (2) Timely — documented at or near the time of the "
            "action; (3) Complete — covering the full lifecycle from request to closure; "
            "(4) Objective — based on facts, not assertions. Hearsay or paraphrased "
            "approvals without reference to original communication are insufficient."
        ),
    },
    {
        "id": "UAM-ACCESS-REVIEW",
        "control_id": "ITGC-AC-05",
        "title": "Access Review and Certification",
        "text": (
            "User access must be reviewed and certified periodically — quarterly for "
            "privileged access, annually for standard access. Access granted for a "
            "specific purpose or time period must be revoked upon completion. Access "
            "reviews must be performed by data owners, not IT administrators."
        ),
    },
    {
        "id": "PCAOB-DEFICIENCY",
        "control_id": "PCAOB-AS2201",
        "title": "Control Deficiency Classification",
        "text": (
            "PCAOB AS 2201 classifies control issues as: (1) Control Deficiency — a "
            "single control failure; (2) Significant Deficiency — less than material but "
            "warrants attention by those responsible for oversight; (3) Material Weakness "
            "— a deficiency that could result in a material misstatement of financial "
            "statements. Self-approval and missing approvals are typically significant "
            "deficiencies or material weaknesses depending on dollar thresholds and "
            "frequency."
        ),
    },
]


# ---------------------------------------------------------------------------
# Internal bag-of-words embedder (no API calls, used only for policy index)
# ---------------------------------------------------------------------------

def _bow_embed(text: str, dims: int = 128) -> list[float]:
    import hashlib
    tokens = text.lower().split()
    vec = [0.0] * dims
    for token in tokens:
        h = int(hashlib.md5(token.encode()).hexdigest(), 16)
        vec[h % dims] += 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    num = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return num / (na * nb) if na and nb else 0.0


# ---------------------------------------------------------------------------
# PolicyRAG
# ---------------------------------------------------------------------------

class PolicyRAG:
    """In-memory policy knowledge base with bag-of-words semantic retrieval.

    Uses its own internal embedder (no external API calls) so it is safe to
    instantiate at server startup without any credentials.
    """

    def __init__(self) -> None:
        self._index: list[dict[str, Any]] = []
        self._build_index()

    def _build_index(self) -> None:
        for chunk in _POLICY_CHUNKS:
            text = f"{chunk['title']} {chunk['text']}"
            self._index.append({**chunk, "vector": _bow_embed(text)})
        logger.info("PolicyRAG: indexed %d policy chunks", len(self._index))

    def retrieve(self, query: str, top_k: int = 3) -> list[dict[str, str]]:
        """Return top-K most relevant policy chunks for ``query``.

        Returns a list of dicts with keys ``control_id``, ``title``,
        ``snippet`` — ready to be formatted into the LLM prompt.
        """
        if not query or not self._index:
            return [
                {"control_id": c["control_id"], "title": c["title"], "snippet": c["text"]}
                for c in _POLICY_CHUNKS[:2]
            ]
        q_vec = _bow_embed(query)
        scored = sorted(
            self._index,
            key=lambda c: _cosine(q_vec, c["vector"]),
            reverse=True,
        )
        return [
            {"control_id": c["control_id"], "title": c["title"], "snippet": c["text"]}
            for c in scored[:top_k]
        ]


# Module-level singleton — built once at first use.
_rag: PolicyRAG | None = None


def get_policy_rag() -> PolicyRAG:
    global _rag
    if _rag is None:
        _rag = PolicyRAG()
    return _rag
