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
    custom = []
    for config in crud.list_configs(db):
        if config.config_type != "rule":
            continue
        data = dict(config.data)
        rule_id = data.get("rule_id") or config.name
        if rule_id in default_ids:
            continue
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
    custom.sort(key=lambda item: item["rule_id"])
    return defaults + custom


@router.post("/rules")
def create_rule(request: RuleCreateRequest, db: Session = Depends(get_db)):
    if not re.match(r"^ITGC-[A-Z]{2,5}-\d{2}$", request.rule_id):
        raise HTTPException(status_code=400, detail="rule_id must match format ITGC-XX-## (e.g., ITGC-AC-01)")
    existing_ids = {rule["rule_id"] for rule in _default_rules()}
    for config in crud.list_configs(db):
        if config.config_type == "rule":
            existing_ids.add((config.data or {}).get("rule_id", config.name))
    if request.rule_id in existing_ids:
        raise HTTPException(status_code=409, detail=f"Rule {request.rule_id} already exists")

    record = crud.upsert_config(
        db,
        "rule",
        request.rule_id,
        request.model_dump(),
    )
    return {
        "id": record.id,
        "rule_id": request.rule_id,
        "rule_name": request.rule_name,
        "severity": request.severity,
        "active": request.active,
    }
