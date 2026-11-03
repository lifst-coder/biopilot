"""ELN service — the only entry point other modules may use to read ELN data.

All functions take an explicit SQLAlchemy ``Session`` and return Pydantic DTOs from
:mod:`app.eln.schemas` (never ORM objects) so callers cannot mutate originals.
Every write records an :class:`~app.core.audit.AuditEvent` in the same transaction.
"""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from datetime import UTC, date, datetime
from typing import Any, cast

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.core.audit import Actor, AuditEvent, AuditEventOut, record_event
from app.core.errors import ImmutableRecordError, NotFoundError, ValidationFailedError
from app.eln import conditions, converters, csv_ingest, storage
from app.eln.models import (
    AttachmentFile,
    ConditionTemplate,
    Dataset,
    Experiment,
    ExperimentAddendum,
    ExperimentRevision,
    Project,
    ProtocolTemplate,
)
from app.eln.schemas import (
    DATASET_KIND_REGISTRY,
    Attachment,
    AttachmentFileOut,
    ConditionBlock,
    ConditionCheck,
    ConditionField,
    ConditionRule,
    ConditionTemplateCreate,
    ConditionTemplateOut,
    CsvIssue,
    DatasetCreate,
    DatasetKind,
    DatasetKindSpec,
    DatasetOut,
    DatasetPreview,
    DatasetValidation,
    ExperimentAddendumCreate,
    ExperimentAddendumOut,
    ExperimentCreate,
    ExperimentDraft,
    ExperimentHistory,
    ExperimentMetadataUpdate,
    ExperimentOut,
    ExperimentSummary,
    HistoryEntry,
    HistoryKind,
    ImportFormat,
    ImportPreview,
    ProjectCreate,
    ProjectOut,
    ProtocolTemplateCreate,
    ProtocolTemplateList,
    ProtocolTemplateOut,
    kind_spec,
)

#: Experiment fields that may be corrected through :func:`update_metadata`.
MUTABLE_EXPERIMENT_FIELDS: tuple[str, ...] = ("title", "author")


def list_condition_fields() -> list[ConditionField]:
    """Known condition-block keys with Korean labels, units and input types."""
    return conditions.condition_fields()


def list_dataset_kinds() -> list[DatasetKindSpec]:
    """Every published ``kind@version`` contract (ELN-7)."""
    return [spec for versions in DATASET_KIND_REGISTRY.values() for spec in versions]


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


# ------------------------------------------------------- condition template


def get_condition_template(session: Session, project_id: int) -> ConditionTemplateOut:
    """Latest stored template of a project, or the built-in default (version 0)."""
    get_project(session, project_id)
    row = session.scalars(
        select(ConditionTemplate)
        .where(ConditionTemplate.project_id == project_id)
        .order_by(ConditionTemplate.version.desc())
        .limit(1)
    ).first()
    if row is None:
        return ConditionTemplateOut(
            id=None,
            project_id=project_id,
            version=0,
            source="default",
            rules=list(conditions.DEFAULT_RULES),
            note="기본 템플릿 (QuEChERS·LC-MS/MS)",
            created_at=None,
        )
    return ConditionTemplateOut(
        id=row.id,
        project_id=project_id,
        version=row.version,
        source="project",
        rules=[ConditionRule.model_validate(r) for r in row.rules],
        note=row.note,
        created_at=row.created_at,
    )


def create_condition_template(
    session: Session, project_id: int, data: ConditionTemplateCreate, *, actor: Actor = "user"
) -> ConditionTemplateOut:
    """Store a new template version for a project (previous versions stay intact)."""
    current = get_condition_template(session, project_id)
    keys = [r.key for r in data.rules]
    if len(keys) != len(set(keys)):
        raise ValidationFailedError("템플릿에 같은 키가 두 번 있습니다")
    for rule in data.rules:
        if rule.min is not None and rule.max is not None and rule.min > rule.max:
            raise ValidationFailedError(f"{rule.key}: min > max")
    row = ConditionTemplate(
        project_id=project_id,
        version=current.version + 1,
        rules=[r.model_dump(exclude_none=True) for r in data.rules],
        note=data.note,
    )
    session.add(row)
    session.flush()
    record_event(
        session,
        actor=actor,
        action="create",
        entity_type="eln.ConditionTemplate",
        entity_id=row.id,
        project_id=project_id,
        payload={"version": row.version, "keys": keys},
    )
    return get_condition_template(session, project_id)


