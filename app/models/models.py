from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db


def _uuid() -> str:
    return str(uuid.uuid4())


# ─────────────────────────────────────────────────────────────────────────────
class Ticket(db.Model):
    """Monitored tickets ingested from JIRA or ServiceNow."""

    __tablename__ = "tickets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    source: Mapped[str] = mapped_column(String(20))          # JIRA | ServiceNow
    ticket_key: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(50))
    requestor_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    approver_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    implementer_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    documentation_link: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    ticket_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    priority: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    raw_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    analyzed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    violations: Mapped[list[Violation]] = relationship(
        "Violation", back_populates="ticket", cascade="all, delete-orphan"
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "source": self.source,
            "ticket_key": self.ticket_key,
            "title": self.title,
            "status": self.status,
            "requestor_id": self.requestor_id,
            "approver_id": self.approver_id,
            "implementer_id": self.implementer_id,
            "documentation_link": self.documentation_link,
            "ticket_type": self.ticket_type,
            "priority": self.priority,
            "created_at": self.created_at.isoformat(),
            "analyzed_at": self.analyzed_at.isoformat() if self.analyzed_at else None,
            "violation_count": len(self.violations),
        }


# ─────────────────────────────────────────────────────────────────────────────
class Violation(db.Model):
    """A compliance violation detected by the ComplianceEngine."""

    __tablename__ = "violations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    ticket_id: Mapped[str] = mapped_column(String(36), ForeignKey("tickets.id"))
    control_id: Mapped[str] = mapped_column(String(50), index=True)
    violation_type: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String(20), index=True)   # High | Medium | Low
    status: Mapped[str] = mapped_column(String(20), default="Open") # Open | Acknowledged | Resolved
    detected_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    ticket: Mapped[Ticket] = relationship("Ticket", back_populates="violations")
    evidence: Mapped[list[AuditEvidence]] = relationship(
        "AuditEvidence", back_populates="violation", cascade="all, delete-orphan"
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "ticket_id": self.ticket_id,
            "ticket_key": self.ticket.ticket_key if self.ticket else None,
            "ticket_title": self.ticket.title if self.ticket else None,
            "ticket_source": self.ticket.source if self.ticket else None,
            "control_id": self.control_id,
            "violation_type": self.violation_type,
            "description": self.description,
            "severity": self.severity,
            "status": self.status,
            "detected_at": self.detected_at.isoformat(),
        }


# ─────────────────────────────────────────────────────────────────────────────
class AuditEvidence(db.Model):
    """Audit evidence package generated for each violation."""

    __tablename__ = "audit_evidence"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    violation_id: Mapped[str] = mapped_column(String(36), ForeignKey("violations.id"))
    report_data: Mapped[dict] = mapped_column(JSON)
    llm_analysis: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    violation: Mapped[Violation] = relationship("Violation", back_populates="evidence")

    def to_dict(self) -> dict:
        v = self.violation
        return {
            "id": self.id,
            "violation_id": self.violation_id,
            "control_id": v.control_id if v else None,
            "severity": v.severity if v else None,
            "ticket_key": v.ticket.ticket_key if v and v.ticket else None,
            "report_data": self.report_data,
            "llm_analysis": self.llm_analysis,
            "generated_at": self.generated_at.isoformat(),
        }


# ─────────────────────────────────────────────────────────────────────────────
class CustomRule(db.Model):
    """User-defined compliance validation rule evaluated on every ticket."""

    __tablename__ = "custom_rules"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    control_id: Mapped[str] = mapped_column(String(50))          # e.g. ITGC-CUSTOM-001
    severity: Mapped[str] = mapped_column(String(20))            # High | Medium | Low

    # Condition
    field: Mapped[str] = mapped_column(String(100))              # ticket field name
    operator: Mapped[str] = mapped_column(String(30))            # is_empty | is_not_empty | equals | not_equals | contains | not_contains
    value: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)   # comparison value

    # Scope filters (empty = apply to all)
    apply_to_status: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    apply_to_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    enabled: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    def violation_type(self) -> str:
        return f"CUSTOM_{self.id[:8].upper()}"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "control_id": self.control_id,
            "severity": self.severity,
            "field": self.field,
            "operator": self.operator,
            "value": self.value,
            "apply_to_status": self.apply_to_status,
            "apply_to_type": self.apply_to_type,
            "enabled": self.enabled,
            "created_at": self.created_at.isoformat(),
        }


# ─────────────────────────────────────────────────────────────────────────────
class Setting(db.Model):
    """Persisted key-value settings (LLM config, integration credentials)."""

    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    value: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
