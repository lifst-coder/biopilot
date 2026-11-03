"""System routes: health, runtime info and the audit log (prefix ``/api``)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.audit import AuditEventOut, list_events
from app.core.config import AIMode, get_settings
from app.deps import get_session

router = APIRouter(prefix="/api", tags=["system"])


class HealthOut(BaseModel):
    status: str


class SystemInfo(BaseModel):
    version: str
    ai_mode: AIMode
    claude_model: str | None


@router.get("/health", response_model=HealthOut, operation_id="system_health")
def health() -> HealthOut:
    return HealthOut(status="ok")


@router.get("/system/info", response_model=SystemInfo, operation_id="system_info")
def system_info() -> SystemInfo:
    from app import __version__

    settings = get_settings()
    return SystemInfo(
        version=__version__,
        ai_mode=settings.ai_mode,
        claude_model=settings.claude_model if settings.ai_mode == "claude" else None,
    )


@router.get("/audit", response_model=list[AuditEventOut], operation_id="system_list_audit")
def audit(
    project_id: int | None = Query(default=None),
    entity_type: str | None = Query(default=None),
    entity_id: int | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    session: Session = Depends(get_session),
) -> list[AuditEventOut]:
    return list_events(
        session, project_id=project_id, entity_type=entity_type, entity_id=entity_id, limit=limit
    )