def check_conditions(session: Session, project_id: int, block: ConditionBlock) -> ConditionCheck:
    """Validate a condition block against the project's effective template (no write)."""
    template = get_condition_template(session, project_id)
    issues = conditions.check_conditions(block.model_dump(exclude_none=True), template.rules)
    return ConditionCheck(
        ok=not any(i.level == "error" for i in issues),
        template_version=template.version,
        template_source=template.source,
        issues=issues,
    )


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


def _revision_count(session: Session, experiment_id: int) -> int:
    count = session.scalar(
        select(func.count())
        .select_from(ExperimentRevision)
        .where(ExperimentRevision.experiment_id == experiment_id)
    )
    return 1 + (count or 0)


def _file_out(row: AttachmentFile) -> AttachmentFileOut:
    return AttachmentFileOut.model_validate(row).model_copy(
        update={"download_url": f"/api/eln/attachment-files/{row.id}/content"}
    )


def _to_out(session: Session, exp: Experiment, kinds: list[DatasetKind]) -> ExperimentOut:
    addenda = session.scalars(
        select(ExperimentAddendum)
        .where(ExperimentAddendum.experiment_id == exp.id)
        .order_by(ExperimentAddendum.id)
    )
    files = session.scalars(
        select(AttachmentFile)
        .where(AttachmentFile.experiment_id == exp.id)
        .order_by(AttachmentFile.id)
    )
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
        cloned_from_experiment_id=exp.cloned_from_experiment_id,
        protocol_template_id=exp.protocol_template_id,
        revision=_revision_count(session, exp.id),
        addenda=[ExperimentAddendumOut.model_validate(a) for a in addenda],
        attachment_files=[_file_out(f) for f in files],
    )


def _experiment_query(
    project_id: int,
    *,
    performed_from: date | None = None,
    performed_to: date | None = None,
    author: str | None = None,
    dataset_kind: DatasetKind | None = None,
) -> Any:
    stmt = select(Experiment).where(Experiment.project_id == project_id)
    if performed_from is not None:
        stmt = stmt.where(Experiment.performed_on >= performed_from)
    if performed_to is not None:
        stmt = stmt.where(Experiment.performed_on <= performed_to)
    if author:
        stmt = stmt.where(Experiment.author == author)
    if dataset_kind is not None:
        stmt = stmt.where(
            Experiment.id.in_(select(Dataset.experiment_id).where(Dataset.kind == dataset_kind))
        )
    return stmt


def count_experiments(
    session: Session,
    project_id: int,
    *,
    performed_from: date | None = None,
    performed_to: date | None = None,
    author: str | None = None,
    dataset_kind: DatasetKind | None = None,
) -> int:
    """Number of experiments matching the filters of :func:`list_experiments`."""
    get_project(session, project_id)
    stmt = _experiment_query(
        project_id,
        performed_from=performed_from,
        performed_to=performed_to,
        author=author,
        dataset_kind=dataset_kind,
    )
    return int(session.scalar(select(func.count()).select_from(stmt.subquery())) or 0)


def list_experiments(
    session: Session,
    project_id: int,
    *,
    limit: int | None = None,
    offset: int = 0,
    performed_from: date | None = None,
    performed_to: date | None = None,
    author: str | None = None,
    dataset_kind: DatasetKind | None = None,
) -> list[ExperimentSummary]:
    """Experiments of a project ordered by date then code, optionally filtered/paged."""
    get_project(session, project_id)
    if offset < 0 or (limit is not None and limit < 0):
        raise ValidationFailedError("limit/offset must be non-negative")
    stmt = _experiment_query(
        project_id,
        performed_from=performed_from,
        performed_to=performed_to,
        author=author,
        dataset_kind=dataset_kind,
    ).order_by(Experiment.performed_on, Experiment.code, Experiment.id)
    if offset:
        stmt = stmt.offset(offset)
    if limit is not None:
        stmt = stmt.limit(limit)
    exps = list(session.scalars(stmt))
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
    return [_to_out(session, e, kinds.get(e.id, [])) for e in exps]


def _get_experiment_row(session: Session, experiment_id: int) -> Experiment:
    exp = session.get(Experiment, experiment_id)
    if exp is None:
        raise NotFoundError(f"Experiment {experiment_id} not found")
    return exp


def get_experiment(session: Session, experiment_id: int) -> ExperimentOut:
    """One experiment with originals; raises :class:`NotFoundError`."""
    exp = _get_experiment_row(session, experiment_id)
    return _to_out(session, exp, _dataset_kinds(session, [exp.id]).get(exp.id, []))


def _same_project(session: Session, experiment_id: int, project_id: int, what: str) -> None:
    other = _get_experiment_row(session, experiment_id)
    if other.project_id != project_id:
        raise ValidationFailedError(f"{what} experiment belongs to another project")


