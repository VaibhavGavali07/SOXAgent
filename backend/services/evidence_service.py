from __future__ import annotations

from typing import Any


def build_timeline(ticket: dict[str, Any]) -> list[dict[str, Any]]:
    timeline: list[dict[str, Any]] = []
    for index, comment in enumerate(ticket.get("comments", [])):
        timeline.append(
            {
                "kind": "comment",
                "ref_id": comment["id"],
                "timestamp": comment.get("timestamp"),
                "summary": comment.get("body", "")[:200],
                "index": index,
            }
        )
    for index, approval in enumerate(ticket.get("approvals", [])):
        timeline.append(
            {
                "kind": "approval",
                "ref_id": f"approval_{index}",
                "timestamp": approval.get("timestamp"),
                "summary": f'{approval.get("decision")} by {approval.get("approver", {}).get("name", "")}'[:200],
                "index": index,
            }
        )
    for index, transition in enumerate(ticket.get("workflow", {}).get("transitions", [])):
        timeline.append(
            {
                "kind": "transition",
                "ref_id": f"transition_{index}",
                "timestamp": transition.get("timestamp"),
                "summary": f'{transition.get("from")} -> {transition.get("to")}'[:200],
                "index": index,
            }
        )
    timeline.sort(key=lambda item: item.get("timestamp") or "")
    return timeline


def related_policy_snippets() -> list[dict[str, str]]:
    return [
        {
            "control_id": "SOX ITGC AC-1",
            "snippet": "Requests for elevated access require approval independent from the requestor and implementer.",
        },
        {
            "control_id": "SOX ITGC CH-2",
            "snippet": "Changes must not be implemented or closed before documented approval and completion evidence exist.",
        },
    ]

