"""HTTP routes for the Memory layer (prefix ``/api/memory``). Thin: service calls only."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.errors import ValidationFailedError
from app.deps import get_session
from app.eln.schemas import ExperimentSummary
from app.memory import service
from app.memory.schemas import (
    ConditionHistoryEntry,
    ConditionMatrix,
    DigestOut,
    ExperimentDiff,
    GraphRelation,
    KGNodeType,
    KnowledgeGraph,
    KnowledgeNoteCreate,
    KnowledgeNoteList,
    KnowledgeNoteOut,
    MemoryAnswer,
    MemoryAskRequest,
    RecallBundle,
    ResearchGraph,
    SearchHit,
    SimilarExperiment,
    TimelineEntry,
)

router = APIRouter(prefix="/api/memory", tags=["memory"])


@router.get(
    "/projects/{project_id}/timeline",
    response_model=list[TimelineEntry],
    operation_id="memory_timeline",
)
def timeline(project_id: int, session: Session = Depends(get_session)) -> list[TimelineEntry]:
    """Chronological experiments with changed keys versus parent."""
    return service.get_timeline(session, project_id)


@router.get(
    "/projects/{project_id}/graph", response_model=ResearchGraph, operation_id="memory_graph"
)
def graph(
    project_id: int,
    relations: list[GraphRelation] | None = Query(
        default=None, description="Edge relations to include (default: derived_from only)"
    ),
    session: Session = Depends(get_session),
) -> ResearchGraph:
    """Experiment graph: lineage, condition similarity and proposal-test edges."""
    return service.get_graph(session, project_id, relations)


@router.get(
    "/projects/{project_id}/knowledge-graph",
    response_model=KnowledgeGraph,
    operation_id="memory_knowledge_graph",
)
def knowledge_graph(
    project_id: int,
    types: list[KGNodeType] | None = Query(default=None, description="Node types to include"),
    focus: str | None = Query(default=None, description="Node id to centre on, e.g. experiment:7"),
    radius: int = Query(default=2, ge=1, le=4),
    session: Session = Depends(get_session),
) -> KnowledgeGraph:
    """Experiment↔Condition↔Analyte/Sample↔Result↔Hypothesis↔Decision graph."""
    return service.get_knowledge_graph(session, project_id, types=types, focus=focus, radius=radius)


@router.get(
    "/projects/{project_id}/search", response_model=list[SearchHit], operation_id="memory_search"
)
def search(
    project_id: int,
    q: str = Query(min_length=1, max_length=200),
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_session),
) -> list[SearchHit]:
    """Ranked full-text search (FTS5 trigram) with highlights."""
    return service.search(session, project_id, q, limit)


@router.get(
    "/projects/{project_id}/recall", response_model=RecallBundle, operation_id="memory_recall"
)
def recall(
    project_id: int,
    q: str = Query(min_length=1, max_length=200),
    limit: int = Query(default=10, ge=1, le=50),
    session: Session = Depends(get_session),
) -> RecallBundle:
    """Experiments, protocols and stored results related to strain/sample/condition/analyte."""
    return service.recall(session, project_id, q, limit)


@router.post("/projects/{project_id}/ask", response_model=MemoryAnswer, operation_id="memory_ask")
def ask(
    project_id: int, body: MemoryAskRequest, session: Session = Depends(get_session)
) -> MemoryAnswer:
    """Question answering with evidence fragments (rules) or a grounded summary (Claude)."""
    return service.ask(session, project_id, body)


@router.get(
    "/projects/{project_id}/conditions/{key}/history",
    response_model=list[ConditionHistoryEntry],
    operation_id="memory_condition_history",
)
def condition_history(
    project_id: int, key: str, session: Session = Depends(get_session)
) -> list[ConditionHistoryEntry]:
    """Value of one condition key across the project's experiments."""
    return service.condition_history(session, project_id, key)


@router.get(
    "/compare-conditions", response_model=ConditionMatrix, operation_id="memory_compare_conditions"
)
def compare_conditions(
    ids: str = Query(description="Comma-separated experiment ids, e.g. 1,2,7"),
    varying_only: bool = Query(default=False),
    session: Session = Depends(get_session),
) -> ConditionMatrix:
    """Key × experiment condition matrix."""
    try:
        parsed = [int(x) for x in ids.split(",") if x.strip()]
    except ValueError as exc:
        raise ValidationFailedError("ids must be comma-separated integers") from exc
    return service.compare_conditions(session, parsed, varying_only=varying_only)


@router.get(
    "/experiments/{experiment_id}/lineage",
    response_model=list[ExperimentSummary],
    operation_id="memory_lineage",
)
def lineage(experiment_id: int, session: Session = Depends(get_session)) -> list[ExperimentSummary]:
    """Ancestors from root to the experiment."""
    return service.get_lineage(session, experiment_id)


@router.get(
    "/experiments/{experiment_id}/similar",
    response_model=list[SimilarExperiment],
    operation_id="memory_similar",
)
def similar(
    experiment_id: int,
    limit: int = Query(default=5, ge=1, le=50),
    session: Session = Depends(get_session),
) -> list[SimilarExperiment]:
    """Experiments ranked by condition-vector similarity."""
    return service.similar_experiments(session, experiment_id, limit)


@router.get("/diff", response_model=ExperimentDiff, operation_id="memory_diff")
def diff(
    a: int = Query(description="baseline experiment id"),
    b: int = Query(description="comparison experiment id"),
    session: Session = Depends(get_session),
) -> ExperimentDiff:
    """Condition, result, QC, note and dataset diff with sources."""
    return service.diff(session, a, b)


@router.get(
    "/experiments/{experiment_id}/digests",
    response_model=list[DigestOut],
    operation_id="memory_list_digests",
)
def list_digests(experiment_id: int, session: Session = Depends(get_session)) -> list[DigestOut]:
    """Digests of an experiment, newest first (with staleness)."""
    return service.list_digests(session, experiment_id)


@router.post(
    "/experiments/{experiment_id}/digests",
    response_model=DigestOut,
    status_code=status.HTTP_201_CREATED,
    operation_id="memory_create_digest",
)
def create_digest(experiment_id: int, session: Session = Depends(get_session)) -> DigestOut:
    """Create a digest (rules or grounded Claude)."""
    return service.create_digest(session, experiment_id)


@router.get(
    "/projects/{project_id}/knowledge-notes",
    response_model=KnowledgeNoteList,
    operation_id="memory_list_knowledge_notes",
)
def list_knowledge_notes(
    project_id: int, session: Session = Depends(get_session)
) -> KnowledgeNoteList:
    """Researcher knowledge notes of a project."""
    return service.list_knowledge_notes(session, project_id)


@router.post(
    "/projects/{project_id}/knowledge-notes",
    response_model=KnowledgeNoteOut,
    status_code=status.HTTP_201_CREATED,
    operation_id="memory_create_knowledge_note",
)
def create_knowledge_note(
    project_id: int, body: KnowledgeNoteCreate, session: Session = Depends(get_session)
) -> KnowledgeNoteOut:
    """Create an immutable knowledge note (audited)."""
    return service.create_knowledge_note(session, project_id, body)