def create_experiment(
    session: Session, project_id: int, data: ExperimentCreate, *, actor: Actor = "user"
) -> ExperimentOut:
    """Record a new experiment (originals become immutable once flushed).

    The condition block is checked against the project template: errors raise
    :class:`ValidationFailedError` (400), warnings are returned in ``warnings``.
    """
    get_project(session, project_id)
    if data.parent_experiment_id is not None:
        _same_project(session, data.parent_experiment_id, project_id, "parent")
    if data.cloned_from_experiment_id is not None:
        _same_project(session, data.cloned_from_experiment_id, project_id, "cloned-from")
    if data.protocol_template_id is not None:
        template = session.get(ProtocolTemplate, data.protocol_template_id)
        if template is None or template.project_id != project_id:
            raise ValidationFailedError("protocol template not found in this project")
    duplicate = session.scalar(
        select(Experiment.id).where(
            Experiment.project_id == project_id, Experiment.code == data.code
        )
    )
    if duplicate is not None:
        raise ValidationFailedError(f"Experiment code {data.code} already exists in project")
    check = check_conditions(session, project_id, data.condition_block)
    if not check.ok:
        errors = [i.message for i in check.issues if i.level == "error"]
        raise ValidationFailedError("조건 블록 템플릿 위반: " + "; ".join(errors))
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
        cloned_from_experiment_id=data.cloned_from_experiment_id,
        protocol_template_id=data.protocol_template_id,
    )
    session.add(exp)
    session.flush()
    warnings = [i for i in check.issues if i.level == "warning"]
    payload: dict[str, Any] = {"code": exp.code}
    if data.parent_experiment_id is not None:
        payload["parent_experiment_id"] = data.parent_experiment_id
    if data.cloned_from_experiment_id is not None:
        payload["cloned_from_experiment_id"] = data.cloned_from_experiment_id
    if data.protocol_template_id is not None:
        payload["protocol_template_id"] = data.protocol_template_id
    if warnings:
        payload["template_version"] = check.template_version
        payload["warnings"] = [w.key for w in warnings]
    record_event(
        session,
        actor=actor,
        action="create",
        entity_type="eln.Experiment",
        entity_id=exp.id,
        project_id=project_id,
        payload=payload,
    )
    return get_experiment(session, exp.id).model_copy(update={"warnings": warnings})


def update_metadata(
    session: Session,
    experiment_id: int,
    data: ExperimentMetadataUpdate,
    *,
    actor: Actor = "user",
) -> ExperimentOut:
    """Correct ``title``/``author`` (ELN-3). Any other field → :class:`ImmutableRecordError`.

    Before/after values are stored as an :class:`ExperimentRevision` and in the audit
    payload, so earlier versions remain reconstructible.
    """
    exp = _get_experiment_row(session, experiment_id)
    extra = sorted((data.model_extra or {}).keys())
    if extra:
        protected = [k for k in extra if k in Experiment.__immutable_fields__ or k == "id"]
        if protected:
            raise ImmutableRecordError(
                f"Experiment fields are immutable: {', '.join(protected)} "
                "(원본은 수정할 수 없습니다 — 보충 기록(addendum)을 사용하세요)"
            )
        raise ValidationFailedError(f"unknown fields: {', '.join(extra)}")
    changes: dict[str, dict[str, Any]] = {}
    for name in MUTABLE_EXPERIMENT_FIELDS:
        new = getattr(data, name)
        if new is not None and new != getattr(exp, name):
            changes[name] = {"before": getattr(exp, name), "after": new}
    if not changes:
        raise ValidationFailedError("변경된 값이 없습니다")
    revision = _revision_count(session, experiment_id) + 1
    for name, change in changes.items():
        setattr(exp, name, change["after"])
    row = ExperimentRevision(
        experiment_id=experiment_id,
        revision=revision,
        changes=changes,
        reason=data.reason,
        actor=actor,
    )
    session.add(row)
    session.flush()
    record_event(
        session,
        actor=actor,
        action="update_metadata",
        entity_type="eln.Experiment",
        entity_id=experiment_id,
        project_id=exp.project_id,
        payload={
            "experiment_id": experiment_id,
            "revision": revision,
            "changes": changes,
            "reason": data.reason,
        },
    )
    return get_experiment(session, experiment_id)


