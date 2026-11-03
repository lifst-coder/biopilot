"""ELN service — the only entry point other modules may use to read ELN data.

All functions take an explicit SQLAlchemy ``Session`` and return Pydantic DTOs from
:mod:`app.eln.schemas` (never ORM objects) so callers cannot mutate originals.
"""

from __future__ import annotations

import hashlib
import io
from collections import defaultdict
from typing import cast

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.audit import Actor, record_event
from app.core.errors import NotFoundError, ValidationFailedError
from app.eln.models import Dataset, Experiment, Project
from app.eln.schemas import (
    CONDITION_FIELD_LABELS,
    DATASET_COLUMNS,
    DATASET_NUMERIC_COLUMNS,
    Attachment,
    ConditionBlock,
    ConditionField,
    DatasetCreate,
    DatasetKind,
    DatasetOut,
    DatasetPreview,
    ExperimentCreate,
    ExperimentOut,
    ExperimentSummary,
    ProjectCreate,
    ProjectOut,
)


def list_condition_fields() -> list[ConditionField]:
    """Known condition-block keys with Korean display labels (UI single source)."""
    return [ConditionField(key=k, label=v) for k, v in CONDITION_FIELD_LABELS.items()]


# ---------------------------------------------------------------- projects


def list_projects(session: Session) -> list[ProjectOut]:
    """All projects with experiment counts, oldest first."""
    counts = dict(
        session.execute(
            select(Experiment.project_id, func.count()).group_by(Experiment.project_id)
        ).all()
    )
    projects = session.scalars(select(Project).order_by(Project.id))
    return [
        ProjectOut.model_validate(p).model_copy(update={"experiment_count": counts.get(p.id, 0)})
        for p in projects
    ]


def get_project(session: Session, project_id: int) -> ProjectOut:
    """One project; raises :class:`NotFoundError`."""
    project = session.get(Project, project_id)
    if project is None:
        raise NotFoundError(f"Project {project_id} not found")
    count = session.scalar(
        select(func.count()).select_from(Experiment).where(Experiment.project_id == project_id)
    )
    return ProjectOut.model_validate(project).model_copy(update={"experiment_count": count or 0})


def create_project(session: Session, data: ProjectCreate, *, actor: Actor = "user") -> ProjectOut:
    """Create a project and audit it."""
    project = Project(**data.model_dump())
    session.add(project)
    session.flush()
    record_event(
        session,
        actor=actor,
        action="create",
        entity_type="eln.Project",
        entity_id=project.id,
        project_id=project.id,
        payload={"name": project.name},
    )
    return get_project(session, project.id)


# ------------------------------------------------------------- experiments


def _dataset_kinds(session: Session, experiment_ids: list[int]) -> dict[int, list[DatasetKind]]:
    kinds: dict[int, list[DatasetKind]] = defaultdict(list)
    if not experiment_ids:
        return kinds
    rows = session.execute(
        select(Dataset.experiment_id, Dataset.kind)
        .where(Dataset.experiment_id.in_(experiment_ids))
        .order_by(Dataset.id)
    )
    for exp_id, kind in rows:
        if kind not in kinds[exp_id]:
            kinds[exp_id].append(cast(DatasetKind, kind))
    return kinds


def _to_summary(exp: Experiment, kinds: list[DatasetKind]) -> ExperimentSummary:
    return ExperimentSummary.model_validate(exp).model_copy(update={"dataset_kinds": kinds})


def _to_out(exp: Experiment, kinds: list[DatasetKind]) -> ExperimentOut:
    return ExperimentOut(
        id=exp.id,
        project_id=exp.project_id,
        code=exp.code,
        title=exp.title,
        author=exp.author,
        performed_on=exp.performed_on,
        parent_experiment_id=exp.parent_experiment_id,
        dataset_kinds=kinds,
        raw_note=exp.raw_note,
        condition_block=ConditionBlock.model_validate(exp.condition_block),
        attachments=[Attachment.model_validate(a) for a in exp.attachments],
        created_at=exp.created_at,
    )


def list_experiments(session: Session, project_id: int) -> list[ExperimentSummary]:
    """Experiments of a project ordered by date then code."""
    get_project(session, project_id)
    exps = list(
        session.scalars(
            select(Experiment)
            .where(Experiment.project_id == project_id)
            .order_by(Experiment.performed_on, Experiment.code)
        )
    )
    kinds = _dataset_kinds(session, [e.id for e in exps])
    return [_to_summary(e, kinds.get(e.id, [])) for e in exps]


def list_experiments_full(session: Session, project_id: int) -> list[ExperimentOut]:
    """Like :func:`list_experiments` but including originals (used by Memory)."""
    get_project(session, project_id)
    exps = list(
        session.scalars(
            select(Experiment)
            .where(Experiment.project_id == project_id)
            .order_by(Experiment.performed_on, Experiment.code)
        )
    )
    kinds = _dataset_kinds(session, [e.id for e in exps])
    return [_to_out(e, kinds.get(e.id, [])) for e in exps]


