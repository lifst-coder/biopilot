"""HTTP routes for the Memory layer (prefix ``/api/memory``)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.deps import get_session
from app.eln.schemas import ExperimentSummary
from app.memory import service
from app.memory.schemas import DigestOut, ExperimentDiff, ResearchGraph, SearchHit, TimelineEntry

router = APIRouter(prefix="/api/memory", tags=["memory"])


@router.get(
    "/projects/{project_id}/timeline",
    response_model=list[TimelineEntry],
    operation_id="memory_timeline",
)
def timeline(project_id: int, session: Session = Depends(get_session)) -> list[TimelineEntry]:
    return service.get_timeline(session, project_id)


@router.get(
    "/projects/{project_id}/graph", response_model=ResearchGraph, operation_id="memory_graph"
)
def graph(project_id: int, session: Session = Depends(get_session)) -> ResearchGraph:
    return service.get_graph(session, project_id)


@router.get(
    "/projects/{project_id}/search", response_model=list[SearchHit], operation_id="memory_search"
)
def search(
    project_id: int,
    q: str = Query(min_length=1, max_length=200),
    session: Session = Depends(get_session),
) -> list[SearchHit]:
    return service.search(session, project_id, q)


@router.get(
    "/experiments/{experiment_id}/lineage",
    response_model=list[ExperimentSummary],
    operation_id="memory_lineage",
)
def lineage(experiment_id: int, session: Session = Depends(get_session)) -> list[ExperimentSummary]:
    return service.get_lineage(session, experiment_id)


@router.get("/diff", response_model=ExperimentDiff, operation_id="memory_diff")
def diff(
    a: int = Query(description="baseline experiment id"),
    b: int = Query(description="comparison experiment id"),
    session: Session = Depends(get_session),
) -> ExperimentDiff:
    return service.diff(session, a, b)


@router.get(
    "/experiments/{experiment_id}/digests",
    response_model=list[DigestOut],
    operation_id="memory_list_digests",
)
def list_digests(experiment_id: int, session: Session = Depends(get_session)) -> list[DigestOut]:
    return service.list_digests(session, experiment_id)


@router.post(
    "/experiments/{experiment_id}/digests",
    response_model=DigestOut,
    status_code=status.HTTP_201_CREATED,
    operation_id="memory_create_digest",
)
def create_digest(experiment_id: int, session: Session = Depends(get_session)) -> DigestOut:
    return service.create_digest(session, experiment_id)