def add_addendum(
    session: Session,
    experiment_id: int,
    data: ExperimentAddendumCreate,
    *,
    actor: Actor = "user",
) -> ExperimentAddendumOut:
    """Append an immutable supplementary note; the original ``raw_note`` is untouched."""
    exp = _get_experiment_row(session, experiment_id)
    if not data.note.strip():
        raise ValidationFailedError("보충 기록 내용이 비어 있습니다")
    row = ExperimentAddendum(experiment_id=experiment_id, note=data.note, author=data.author)
    session.add(row)
    session.flush()
    record_event(
        session,
        actor=actor,
        action="add_addendum",
        entity_type="eln.ExperimentAddendum",
        entity_id=row.id,
        project_id=exp.project_id,
        payload={"experiment_id": experiment_id, "author": data.author},
    )
    return ExperimentAddendumOut.model_validate(row)


# ------------------------------------------------------------- drafts/clone


def suggest_next_code(session: Session, project_id: int) -> str:
    """Next free ``#NNN`` code (max numeric code + 1, zero-padded to the widest code)."""
    codes = list(
        session.scalars(select(Experiment.code).where(Experiment.project_id == project_id))
    )
    numbers = [(int(m.group(1)), len(m.group(1))) for c in codes if (m := re.search(r"(\d+)$", c))]
    if not numbers:
        return "#001"
    value = max(n for n, _ in numbers) + 1
    width = max(w for _, w in numbers)
    candidate = f"#{value:0{width}d}"
    while candidate in codes:  # pragma: no cover - only with exotic code schemes
        value += 1
        candidate = f"#{value:0{width}d}"
    return candidate


def experiment_draft(
    session: Session,
    project_id: int,
    *,
    source_experiment_id: int | None = None,
    protocol_template_id: int | None = None,
    performed_on: date | None = None,
) -> ExperimentDraft:
    """Unsaved form prefill: blank, clone of an experiment, or from a protocol template.

    A clone copies conditions and note and, by default, becomes a child of the source.
    Nothing is written (no audit event) — the eventual create is audited.
    """
    get_project(session, project_id)
    if source_experiment_id is not None and protocol_template_id is not None:
        raise ValidationFailedError("source_experiment_id와 protocol_template_id 중 하나만")
    code = suggest_next_code(session, project_id)
    day = performed_on or date.today()
    if source_experiment_id is not None:
        src = get_experiment(session, source_experiment_id)
        if src.project_id != project_id:
            raise ValidationFailedError("source experiment belongs to another project")
        return ExperimentDraft(
            source="clone",
            suggested_code=code,
            draft=ExperimentCreate(
                code=code,
                title=f"{src.title} (복제)",
                author=src.author,
                performed_on=day,
                parent_experiment_id=src.id,
                raw_note=src.raw_note,
                condition_block=src.condition_block,
                cloned_from_experiment_id=src.id,
            ),
        )
    if protocol_template_id is not None:
        tpl = get_protocol_template(session, protocol_template_id)
        if tpl.project_id != project_id:
            raise ValidationFailedError("protocol template belongs to another project")
        return ExperimentDraft(
            source="template",
            suggested_code=code,
            draft=ExperimentCreate(
                code=code,
                title=tpl.name,
                author="",
                performed_on=day,
                parent_experiment_id=tpl.source_experiment_id,
                raw_note=tpl.raw_note_template,
                condition_block=tpl.condition_block,
                protocol_template_id=tpl.id,
            ),
        )
    return ExperimentDraft(
        source="blank",
        suggested_code=code,
        draft=ExperimentCreate(
            code=code,
            title="새 실험",
            performed_on=day,
            raw_note="목적:\n절차:\n관찰:\n- ",
            condition_block=ConditionBlock(),
        ),
    )


# ------------------------------------------------------- protocol templates


def _template_out(row: ProtocolTemplate) -> ProtocolTemplateOut:
    return ProtocolTemplateOut(
        id=row.id,
        project_id=row.project_id,
        name=row.name,
        version=row.version,
        description=row.description,
        raw_note_template=row.raw_note_template,
        condition_block=ConditionBlock.model_validate(row.condition_block),
        source_experiment_id=row.source_experiment_id,
        author=row.author,
        created_at=row.created_at,
    )