def get_experiment(session: Session, experiment_id: int) -> ExperimentOut:
    """One experiment with originals; raises :class:`NotFoundError`."""
    exp = session.get(Experiment, experiment_id)
    if exp is None:
        raise NotFoundError(f"Experiment {experiment_id} not found")
    return _to_out(exp, _dataset_kinds(session, [exp.id]).get(exp.id, []))


def create_experiment(
    session: Session, project_id: int, data: ExperimentCreate, *, actor: Actor = "user"
) -> ExperimentOut:
    """Record a new experiment (originals become immutable once flushed)."""
    get_project(session, project_id)
    if data.parent_experiment_id is not None:
        parent = get_experiment(session, data.parent_experiment_id)
        if parent.project_id != project_id:
            raise ValidationFailedError("parent experiment belongs to another project")
    duplicate = session.scalar(
        select(Experiment.id).where(
            Experiment.project_id == project_id, Experiment.code == data.code
        )
    )
    if duplicate is not None:
        raise ValidationFailedError(f"Experiment code {data.code} already exists in project")
    exp = Experiment(
        project_id=project_id,
        code=data.code,
        title=data.title,
        author=data.author,
        performed_on=data.performed_on,
        parent_experiment_id=data.parent_experiment_id,
        raw_note=data.raw_note,
        condition_block=data.condition_block.model_dump(exclude_none=True),
        attachments=[a.model_dump() for a in data.attachments],
    )
    session.add(exp)
    session.flush()
    record_event(
        session,
        actor=actor,
        action="create",
        entity_type="eln.Experiment",
        entity_id=exp.id,
        project_id=project_id,
        payload={"code": exp.code},
    )
    return get_experiment(session, exp.id)


# ---------------------------------------------------------------- datasets


def _validate_csv(kind: DatasetKind, content: str) -> pd.DataFrame:
    try:
        frame = pd.read_csv(io.StringIO(content))
    except (pd.errors.ParserError, pd.errors.EmptyDataError) as exc:
        raise ValidationFailedError(f"CSV could not be parsed: {exc}") from exc
    missing = [c for c in DATASET_COLUMNS[kind] if c not in frame.columns]
    if missing:
        raise ValidationFailedError(f"{kind} CSV is missing columns: {', '.join(missing)}")
    if frame.empty:
        raise ValidationFailedError("CSV has no data rows")
    for col in DATASET_NUMERIC_COLUMNS.intersection(frame.columns):
        if not pd.api.types.is_numeric_dtype(frame[col]):
            raise ValidationFailedError(f"column {col} must be numeric")
    return frame


def create_dataset(
    session: Session, experiment_id: int, data: DatasetCreate, *, actor: Actor = "user"
) -> DatasetOut:
    """Validate and store a CSV dataset (immutable)."""
    exp = get_experiment(session, experiment_id)
    frame = _validate_csv(data.kind, data.content)
    dataset = Dataset(
        experiment_id=experiment_id,
        kind=data.kind,
        filename=data.filename,
        content=data.content,
        sha256=hashlib.sha256(data.content.encode("utf-8")).hexdigest(),
        row_count=len(frame),
        columns=[str(c) for c in frame.columns],
    )
    session.add(dataset)
    session.flush()
    record_event(
        session,
        actor=actor,
        action="create",
        entity_type="eln.Dataset",
        entity_id=dataset.id,
        project_id=exp.project_id,
        payload={"experiment_id": experiment_id, "kind": data.kind, "sha256": dataset.sha256},
    )
    return DatasetOut.model_validate(dataset)


def list_datasets(session: Session, experiment_id: int) -> list[DatasetOut]:
    """Datasets of one experiment in upload order."""
    get_experiment(session, experiment_id)
    rows = session.scalars(
        select(Dataset).where(Dataset.experiment_id == experiment_id).order_by(Dataset.id)
    )
    return [DatasetOut.model_validate(d) for d in rows]


def _get_dataset_row(session: Session, dataset_id: int) -> Dataset:
    dataset = session.get(Dataset, dataset_id)
    if dataset is None:
        raise NotFoundError(f"Dataset {dataset_id} not found")
    return dataset


def get_dataset(session: Session, dataset_id: int) -> DatasetOut:
    """Dataset metadata."""
    return DatasetOut.model_validate(_get_dataset_row(session, dataset_id))


def get_dataset_content(session: Session, dataset_id: int) -> str:
    """Raw CSV text exactly as uploaded."""
    return _get_dataset_row(session, dataset_id).content


def preview_dataset(session: Session, dataset_id: int, limit: int = 50) -> DatasetPreview:
    """First ``limit`` rows parsed as records."""
    row = _get_dataset_row(session, dataset_id)
    frame = pd.read_csv(io.StringIO(row.content))
    records = frame.head(limit).to_dict(orient="records")
    return DatasetPreview(
        dataset=DatasetOut.model_validate(row),
        rows=[{str(k): v for k, v in r.items()} for r in records],
        truncated=len(frame) > limit,
    )
