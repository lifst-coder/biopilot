"""HTTP routes for the Analysis layer (prefix ``/api/analysis``)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.analysis import service
from app.analysis.schemas import (
    AcceptanceCriteria,
    AnalysisResultOut,
    ExperimentMetrics,
    MetricsComparison,
    ResultKind,
    RunResponse,
    TrendPoint,
)
from app.deps import get_session

router = APIRouter(prefix="/api/analysis", tags=["analysis"])


@router.get("/criteria", response_model=AcceptanceCriteria, operation_id="analysis_get_criteria")
def get_criteria() -> AcceptanceCriteria:
    return service.get_criteria()


@router.post(
    "/experiments/{experiment_id}/run",
    response_model=RunResponse,
    operation_id="analysis_run_experiment",
)
def run_experiment(experiment_id: int, session: Session = Depends(get_session)) -> RunResponse:
    return service.run_experiment(session, experiment_id)


@router.get(
    "/experiments/{experiment_id}/metrics",
    response_model=ExperimentMetrics,
    operation_id="analysis_get_metrics",
)
def get_metrics(experiment_id: int, session: Session = Depends(get_session)) -> ExperimentMetrics:
    return service.get_metrics(session, experiment_id)


@router.get(
    "/results", response_model=list[AnalysisResultOut], operation_id="analysis_list_results"
)
def list_results(
    experiment_id: int | None = Query(default=None),
    kind: ResultKind | None = Query(default=None),
    session: Session = Depends(get_session),
) -> list[AnalysisResultOut]:
    return service.list_results(session, experiment_id, kind)


@router.get(
    "/results/{result_id}", response_model=AnalysisResultOut, operation_id="analysis_get_result"
)
def get_result(result_id: int, session: Session = Depends(get_session)) -> AnalysisResultOut:
    return service.get_result(session, result_id)


@router.get("/compare", response_model=MetricsComparison, operation_id="analysis_compare")
def compare(
    a: int = Query(description="baseline experiment id"),
    b: int = Query(description="comparison experiment id"),
    session: Session = Depends(get_session),
) -> MetricsComparison:
    return service.compare(session, a, b)


@router.get(
    "/projects/{project_id}/trend",
    response_model=list[TrendPoint],
    operation_id="analysis_project_trend",
)
def project_trend(project_id: int, session: Session = Depends(get_session)) -> list[TrendPoint]:
    return service.project_trend(session, project_id)