def create_protocol_template(
    session: Session, project_id: int, data: ProtocolTemplateCreate, *, actor: Actor = "user"
) -> ProtocolTemplateOut:
    """Save a protocol; when ``source_experiment_id`` is given, missing parts are copied."""
    get_project(session, project_id)
    note, block = data.raw_note_template, data.condition_block
    if data.source_experiment_id is not None:
        src = get_experiment(session, data.source_experiment_id)
        if src.project_id != project_id:
            raise ValidationFailedError("source experiment belongs to another project")
        note = src.raw_note if note is None else note
        block = src.condition_block if block is None else block
    if block is None:
        raise ValidationFailedError("condition_block 또는 source_experiment_id가 필요합니다")
    latest = session.scalar(
        select(func.max(ProtocolTemplate.version)).where(
            ProtocolTemplate.project_id == project_id, ProtocolTemplate.name == data.name
        )
    )
    row = ProtocolTemplate(
        project_id=project_id,
        name=data.name,
        version=(latest or 0) + 1,
        description=data.description,
        raw_note_template=note or "",
        condition_block=block.model_dump(exclude_none=True),
        source_experiment_id=data.source_experiment_id,
        author=data.author,
    )
    session.add(row)
    session.flush()
    record_event(
        session,
        actor=actor,
        action="create",
        entity_type="eln.ProtocolTemplate",
        entity_id=row.id,
        project_id=project_id,
        payload={
            "name": row.name,
            "version": row.version,
            "source_experiment_id": data.source_experiment_id,
        },
    )
    return _template_out(row)


def get_protocol_template(session: Session, template_id: int) -> ProtocolTemplateOut:
    """One protocol template version; raises :class:`NotFoundError`."""
    row = session.get(ProtocolTemplate, template_id)
    if row is None:
        raise NotFoundError(f"Protocol template {template_id} not found")
    return _template_out(row)


def list_protocol_templates(
    session: Session, project_id: int, *, all_versions: bool = False
) -> ProtocolTemplateList:
    """Templates of a project (latest version per name unless ``all_versions``)."""
    get_project(session, project_id)
    rows = list(
        session.scalars(
            select(ProtocolTemplate)
            .where(ProtocolTemplate.project_id == project_id)
            .order_by(ProtocolTemplate.name, ProtocolTemplate.version.desc())
        )
    )
    if not all_versions:
        seen: set[str] = set()
        latest: list[ProtocolTemplate] = []
        for row in rows:
            if row.name not in seen:
                seen.add(row.name)
                latest.append(row)
        rows = latest
    items = [_template_out(r) for r in rows]
    return ProtocolTemplateList(project_id=project_id, total=len(items), items=items)


# ---------------------------------------------------------------- datasets


def _spec_for(kind: DatasetKind, version: int | None) -> DatasetKindSpec:
    try:
        return kind_spec(kind, version)
    except KeyError as exc:
        raise ValidationFailedError(f"unknown dataset contract {kind}@{version}") from exc


def validate_csv_text(
    kind: DatasetKind,
    content: str,
    *,
    filename: str = "upload.csv",
    schema_version: int | None = None,
    encoding: str = "utf-8",
    preview_limit: int = 10,
) -> DatasetValidation:
    """Dry-run validation of CSV text (no write). Parse failures become issues."""
    spec = _spec_for(kind, schema_version)
    sha = hashlib.sha256(content.encode("utf-8")).hexdigest()
    try:
        frame = csv_ingest.parse_frame(content)
    except ValueError as exc:
        return DatasetValidation(
            ok=False,
            kind=kind,
            schema_ref=spec.ref,
            filename=filename,
            encoding=encoding,
            sha256=sha,
            row_count=0,
            columns=[],
            preview_rows=[],
            issues=[CsvIssue(level="error", code="parse_error", message=str(exc))],
        )
    issues = csv_ingest.validate_frame(frame, spec)
    return DatasetValidation(
        ok=not any(i.level == "error" for i in issues),
        kind=kind,
        schema_ref=spec.ref,
        filename=filename,
        encoding=encoding,
        sha256=sha,
        row_count=len(frame),
        columns=[str(c) for c in frame.columns],
        preview_rows=csv_ingest.records(frame, preview_limit),
        issues=issues,
    )


def _decode_upload(raw: bytes) -> tuple[str, str]:
    if len(raw) > csv_ingest.MAX_CSV_BYTES:
        raise ValidationFailedError(
            f"파일이 너무 큽니다 ({len(raw)} bytes > {csv_ingest.MAX_CSV_BYTES} bytes)"
        )
    if not raw.strip():
        raise ValidationFailedError("빈 파일입니다")
    try:
        return csv_ingest.decode_bytes(raw)
    except csv_ingest.DecodeError as exc:
        raise ValidationFailedError(str(exc)) from exc


def validate_csv_upload(
    kind: DatasetKind, filename: str, raw: bytes, *, schema_version: int | None = None
) -> DatasetValidation:
    """Dry-run validation of uploaded bytes (encoding detection + contract checks)."""
    text, encoding = _decode_upload(raw)
    return validate_csv_text(
        kind, text, filename=filename, schema_version=schema_version, encoding=encoding
    )


def _dataset_out(session: Session, row: Dataset) -> DatasetOut:
    successor = session.scalar(
        select(Dataset.id).where(Dataset.supersedes_dataset_id == row.id).order_by(Dataset.id)
    )
    return DatasetOut.model_validate(row).model_copy(
        update={
            "schema_ref": f"{row.kind}@{row.schema_version}",
            "superseded_by_dataset_id": successor,
        }
    )


