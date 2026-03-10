from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import DateTime, Float, Index, Integer, String, Text
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import Mapped, mapped_column

from backend.storage.db import Base


def utcnow() -> datetime:
    return datetime.utcnow()


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utcnow,
        onupdate=utcnow,
        index=True,
    )


class ConfigRecord(Base, TimestampMixin):
    __tablename__ = "configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    config_type: Mapped[str] = mapped_column(String(50), index=True)
    name: Mapped[str] = mapped_column(String(100), index=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class RawRecord(Base, TimestampMixin):
    __tablename__ = "raw_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(50), index=True)
    record_type: Mapped[str] = mapped_column(String(50), index=True)
    external_id: Mapped[str] = mapped_column(String(100), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)


class TicketRecord(Base, TimestampMixin):
    __tablename__ = "tickets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(50), index=True)
    ticket_id: Mapped[str] = mapped_column(String(100), index=True)
    ticket_type: Mapped[str] = mapped_column(String(50), index=True)
    status: Mapped[str] = mapped_column(String(100), index=True)
    summary: Mapped[str] = mapped_column(Text)
    requestor_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    requestor_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    severity_hint: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    canonical_json: Mapped[dict[str, Any]] = mapped_column(JSON)


class EmbeddingRecord(Base, TimestampMixin):
    __tablename__ = "embeddings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(50), index=True)
    entity_id: Mapped[str] = mapped_column(String(100), index=True)
    vector_json: Mapped[list[float]] = mapped_column(JSON)
    text_preview: Mapped[str] = mapped_column(Text)


class LLMRunRecord(Base, TimestampMixin):
    __tablename__ = "llm_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, default=lambda: str(uuid.uuid4()))
    source: Mapped[str] = mapped_column(String(50), index=True)
    status: Mapped[str] = mapped_column(String(50), default="queued", index=True)
    total_items: Mapped[int] = mapped_column(Integer, default=0)
    processed_items: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class LLMResponseRecord(Base, TimestampMixin):
    __tablename__ = "llm_responses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    ticket_id: Mapped[str] = mapped_column(String(100), index=True)
    ticket_db_id: Mapped[int] = mapped_column(Integer, index=True)
    provider: Mapped[str] = mapped_column(String(50), index=True)
    model: Mapped[str] = mapped_column(String(100), index=True)
    prompt_hash: Mapped[str] = mapped_column(String(64), index=True)
    prompt_text: Mapped[str] = mapped_column(Text)
    response_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    overall_assessment: Mapped[str] = mapped_column(String(50), index=True)


class RuleResultRecord(Base, TimestampMixin):
    __tablename__ = "rule_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    ticket_db_id: Mapped[int] = mapped_column(Integer, index=True)
    ticket_id: Mapped[str] = mapped_column(String(100), index=True)
    source: Mapped[str] = mapped_column(String(50), index=True)
    rule_id: Mapped[str] = mapped_column(String(20), index=True)
    rule_name: Mapped[str] = mapped_column(String(255))
    severity: Mapped[str] = mapped_column(String(20), index=True)
    status: Mapped[str] = mapped_column(String(20), index=True)
    confidence: Mapped[float] = mapped_column(Float)
    why: Mapped[str] = mapped_column(Text)
    evidence_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    recommended_action: Mapped[str] = mapped_column(Text)
    control_mapping: Mapped[list[str]] = mapped_column(JSON)


class AlertRecord(Base, TimestampMixin):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    ticket_db_id: Mapped[int] = mapped_column(Integer, index=True)
    ticket_id: Mapped[str] = mapped_column(String(100), index=True)
    source: Mapped[str] = mapped_column(String(50), index=True)
    rule_id: Mapped[str] = mapped_column(String(20), index=True)
    severity: Mapped[str] = mapped_column(String(20), index=True)
    status: Mapped[str] = mapped_column(String(20), index=True)
    title: Mapped[str] = mapped_column(String(255))
    detail: Mapped[str] = mapped_column(Text)
    evidence_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON)


