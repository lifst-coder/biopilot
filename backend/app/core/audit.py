"""Append-only audit log. Every state change in any module must call :func:`record_event`."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict
from sqlalchemy import JSON, DateTime, Integer, String, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.core.db import Base, utcnow
from app.core.immutability import ImmutableMixin

Actor = Literal["user", "system", "seed", "ai:rules", "ai:claude"]


class AuditEvent(ImmutableMixin, Base):
    """One immutable audit entry. ``entity_type`` is ``<module>.<Entity>``."""

    __tablename__ = "core_audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    actor: Mapped[str] = mapped_column(String(32))
    action: Mapped[str] = mapped_column(String(64), index=True)
    entity_type: Mapped[str] = mapped_column(String(64), index=True)
    entity_id: Mapped[int] = mapped_column(Integer, index=True)
    project_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class AuditEventOut(BaseModel):
    """Public representation of an audit event."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    occurred_at: datetime
    actor: str
    action: str
    entity_type: str
    entity_id: int
    project_id: int | None
    payload: dict[str, Any]


def record_event(
    session: Session,
    *,
    actor: Actor,
    action: str,
    entity_type: str,
    entity_id: int,
    project_id: int | None = None,
    payload: dict[str, Any] | None = None,
) -> AuditEvent:
    """Append an audit event in the caller's transaction (flushes, does not commit)."""
    event = AuditEvent(
        actor=actor,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        project_id=project_id,
        payload=payload or {},
    )
    session.add(event)
    session.flush()
    return event


def list_events(
    session: Session,
    *,
    project_id: int | None = None,
    entity_type: str | None = None,
    entity_id: int | None = None,
    limit: int = 100,
) -> list[AuditEventOut]:
    """Return audit events, newest first, optionally filtered."""
    stmt = select(AuditEvent).order_by(AuditEvent.id.desc()).limit(limit)
    if project_id is not None:
        stmt = stmt.where(AuditEvent.project_id == project_id)
    if entity_type is not None:
        stmt = stmt.where(AuditEvent.entity_type == entity_type)
    if entity_id is not None:
        stmt = stmt.where(AuditEvent.entity_id == entity_id)
    return [AuditEventOut.model_validate(e) for e in session.scalars(stmt)]