def _store_dataset(
    session: Session,
    experiment_id: int,
    data: DatasetCreate,
    *,
    encoding: str,
    actor: Actor,
    source_attachment_id: int | None = None,
    audit_extra: dict[str, Any] | None = None,
) -> DatasetOut:
    exp = _get_experiment_row(session, experiment_id)
    if data.supersedes_dataset_id is not None:
        previous = session.get(Dataset, data.supersedes_dataset_id)
        if previous is None or previous.experiment_id != experiment_id:
            raise ValidationFailedError("supersedes_dataset_id is not a dataset of this experiment")
        if previous.kind != data.kind:
            raise ValidationFailedError("a re-upload must keep the dataset kind")
    report = validate_csv_text(
        data.kind,
        data.content,
        filename=data.filename,
        schema_version=data.schema_version,
        encoding=encoding,
        preview_limit=0,
    )
    if not report.ok:
        raise ValidationFailedError(csv_ingest.error_summary(report.issues))
    spec = _spec_for(data.kind, data.schema_version)
    dataset = Dataset(
        experiment_id=experiment_id,
        kind=data.kind,
        filename=data.filename,
        content=data.content,
        sha256=hashlib.sha256(data.content.encode("utf-8")).hexdigest(),
        row_count=report.row_count,
        columns=report.columns,
        schema_version=spec.version,
        source_encoding=encoding,
        supersedes_dataset_id=data.supersedes_dataset_id,
        source_attachment_id=source_attachment_id,
    )
    session.add(dataset)
    session.flush()
    payload: dict[str, Any] = {
        "experiment_id": experiment_id,
        "kind": data.kind,
        "sha256": dataset.sha256,
        "schema_ref": spec.ref,
        "filename": data.filename,
        "row_count": dataset.row_count,
    }
    if data.supersedes_dataset_id is not None:
        payload["supersedes_dataset_id"] = data.supersedes_dataset_id
    payload.update(audit_extra or {})
    record_event(
        session,
        actor=actor,
        action="reupload" if data.supersedes_dataset_id is not None else "create",
        entity_type="eln.Dataset",
        entity_id=dataset.id,
        project_id=exp.project_id,
        payload=payload,
    )
    return _dataset_out(session, dataset)


def create_dataset(
    session: Session, experiment_id: int, data: DatasetCreate, *, actor: Actor = "user"
) -> DatasetOut:
    """Validate and store a CSV dataset given as text (immutable)."""
    return _store_dataset(session, experiment_id, data, encoding="utf-8", actor=actor)


def upload_dataset(
    session: Session,
    experiment_id: int,
    *,
    kind: DatasetKind,
    filename: str,
    raw: bytes,
    schema_version: int | None = None,
    supersedes_dataset_id: int | None = None,
    actor: Actor = "user",
) -> DatasetOut:
    """Store an uploaded CSV file (UTF-8/CP949 auto-detected, size-limited, ELN-1)."""
    text, encoding = _decode_upload(raw)
    data = DatasetCreate(
        kind=kind,
        filename=filename or "upload.csv",
        content=text,
        schema_version=schema_version,
        supersedes_dataset_id=supersedes_dataset_id,
    )
    return _store_dataset(
        session,
        experiment_id,
        data,
        encoding=encoding,
        actor=actor,
        audit_extra={"source_sha256": hashlib.sha256(raw).hexdigest(), "encoding": encoding},
    )


def list_datasets(session: Session, experiment_id: int) -> list[DatasetOut]:
    """Datasets of one experiment in upload order."""
    _get_experiment_row(session, experiment_id)
    rows = session.scalars(
        select(Dataset).where(Dataset.experiment_id == experiment_id).order_by(Dataset.id)
    )
    return [_dataset_out(session, d) for d in rows]


def _get_dataset_row(session: Session, dataset_id: int) -> Dataset:
    dataset = session.get(Dataset, dataset_id)
    if dataset is None:
        raise NotFoundError(f"Dataset {dataset_id} not found")
    return dataset


def get_dataset(session: Session, dataset_id: int) -> DatasetOut:
    """Dataset metadata."""
    return _dataset_out(session, _get_dataset_row(session, dataset_id))


def get_dataset_content(session: Session, dataset_id: int) -> str:
    """Raw CSV text exactly as uploaded."""
    return _get_dataset_row(session, dataset_id).content