class AuditReportRecord(Base, TimestampMixin):
    __tablename__ = "audit_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    source: Mapped[str] = mapped_column(String(50), index=True)
    summary_json: Mapped[dict[str, Any]] = mapped_column(JSON)


class NotificationRecord(Base, TimestampMixin):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    channel: Mapped[str] = mapped_column(String(50), index=True)
    severity: Mapped[str] = mapped_column(String(20), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)


Index("ix_rule_results_ticket_rule", RuleResultRecord.ticket_id, RuleResultRecord.rule_id)
Index("ix_alerts_ticket_rule", AlertRecord.ticket_id, AlertRecord.rule_id)


class PersonModel(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str = ""
    name: str = ""
    email: str | None = None


class ApprovalModel(BaseModel):
    approver: PersonModel
    timestamp: str
    type: str
    decision: str


class WorkflowStepModel(BaseModel):
    name: str
    status: Literal["done", "skipped", "pending"]
    timestamp: str | None = None


class TransitionModel(BaseModel):
    from_status: str = Field(alias="from")
    to: str
    by: PersonModel
    timestamp: str

    model_config = ConfigDict(populate_by_name=True)


class CommentModel(BaseModel):
    id: str
    author: PersonModel
    timestamp: str
    body: str


class AttachmentModel(BaseModel):
    id: str
    name: str
    url: str


class WorkflowModel(BaseModel):
    steps: list[WorkflowStepModel] = Field(default_factory=list)
    transitions: list[TransitionModel] = Field(default_factory=list)


class CanonicalTicketModel(BaseModel):
    model_config = ConfigDict(extra="allow")

    source: Literal["servicenow"]
    ticket_id: str
    type: Literal["incident", "request", "change"]
    summary: str
    description: str
    status: str
    requestor: PersonModel
    approvals: list[ApprovalModel] = Field(default_factory=list)
    implementers: list[PersonModel] = Field(default_factory=list)
    created_at: str
    updated_at: str
    closed_at: str | None = None
    workflow: WorkflowModel = Field(default_factory=WorkflowModel)
    comments: list[CommentModel] = Field(default_factory=list)
    attachments: list[AttachmentModel] = Field(default_factory=list)
    custom_fields: dict[str, Any] = Field(default_factory=dict)


class EvidenceItemModel(BaseModel):
    type: Literal["comment", "approval", "transition", "field"]
    ref_id: str
    timestamp: str | None = None
    snippet: str = Field(max_length=200)


class RuleEvaluationModel(BaseModel):
    rule_id: str
    rule_name: str
    severity: Literal["HIGH", "MEDIUM", "LOW"]
    status: Literal["PASS", "FAIL", "NEEDS_REVIEW"]
    confidence: float = Field(ge=0.0, le=1.0)
    why: str
    evidence: list[EvidenceItemModel] = Field(default_factory=list)
    recommended_action: str
    control_mapping: list[str] = Field(default_factory=list)

    @field_validator("evidence")
    @classmethod
    def require_evidence_for_non_pass(cls, value: list[EvidenceItemModel], info: Any) -> list[EvidenceItemModel]:
        status = info.data.get("status")
        if status in {"FAIL", "NEEDS_REVIEW"} and not value:
            raise ValueError("Evidence is required for FAIL and NEEDS_REVIEW")
        return value


class LLMEvaluationModel(BaseModel):
    run_id: str
    ticket_id: str
    overall_assessment: Literal["compliant", "non_compliant", "needs_review"]
    rules: list[RuleEvaluationModel]
    red_flags: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    missing_info: list[str] = Field(default_factory=list)


class CanonicalSoftwareInstallModel(BaseModel):
    source: str = "software_log"
    ticket_id: str
    software_name: str
    installed_by: PersonModel
    authorized: bool
    timestamp: str


class CanonicalIdentityLogModel(BaseModel):
    source: str = "identity_log"
    ticket_id: str
    user: PersonModel
    privilege: str
    action: str
    timestamp: str


class CanonicalWorkflowLogModel(BaseModel):
    source: str = "workflow_log"
    ticket_id: str
    event: str
    actor: PersonModel
    timestamp: str

