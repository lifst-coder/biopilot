"""HTTP routes for the Analysis layer (prefix ``/api/analysis``). Thin: service calls only."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.analysis import records, service
from app.analysis.schemas import (
    AcceptanceCriteria,
    AnalysisResultOut,
    ConditionRecords,
    CriteriaCreate,
    CriteriaVersionOut,
    ExperimentMetrics,
    MethodDoc,
    MetricsComparison,
    OperatorRecords,
    PeriodRecords,
    ProjectCriteria,
    ReportFormat,
    ResultKind,
    RunResponse,
    TrendPoint,
)
from app.deps import get_session

router = APIRouter(prefix="/api/analysis", tags=["analysis"])


@router.get("/criteria", response_model=AcceptanceCriteria, operation_id="analysis_get_criteria")
def get_criteria(
    project_id: int | None = Query(
        default=None, description="Return this project's active criteria instead of defaults"
    ),
    session: Session = Depends(get_session),
) -> AcceptanceCriteria:
    """Default criteria, or the active criteria of ``project_id``."""
    if project_id is None:
        return service.get_criteria()
    return service.get_project_criteria(session, project_id).active.criteria


@router.get("/methods", response_model=list[MethodDoc], operation_id="analysis_list_methods")
def list_methods() -> list[MethodDoc]:
    """Formula sheets (formulas, assumptions, references) of every current method."""
    return service.list_methods()


@router.get(
    "/projects/{project_id}/criteria",
    response_model=ProjectCriteria,
    operation_id="analysis_get_project_criteria",
)
def get_project_criteria(
    project_id: int, session: Session = Depends(get_session)
) -> ProjectCriteria:
    """Active criteria version and full history (version 0 = defaults)."""
    return service.get_project_criteria(session, project_id)


@router.post(
    "/projects/{project_id}/criteria",
    response_model=CriteriaVersionOut,
    status_code=201,
    operation_id="analysis_create_project_criteria",
)
def create_project_criteria(
    project_id: int, body: CriteriaCreate, session: Session = Depends(get_session)
) -> CriteriaVersionOut:
    """Append a new criteria version (existing results stay unchanged; re-run to apply)."""
    return service.create_criteria_version(session, project_id, body)


@router.post(
    "/experiments/{experiment_id}/run",
    response_model=RunResponse,
    operation_id="analysis_run_experiment",
)
def run_experiment(experiment_id: int, session: Session = Depends(get_session)) -> RunResponse:
    """Run all applicable analyses (idempotent for identical inputs)."""
    return service.run_experiment(session, experiment_id)


@router.get(
    "/experiments/{experiment_id}/metrics",
    response_model=ExperimentMetrics,
    operation_id="analysis_get_metrics",
)
def get_metrics(experiment_id: int, session: Session = Depends(get_session)) -> ExperimentMetrics:
    """Headline metrics from the latest stored results."""
    return service.get_metrics(session, experiment_id)


@router.get(
    "/experiments/{experiment_id}/report",
    response_class=PlainTextResponse,
    operation_id="analysis_get_report",
    responses={200: {"content": {"text/markdown": {}, "text/csv": {}}}},
)
def get_report(
    experiment_id: int,
    format: ReportFormat = Query(default="markdown"),
    session: Session = Depends(get_session),
) -> PlainTextResponse:
    """Markdown or CSV export of the latest stored results (download)."""
    text, media_type, filename = service.build_report(session, experiment_id, format)
    return PlainTextResponse(
        text,
        media_type=f"{media_type}; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get(
    "/results", response_model=list[AnalysisResultOut], operation_id="analysis_list_results"
)
def list_results(
    experiment_id: int | None = Query(default=None),
    kind: ResultKind | None = Query(default=None),
    session: Session = Depends(get_session),
) -> list[AnalysisResultOut]:
    """Stored results filtered by experiment and kind."""
    return service.list_results(session, experiment_id, kind)


@router.get(
    "/results/{result_id}", response_model=AnalysisResultOut, operation_id="analysis_get_result"
)
def get_result(result_id: int, session: Session = Depends(get_session)) -> AnalysisResultOut:
    """One stored result."""
    return service.get_result(session, result_id)


@router.get("/compare", response_model=MetricsComparison, operation_id="analysis_compare")
def compare(
    a: int = Query(description="baseline experiment id"),
    b: int = Query(description="comparison experiment id"),
    session: Session = Depends(get_session),
) -> MetricsComparison:
    """Welch t-tests, effect sizes and Holm-adjusted per-analyte tests of b vs a."""
    return service.compare(session, a, b)


@router.get(
    "/projects/{project_id}/trend",
    response_model=list[TrendPoint],
    operation_id="analysis_project_trend",
)
def project_trend(project_id: int, session: Session = Depends(get_session)) -> list[TrendPoint]:
    """Recovery trend across a project's experiments."""
    return service.project_trend(session, project_id)


_PROJECTS = Query(default=None, description="Restrict to these projects (default: every project)")


@router.get(
    "/records/conditions",
    response_model=ConditionRecords,
    operation_id="analysis_records_by_condition",
)
def records_by_condition(
    key: str = Query(
        min_length=1, max_length=80, description="Condition key, e.g. cleanup_sorbent"
    ),
    contains: str | None = Query(default=None, max_length=80, description="Pool values containing"),
    project_id: list[int] | None = _PROJECTS,
    session: Session = Depends(get_session),
) -> ConditionRecords:
    """Stored outcomes of every experiment grouped by one condition value."""
    return records.by_condition(session, key, project_id, contains)


@router.get(
    "/records/operators",
    response_model=OperatorRecords,
    operation_id="analysis_records_by_operator",
)
def records_by_operator(
    window_days: int = Query(default=records.OPERATOR_WINDOW_DAYS, ge=0, le=365),
    project_id: list[int] | None = _PROJECTS,
    session: Session = Depends(get_session),
) -> OperatorRecords:
    """Outcomes by author and same-protocol pairs run by different authors (Welch)."""
    return records.by_operator(session, project_id, window_days)


@router.get(
    "/records/periods",
    response_model=PeriodRecords,
    operation_id="analysis_records_by_period",
)
def records_by_period(
    gap_days: int = Query(default=records.GAP_DAYS, ge=1, le=365),
    project_id: list[int] | None = _PROJECTS,
    session: Session = Depends(get_session),
) -> PeriodRecords:
    """Outcomes by month and stretches without any experiment."""
    return records.by_period(session, project_id, gap_days)
