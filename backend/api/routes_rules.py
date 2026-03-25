from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.llm.llm_evaluator import RULE_CATALOG
from backend.storage import crud
from backend.storage.db import get_db


router = APIRouter(prefix="/api", tags=["rules"])


class RuleCreateRequest(BaseModel):
    rule_id: str = Field(min_length=4, max_length=20)
    rule_name: str = Field(min_length=3, max_length=255)
    severity: str = Field(pattern="^(HIGH|MEDIUM|LOW)$")
    description: str = ""
    recommended_action: str = ""
    control_mapping: list[str] = Field(default_factory=list)
    active: bool = True


class RuleUpdateRequest(BaseModel):
    rule_name: str = Field(min_length=3, max_length=255)
    severity: str = Field(pattern="^(HIGH|MEDIUM|LOW)$")
    description: str = ""
    recommended_action: str = ""
    control_mapping: list[str] = Field(default_factory=list)
    active: bool = True


_RULE_ID_PATTERN = re.compile(r"^(ITGC-[A-Z]{2,5}-\d{2}|R\d{3,4})$")


def _default_rules() -> list[dict[str, Any]]:
    return [
        {
            "rule_id": rule_id,
            "rule_name": rule_name,
            "severity": severity,
            "description": "",
            "recommended_action": "",
            "control_mapping": controls,
            "active": True,
            "is_default": True,
        }
        for rule_id, rule_name, severity, controls in RULE_CATALOG
    ]


@router.get("/rules")
def list_rules(db: Session = Depends(get_db)):
    defaults = _default_rules()
    default_ids = {rule["rule_id"] for rule in defaults}

    # Check for overrides of default rules
    overrides: dict[str, dict[str, Any]] = {}
    custom = []
    for config in crud.list_configs(db):
        if config.config_type != "rule":
            continue
        data = dict(config.data)
        rule_id = data.get("rule_id") or config.name
        if rule_id in default_ids:
            overrides[rule_id] = data
        else:
            custom.append(
                {
                    "rule_id": rule_id,
                    "rule_name": data.get("rule_name", config.name),
                    "severity": data.get("severity", "MEDIUM"),
                    "description": data.get("description", ""),
                    "recommended_action": data.get("recommended_action", ""),
                    "control_mapping": data.get("control_mapping", []),
                    "active": bool(data.get("active", True)),
                    "is_default": False,
                }
            )

    # Apply overrides to defaults, skipping any marked as deleted
    merged_defaults = []
    for rule in defaults:
        if rule["rule_id"] in overrides:
            override = overrides[rule["rule_id"]]
            if override.get("deleted"):
                continue  # rule was removed by the user
            merged_defaults.append({
                **rule,
                "rule_name": override.get("rule_name", rule["rule_name"]),
                "severity": override.get("severity", rule["severity"]),
                "description": override.get("description", rule.get("description", "")),
                "recommended_action": override.get("recommended_action", rule.get("recommended_action", "")),
                "control_mapping": override.get("control_mapping", rule["control_mapping"]),
                "active": bool(override.get("active", True)),
                "is_default": True,
            })
        else:
            merged_defaults.append(rule)

    custom.sort(key=lambda item: item["rule_id"])
    return merged_defaults + custom


@router.post("/rules")
def create_rule(request: RuleCreateRequest, db: Session = Depends(get_db)):
    normalized_rule_id = request.rule_id.strip().upper()
    if not _RULE_ID_PATTERN.match(normalized_rule_id):
        raise HTTPException(
            status_code=400,
            detail="rule_id must match ITGC-XX-## (e.g., ITGC-AC-01) or R### (e.g., R101)",
        )
    existing_ids = {rule["rule_id"] for rule in _default_rules()}
    for config in crud.list_configs(db):
        if config.config_type == "rule":
            existing_rule_id = (config.data or {}).get("rule_id", config.name)
            if isinstance(existing_rule_id, str):
                existing_ids.add(existing_rule_id.strip().upper())
    if normalized_rule_id in existing_ids:
        raise HTTPException(status_code=409, detail=f"Rule {normalized_rule_id} already exists")

    payload = request.model_dump()
    payload["rule_id"] = normalized_rule_id

    record = crud.upsert_config(
        db,
        "rule",
        normalized_rule_id,
        payload,
    )
    return {
        "id": record.id,
        "rule_id": normalized_rule_id,
        "rule_name": request.rule_name,
        "severity": request.severity,
        "active": request.active,
    }


@router.delete("/rules/{rule_id}")
def delete_rule(rule_id: str, db: Session = Depends(get_db)):
    normalized_rule_id = rule_id.strip().upper()
    default_ids = {rule["rule_id"] for rule in _default_rules()}
    if normalized_rule_id in default_ids:
        # Default rules live only in RULE_CATALOG (not in DB), so "delete" means
        # store a disabled+deleted override so list_rules filters it out.
        crud.upsert_config(db, "rule", normalized_rule_id, {
            "rule_id": normalized_rule_id,
            "deleted": True,
            "active": False,
        })
    else:
        deleted = crud.delete_config(db, "rule", normalized_rule_id)
        if not deleted:
            raise HTTPException(status_code=404, detail=f"Rule {normalized_rule_id} not found")
    return {"deleted": normalized_rule_id}


@router.put("/rules/{rule_id}")
def update_rule(rule_id: str, request: RuleUpdateRequest, db: Session = Depends(get_db)):
    normalized_rule_id = rule_id.strip().upper()
    payload = request.model_dump()
    payload["rule_id"] = normalized_rule_id

    record = crud.upsert_config(
        db,
        "rule",
        normalized_rule_id,
        payload,
    )
    return {
        "id": record.id,
        "rule_id": normalized_rule_id,
        "rule_name": request.rule_name,
        "severity": request.severity,
        "description": request.description,
        "recommended_action": request.recommended_action,
        "control_mapping": request.control_mapping,
        "active": request.active,
    }