def preview_dataset(session: Session, dataset_id: int, limit: int = 50) -> DatasetPreview:
    """First ``limit`` rows parsed as records."""
    row = _get_dataset_row(session, dataset_id)
    frame = csv_ingest.parse_frame(row.content)
    return DatasetPreview(
        dataset=_dataset_out(session, row),
        rows=csv_ingest.records(frame, limit),
        truncated=len(frame) > limit,
    )


# --------------------------------------------------------- vendor import


def list_import_formats() -> list[ImportFormat]:
    """Supported instrument export layouts (ELN-9)."""
    return converters.list_formats()


def preview_import(
    kind: DatasetKind, layout: str, filename: str, raw: bytes, *, preview_limit: int = 10
) -> ImportPreview:
    """Convert a wide vendor file to the long contract and validate it (no write)."""
    text, encoding = _decode_upload(raw)
    try:
        frame = csv_ingest.parse_frame(text)
        long, analytes = converters.convert_wide(frame, layout, kind)
    except ValueError as exc:  # ConversionError is a ValueError
        raise ValidationFailedError(str(exc)) from exc
    converted = long.to_csv(index=False, lineterminator="\n")
    validation = validate_csv_text(
        kind,
        converted,
        filename=_converted_name(filename),
        encoding=encoding,
        preview_limit=preview_limit,
    )
    return ImportPreview(
        format=layout,
        kind=kind,
        analytes=analytes,
        source_rows=len(frame),
        converted_csv=converted,
        validation=validation,
    )


def _converted_name(filename: str) -> str:
    stem = filename.rsplit(".", 1)[0] if "." in filename else filename
    return f"{stem or 'import'}.long.csv"


def import_dataset(
    session: Session,
    experiment_id: int,
    *,
    kind: DatasetKind,
    layout: str,
    filename: str,
    raw: bytes,
    supersedes_dataset_id: int | None = None,
    actor: Actor = "user",
) -> DatasetOut:
    """Convert + store: original vendor file kept as an attachment, long CSV as dataset."""
    preview = preview_import(kind, layout, filename, raw, preview_limit=0)
    if not preview.validation.ok:
        raise ValidationFailedError(csv_ingest.error_summary(preview.validation.issues))
    original = store_attachment(
        session,
        experiment_id,
        name=filename or "import.csv",
        media_type="text/csv",
        description=f"장비 내보내기 원본 ({layout})",
        data=raw,
        actor=actor,
    )
    return _store_dataset(
        session,
        experiment_id,
        DatasetCreate(
            kind=kind,
            filename=preview.validation.filename,
            content=preview.converted_csv,
            supersedes_dataset_id=supersedes_dataset_id,
        ),
        encoding=preview.validation.encoding,
        actor=actor,
        source_attachment_id=original.id,
        audit_extra={"import_format": layout, "source_attachment_id": original.id},
    )


# -------------------------------------------------------------- attachments


def store_attachment(
    session: Session,
    experiment_id: int,
    *,
    name: str,
    media_type: str,
    data: bytes,
    description: str = "",
    actor: Actor = "user",
) -> AttachmentFileOut:
    """Store an attachment binary (content-addressed). Identical re-upload → same record."""
    exp = _get_experiment_row(session, experiment_id)
    if not data:
        raise ValidationFailedError("빈 파일입니다")
    if len(data) > storage.MAX_ATTACHMENT_BYTES:
        raise ValidationFailedError(
            f"첨부 파일이 너무 큽니다 (최대 {storage.MAX_ATTACHMENT_BYTES // (1024 * 1024)} MB)"
        )
    digest, written = storage.put_blob(data)
    existing = session.scalars(
        select(AttachmentFile).where(
            AttachmentFile.experiment_id == experiment_id,
            AttachmentFile.sha256 == digest,
            AttachmentFile.name == name,
        )
    ).first()
    if existing is not None:
        return _file_out(existing)
    row = AttachmentFile(
        experiment_id=experiment_id,
        name=name,
        media_type=media_type or "application/octet-stream",
        description=description,
        size_bytes=len(data),
        sha256=digest,
    )
    session.add(row)
    session.flush()
    record_event(
        session,
        actor=actor,
        action="attach_file",
        entity_type="eln.AttachmentFile",
        entity_id=row.id,
        project_id=exp.project_id,
        payload={
            "experiment_id": experiment_id,
            "name": name,
            "sha256": digest,
            "size_bytes": len(data),
            "blob_reused": not written,
        },
    )
    return _file_out(row)


