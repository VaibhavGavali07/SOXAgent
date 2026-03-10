from __future__ import annotations

from typing import Any

from backend.storage.models import (
    CanonicalIdentityLogModel,
    CanonicalSoftwareInstallModel,
    CanonicalTicketModel,
    CanonicalWorkflowLogModel,
)


def normalize_servicenow_ticket(raw: dict[str, Any], related: dict[str, Any] | None = None) -> dict[str, Any]:
    related = related or {}
    ticket = CanonicalTicketModel(
        source="servicenow",
        ticket_id=raw["number"],
        type=raw["record_type"],
        summary=raw["short_description"],
        description=raw.get("description", ""),
        status=raw["state"],
        requestor=raw["requested_for"],
        approvals=raw.get("approval_history", []),
        implementers=raw.get("assigned_implementers", []),
        created_at=raw["opened_at"],
        updated_at=raw["sys_updated_on"],
        closed_at=raw.get("closed_at"),
        workflow={
            "steps": raw.get("workflow_steps", []),
            "transitions": raw.get("state_transitions", []),
        },
        comments=raw.get("activity", []),
        attachments=raw.get("attachments", []),
        custom_fields={
            **raw.get("custom_fields", {}),
            "software_installs": related.get("software_installs", []),
            "identity_logs": related.get("identity_logs", []),
            "workflow_logs": related.get("workflow_logs", []),
        },
    )
    return ticket.model_dump(by_alias=True)


def normalize_software_install(raw: dict[str, Any]) -> dict[str, Any]:
    return CanonicalSoftwareInstallModel(**raw).model_dump()


def normalize_identity_log(raw: dict[str, Any]) -> dict[str, Any]:
    return CanonicalIdentityLogModel(**raw).model_dump()


def normalize_workflow_log(raw: dict[str, Any]) -> dict[str, Any]:
    return CanonicalWorkflowLogModel(**raw).model_dump()

