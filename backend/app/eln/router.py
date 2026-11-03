"""HTTP routes for the ELN layer (prefix ``/api/eln``).

There are no update/delete routes: original records are immutable.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.deps import get_session
from app.eln import service
from app.eln.schemas import (
    ConditionField,
    DatasetCreate,
    DatasetOut,
    DatasetPreview,
    ExperimentCreate,
    ExperimentOut,
    ExperimentSummary,
    ProjectCreate,
    ProjectOut,
)

router = APIRouter(prefix="/api/eln", tags=["eln"])


@router.get(
    "/condition-fields",
    response_model=list[ConditionField],
    operation_id="eln_list_condition_fields",
)
def list_condition_fields() -> list[ConditionField]:
    return service.list_condition_fields()


@router.get("/projects", response_model=list[ProjectOut], operation_id="eln_list_projects")
def list_projects(session: Session = Depends(get_session)) -> list[ProjectOut]:
    return service.list_projects(session)


@router.post(
    "/projects",
    response_model=ProjectOut,
    status_code=status.HTTP_201_CREATED,
    operation_id="eln_create_project",
)
def create_project(data: ProjectCreate, session: Session = Depends(get_session)) -> ProjectOut:
    return service.create_project(session, data)


@router.get("/projects/{project_id}", response_model=ProjectOut, operation_id="eln_get_project")
def get_project(project_id: int, session: Session = Depends(get_session)) -> ProjectOut:
    return service.get_project(session, project_id)


@router.get(
    "/projects/{project_id}/experiments",
    response_model=list[ExperimentSummary],
    operation_id="eln_list_experiments",
)
def list_experiments(
    project_id: int, session: Session = Depends(get_session)
) -> list[ExperimentSummary]:
    return service.list_experiments(session, project_id)


@router.post(
    "/projects/{project_id}/experiments",
    response_model=ExperimentOut,
    status_code=status.HTTP_201_CREATED,
    operation_id="eln_create_experiment",
)
def create_experiment(
    project_id: int, data: ExperimentCreate, session: Session = Depends(get_session)
) -> ExperimentOut:
    return service.create_experiment(session, project_id, data)


@router.get(
    "/experiments/{experiment_id}", response_model=ExperimentOut, operation_id="eln_get_experiment"
)
def get_experiment(experiment_id: int, session: Session = Depends(get_session)) -> ExperimentOut:
    return service.get_experiment(session, experiment_id)


@router.get(
    "/experiments/{experiment_id}/datasets",
    response_model=list[DatasetOut],
    operation_id="eln_list_datasets",
)
def list_datasets(experiment_id: int, session: Session = Depends(get_session)) -> list[DatasetOut]:
    return service.list_datasets(session, experiment_id)


@router.post(
    "/experiments/{experiment_id}/datasets",
    response_model=DatasetOut,
    status_code=status.HTTP_201_CREATED,
    operation_id="eln_create_dataset",
)
def create_dataset(
    experiment_id: int, data: DatasetCreate, session: Session = Depends(get_session)
) -> DatasetOut:
    return service.create_dataset(session, experiment_id, data)


@router.get(
    "/datasets/{dataset_id}", response_model=DatasetPreview, operation_id="eln_preview_dataset"
)
def preview_dataset(
    dataset_id: int,
    limit: int = Query(default=50, ge=1, le=1000),
    session: Session = Depends(get_session),
) -> DatasetPreview:
    return service.preview_dataset(session, dataset_id, limit)


@router.get(
    "/datasets/{dataset_id}/content",
    response_class=PlainTextResponse,
    operation_id="eln_get_dataset_content",
    responses={200: {"content": {"text/csv": {}}}},
)
def get_dataset_content(dataset_id: int, session: Session = Depends(get_session)) -> str:
    return service.get_dataset_content(session, dataset_id)