def get_attachment_file(session: Session, file_id: int) -> tuple[AttachmentFileOut, bytes]:
    """Attachment metadata + bytes (sha256 verified on read)."""
    row = session.get(AttachmentFile, file_id)
    if row is None:
        raise NotFoundError(f"Attachment file {file_id} not found")
    try:
        data = storage.read_blob(row.sha256)
    except FileNotFoundError as exc:
        raise NotFoundError(f"Attachment blob {row.sha256[:12]} missing from storage") from exc
    if hashlib.sha256(data).hexdigest() != row.sha256:
        raise ValidationFailedError("stored attachment failed its sha256 check")
    return _file_out(row), data


# ------------------------------------------------------------ history/audit


def _utc(value: datetime) -> datetime:
    """SQLite returns naive datetimes; treat them as UTC so they compare with aware ones."""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def get_history(session: Session, experiment_id: int) -> ExperimentHistory:
    """Version history: creation, metadata revisions, addenda, datasets, attachments.

    Title/author shown per entry are the values in effect at that point, rebuilt
    backwards from the current row using each revision's before/after values.
    """
    exp = _get_experiment_row(session, experiment_id)
    revisions = list(
        session.scalars(
            select(ExperimentRevision)
            .where(ExperimentRevision.experiment_id == experiment_id)
            .order_by(ExperimentRevision.revision)
        )
    )
    state = {"title": exp.title, "author": exp.author}
    states: dict[int, dict[str, str]] = {len(revisions) + 1: dict(state)}
    for rev in reversed(revisions):
        for name, change in rev.changes.items():
            state[name] = change["before"]
        states[rev.revision - 1] = dict(state)

    def rev_at(when: datetime) -> int:
        current = 1
        for rev in revisions:
            if _utc(rev.created_at) <= when:
                current = rev.revision
        return current

    def entry(
        kind: HistoryKind, when: datetime, summary: str, ref_type: str, ref_id: int, **kw: Any
    ) -> None:
        when = _utc(when)
        revision = kw.pop("revision", None) or rev_at(when)
        entries.append(
            HistoryEntry(
                kind=kind,
                occurred_at=when,
                revision=revision,
                summary=summary,
                ref_type=ref_type,
                ref_id=ref_id,
                title=states[revision]["title"],
                author=states[revision]["author"],
                **kw,
            )
        )

    entries: list[HistoryEntry] = []
    entry("created", exp.created_at, f"{exp.code} 원본 기록", "eln.Experiment", exp.id, revision=1)
    for rev in revisions:
        fields = ", ".join(rev.changes)
        reason = f" — {rev.reason}" if rev.reason else ""
        entry(
            "metadata",
            rev.created_at,
            f"메타데이터 수정 ({fields}){reason}",
            "eln.ExperimentRevision",
            rev.id,
            revision=rev.revision,
            changes=rev.changes,
        )
    for add in session.scalars(
        select(ExperimentAddendum).where(ExperimentAddendum.experiment_id == experiment_id)
    ):
        entry("addendum", add.created_at, "보충 기록 추가", "eln.ExperimentAddendum", add.id)
    for ds in session.scalars(select(Dataset).where(Dataset.experiment_id == experiment_id)):
        verb = "재업로드" if ds.supersedes_dataset_id else "업로드"
        entry(
            "dataset",
            ds.created_at,
            f"데이터셋 {verb}: {ds.filename} ({ds.kind}@{ds.schema_version}, {ds.row_count}행)",
            "eln.Dataset",
            ds.id,
        )
    for f in session.scalars(
        select(AttachmentFile).where(AttachmentFile.experiment_id == experiment_id)
    ):
        entry("attachment", f.created_at, f"첨부 파일: {f.name}", "eln.AttachmentFile", f.id)
    entries.sort(key=lambda e: (e.occurred_at, e.ref_type != "eln.Experiment", e.ref_id))
    return ExperimentHistory(
        experiment_id=experiment_id, current_revision=len(revisions) + 1, entries=entries
    )


def list_experiment_audit(
    session: Session, experiment_id: int, *, limit: int = 200
) -> list[AuditEventOut]:
    """Audit events about an experiment and everything derived from it, newest first.

    Matches the experiment row itself plus any event whose payload names it
    (datasets, addenda, attachments, AI digests, analysis results, critiques).
    """
    exp = _get_experiment_row(session, experiment_id)
    stmt = (
        select(AuditEvent)
        .where(
            AuditEvent.project_id == exp.project_id,
            or_(
                and_(
                    AuditEvent.entity_type == "eln.Experiment",
                    AuditEvent.entity_id == experiment_id,
                ),
                AuditEvent.payload["experiment_id"].as_integer() == experiment_id,
            ),
        )
        .order_by(AuditEvent.id.desc())
        .limit(limit)
    )
    return [AuditEventOut.model_validate(e) for e in session.scalars(stmt)]
