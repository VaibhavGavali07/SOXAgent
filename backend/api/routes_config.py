from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from backend.connectors.servicenow_connector import ServiceNowConnector
from backend.llm.chat_client import build_chat_provider, normalize_provider_name
from backend.storage import crud
from backend.storage.db import get_db
from backend.storage.models import ConfigRecord


router = APIRouter(prefix="/api", tags=["config"])


class ConfigCreateRequest(BaseModel):
    config_type: str
    name: str
    data: dict[str, Any] = Field(default_factory=dict)


class LLMTestRequest(BaseModel):
    provider: str | None = None
    deployment_name: str | None = None
    api_key: str | None = None
    endpoint: str | None = None
    api_version: str | None = None


class ServiceNowTestRequest(BaseModel):
    instance_url: str | None = None
    client_id: str | None = None
    client_secret: str | None = None
    table: str | None = None


class NotificationTestRequest(BaseModel):
    webhook_url: str | None = None
    email_to: str | None = None


class ClearDataRequest(BaseModel):
    include_configs: bool = False


def _pick_active_llm_config(db: Session) -> dict[str, Any]:
    row = db.scalar(
        select(ConfigRecord)
        .where(ConfigRecord.config_type == "llm")
        .order_by(
            desc(ConfigRecord.name == "llm-default"),
            desc(ConfigRecord.updated_at),
            desc(ConfigRecord.id),
        )
    )
    return dict(row.data) if row else {}


def _merge_preserving_secrets(base: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in incoming.items():
        if any(term in key.lower() for term in ("key", "secret", "token", "password")):
            if value is None or (isinstance(value, str) and not value.strip()):
                continue
        merged[key] = value
    return merged


@router.get("/configs")
def get_configs(db: Session = Depends(get_db)):
    configs = crud.list_configs(db)
    response = []
    for config in configs:
        data = dict(config.data)
        if config.config_type == "llm" and "deployment_name" not in data and "model" in data:
            data["deployment_name"] = data["model"]
        if config.config_type == "servicenow":
            if "client_id" not in data and "username" in data:
                data["client_id"] = data["username"]
            if "client_secret" not in data and "password" in data:
                data["client_secret"] = data["password"]
        masked_data = {
            key: (
                ""
                if any(secret_term in key.lower() for secret_term in ["key", "secret", "token", "password"])
                else value
            )
            for key, value in data.items()
            if key not in {"model", "username", "password"}
        }
        response.append(
            {
                "id": config.id,
                "config_type": config.config_type,
                "name": config.name,
                "data": masked_data,
                "created_at": config.created_at.isoformat(),
            }
        )
    return response


@router.post("/configs")
def save_config(request: ConfigCreateRequest, db: Session = Depends(get_db)):
    payload = dict(request.data)
    if request.config_type == "llm" and "model" in payload and "deployment_name" not in payload:
        payload["deployment_name"] = payload["model"]
    if request.config_type == "llm":
        payload["provider"] = normalize_provider_name(payload.get("provider"))
    record = crud.upsert_config(db, request.config_type, request.name, payload)
    return {"id": record.id, "config_type": record.config_type, "name": record.name}


@router.post("/llm/test")
def test_llm(request: LLMTestRequest, db: Session = Depends(get_db)):
    saved = _pick_active_llm_config(db)
    incoming = {
        key: value
        for key, value in request.model_dump(exclude_none=True).items()
        if not (isinstance(value, str) and not value.strip())
    }
    payload = _merge_preserving_secrets(saved, incoming)
    if "deployment_name" not in payload and "model" in payload:
        payload["deployment_name"] = payload["model"]
    provider_name = normalize_provider_name(payload.get("provider"))
    payload["provider"] = provider_name

    if provider_name == "mock":
        return {
            "ok": False,
            "skipped": True,
            "provider": "mock",
            "deployment_name": payload.get("deployment_name") or "mock-llm",
            "mock_mode": True,
            "message": "Mock provider selected. No external LLM connection to test.",
        }

    if provider_name in {"openai", "azure_openai", "gemini"} and not payload.get("api_key"):
        return {
            "ok": False,
            "provider": provider_name,
            "deployment_name": payload.get("deployment_name") or payload.get("model") or "",
            "mock_mode": False,
            "message": f"{provider_name} requires an API key before the connection test can pass. Save a valid key in LLM config.",
        }

    if provider_name == "azure_openai" and not payload.get("endpoint"):
        return {
            "ok": False,
            "provider": provider_name,
            "deployment_name": payload.get("deployment_name") or payload.get("model") or "",
            "mock_mode": False,
            "message": "Azure OpenAI requires an endpoint URL for the connection test.",
        }

    try:
        provider = build_chat_provider(payload)
        probe_prompt = (
            'Return strict JSON only: {"connection":"ok","service":"llm_test"}. '
            "Do not include markdown."
        )
        probe_result = provider.complete_json(probe_prompt)
        return {
            "ok": True,
            "provider": provider.provider_name,
            "deployment_name": provider.model_name,
            "mock_mode": provider.provider_name == "mock",
            "probe_response_preview": str(probe_result)[:200],
            "message": f"{provider.provider_name} connection test passed.",
        }
    except Exception as exc:
        return {
            "ok": False,
            "provider": provider_name,
            "deployment_name": payload.get("deployment_name") or payload.get("model") or "",
            "mock_mode": False,
            "message": f"Failed to initialize provider: {str(exc)}",
        }


@router.post("/servicenow/test")
def test_servicenow(request: ServiceNowTestRequest):
    if not request.instance_url:
        return {
            "ok": False,
            "source": "servicenow",
            "tickets_found": 0,
            "sample_ticket_ids": [],
            "message": "instance_url is required to test the ServiceNow connection.",
        }
    try:
        connector = ServiceNowConnector()
        result = connector.fetch(request.model_dump(exclude_none=True))
        return {
            "ok": True,
            "source": "servicenow",
            "tickets_found": len(result["tickets"]),
            "sample_ticket_ids": [ticket["ticket_id"] for ticket in result["tickets"][:3]],
            "message": f"ServiceNow connection successful. {len(result['tickets'])} closed/resolved tickets found.",
        }
    except Exception as exc:
        return {
            "ok": False,
            "source": "servicenow",
            "tickets_found": 0,
            "sample_ticket_ids": [],
            "message": f"ServiceNow connection failed: {str(exc)}",
        }


@router.post("/notifications/test")
def test_notifications(request: NotificationTestRequest):
    using_mock = os.getenv("MOCK_MODE", "true").lower() == "true" or not request.webhook_url
    target = request.email_to or request.webhook_url or "mock-target"
    return {
        "ok": True,
        "mock_mode": using_mock,
        "channel": "webhook" if request.webhook_url else "email",
        "target": target,
        "message": "Notification test validated in mock mode." if using_mock else "Notification settings accepted for runtime use.",
    }


@router.post("/data/clear")
def clear_data(request: ClearDataRequest, db: Session = Depends(get_db)):
    counts = crud.clear_compliance_data(db, include_configs=request.include_configs)
    return {
        "ok": True,
        "message": "Compliance data cleared.",
        "counts": counts,
    }
