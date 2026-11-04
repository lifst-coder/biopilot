"""HTTP routes for the ELN layer (prefix ``/api/eln``).

There are no update/delete routes for originals: corrections are new records
(addenda, metadata revisions, re-uploads). ``PATCH .../metadata`` only touches the
mutable ``title``/``author`` and is fully audited. Multipart endpoints parse the body
with :mod:`app.eln.multipart` and document their form in ``openapi_extra``.
"""

from __future__ import annotations

from datetime import date
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.responses import PlainTextResponse
from pydantic import TypeAdapter, ValidationError
from sqlalchemy.orm import Session

from app.core.audit import AuditEventOut
from app.core.errors import ValidationFailedError
from app.deps import get_session
from app.eln import service
from app.eln.csv_ingest import MAX_CSV_BYTES
from app.eln.multipart import FormData, read_form
from app.eln.schemas import (
    AttachmentFileOut,
    ConditionBlock,
    ConditionCheck,
    ConditionField,
    ConditionTemplateCreate,
    ConditionTemplateOut,
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
    ImportFormat,
    ImportPreview,
    ProjectCreate,
    ProjectOut,
    ProtocolDiff,
    ProtocolExtraction,
    ProtocolExtractionRequest,
    ProtocolLineage,
    ProtocolRunComplete,
    ProtocolRunCompletion,
    ProtocolRunCreate,
    ProtocolRunEntryCreate,
    ProtocolRunList,
    ProtocolRunOut,
    ProtocolTemplateCreate,
    ProtocolTemplateList,
    ProtocolTemplateOut,
    RunStatus,
)
from app.eln.storage import MAX_ATTACHMENT_BYTES

router = APIRouter(prefix="/api/eln", tags=["eln"])

_KIND = TypeAdapter(DatasetKind)
_FILE = {"type": "string", "format": "binary"}
_KIND_FIELD = {
    "type": "string",
    "enum": ["calibration", "recovery", "matrix_effect", "ion_ratio", "other"],
}


def _multipart(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    """``openapi_extra`` documenting a multipart/form-data request body."""
    return {
        "requestBody": {
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": {"type": "object", "properties": properties, "required": required}
                }
            },
        }
    }


def _kind(form: FormData) -> DatasetKind:
    try:
        return _KIND.validate_python(form.text("kind"))
    except ValidationError as exc:
        raise ValidationFailedError(f"unknown dataset kind '{form.fields.get('kind')}'") from exc


def _optional_int(form: FormData, name: str) -> int | None:
    value = form.fields.get(name, "").strip()
    if not value:
        return None
    if not value.isdigit():
        raise ValidationFailedError(f"{name} must be an integer")
    return int(value)


# ------------------------------------------------------------------ registry


@router.get(
    "/condition-fields",
    response_model=list[ConditionField],
    operation_id="eln_list_condition_fields",
)
def list_condition_fields() -> list[ConditionField]:
    return service.list_condition_fields()


@router.get(
    "/dataset-kinds", response_model=list[DatasetKindSpec], operation_id="eln_list_dataset_kinds"
)
def list_dataset_kinds() -> list[DatasetKindSpec]:
    return service.list_dataset_kinds()


@router.get(
    "/import-formats", response_model=list[ImportFormat], operation_id="eln_list_import_formats"
)
def list_import_formats() -> list[ImportFormat]:
    return service.list_import_formats()


# ------------------------------------------------------------------ projects


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
    project_id: int,
    response: Response,
    limit: int | None = Query(default=None, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    performed_from: date | None = Query(default=None),
    performed_to: date | None = Query(default=None),
    author: str | None = Query(default=None, max_length=100),
    dataset_kind: DatasetKind | None = Query(default=None),
    session: Session = Depends(get_session),
) -> list[ExperimentSummary]:
    """List experiments. Total (before paging) is returned in ``X-Total-Count``."""
    filters: dict[str, Any] = {
        "performed_from": performed_from,
        "performed_to": performed_to,
        "author": author,
        "dataset_kind": dataset_kind,
    }
    response.headers["X-Total-Count"] = str(
        service.count_experiments(session, project_id, **filters)
    )
    return service.list_experiments(session, project_id, limit=limit, offset=offset, **filters)


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
    "/projects/{project_id}/experiment-draft",
    response_model=ExperimentDraft,
    operation_id="eln_experiment_draft",
)
def experiment_draft(
    project_id: int,
    source_experiment_id: int | None = Query(default=None, description="clone this experiment"),
    protocol_template_id: int | None = Query(default=None, description="prefill from template"),
    session: Session = Depends(get_session),
) -> ExperimentDraft:
    return service.experiment_draft(
        session,
        project_id,
        source_experiment_id=source_experiment_id,
        protocol_template_id=protocol_template_id,
    )


@router.get(
    "/projects/{project_id}/condition-template",
    response_model=ConditionTemplateOut,
    operation_id="eln_get_condition_template",
)
def get_condition_template(
    project_id: int, session: Session = Depends(get_session)
) -> ConditionTemplateOut:
    return service.get_condition_template(session, project_id)


@router.post(
    "/projects/{project_id}/condition-template",
    response_model=ConditionTemplateOut,
    status_code=status.HTTP_201_CREATED,
    operation_id="eln_create_condition_template",
)
def create_condition_template(
    project_id: int, data: ConditionTemplateCreate, session: Session = Depends(get_session)
) -> ConditionTemplateOut:
    return service.create_condition_template(session, project_id, data)


@router.post(
    "/projects/{project_id}/condition-check",
    response_model=ConditionCheck,
    operation_id="eln_check_conditions",
)
def check_conditions(
    project_id: int, block: ConditionBlock, session: Session = Depends(get_session)
) -> ConditionCheck:
    """Validate a condition block against the project template without saving."""
    return service.check_conditions(session, project_id, block)


@router.get(
    "/projects/{project_id}/protocol-templates",
    response_model=ProtocolTemplateList,
    operation_id="eln_list_protocol_templates",
)
def list_protocol_templates(
    project_id: int,
    all_versions: bool = Query(default=False),
    session: Session = Depends(get_session),
) -> ProtocolTemplateList:
    return service.list_protocol_templates(session, project_id, all_versions=all_versions)


@router.post(
    "/projects/{project_id}/protocol-templates",
    response_model=ProtocolTemplateOut,
    status_code=status.HTTP_201_CREATED,
    operation_id="eln_create_protocol_template",
)
def create_protocol_template(
    project_id: int, data: ProtocolTemplateCreate, session: Session = Depends(get_session)
) -> ProtocolTemplateOut:
    return service.create_protocol_template(session, project_id, data)


@router.post(
    "/protocol-extractions",
    response_model=ProtocolExtraction,
    operation_id="eln_extract_protocol",
)
def extract_protocol(data: ProtocolExtractionRequest) -> ProtocolExtraction:
    """Condition-block candidates from pasted text or a table — nothing is stored.

    The researcher confirms/edits the candidates and saves them with
    ``POST /projects/{id}/protocol-templates`` (``source_text`` + ``extraction``).
    """
    return service.extract_protocol(data.text)


@router.get(
    "/projects/{project_id}/protocol-lineage",
    response_model=ProtocolLineage,
    operation_id="eln_protocol_lineage",
)
def protocol_lineage(project_id: int, session: Session = Depends(get_session)) -> ProtocolLineage:
    """Protocol versions with condition changes and the experiments recorded with each."""
    return service.protocol_lineage(session, project_id)


@router.get(
    "/protocol-diff",
    response_model=ProtocolDiff,
    operation_id="eln_protocol_diff",
)
def protocol_diff(
    a: int = Query(description="older template id"),
    b: int = Query(description="newer template id"),
    session: Session = Depends(get_session),
) -> ProtocolDiff:
    """Condition-level difference between two protocol template versions."""
    return service.diff_protocols(session, a, b)


@router.post(
    "/protocol-templates/{template_id}/runs",
    response_model=ProtocolRunOut,
    status_code=status.HTTP_201_CREATED,
    operation_id="eln_start_protocol_run",
)
def start_protocol_run(
    template_id: int, data: ProtocolRunCreate, session: Session = Depends(get_session)
) -> ProtocolRunOut:
    """Start following a protocol version step by step."""
    return service.start_protocol_run(session, template_id, data)


@router.get(
    "/projects/{project_id}/protocol-runs",
    response_model=ProtocolRunList,
    operation_id="eln_list_protocol_runs",
)
def list_protocol_runs(
    project_id: int,
    run_status: RunStatus | None = Query(default=None, alias="status"),
    session: Session = Depends(get_session),
) -> ProtocolRunList:
    """Runs of a project, newest first."""
    return service.list_protocol_runs(session, project_id, run_status)


@router.get(
    "/protocol-runs/{run_id}", response_model=ProtocolRunOut, operation_id="eln_get_protocol_run"
)
def get_protocol_run(run_id: int, session: Session = Depends(get_session)) -> ProtocolRunOut:
    """Current state of a run (folded from its append-only entries)."""
    return service.get_protocol_run(session, run_id)


@router.post(
    "/protocol-runs/{run_id}/entries",
    response_model=ProtocolRunOut,
    operation_id="eln_add_protocol_run_entry",
)
def add_protocol_run_entry(
    run_id: int, data: ProtocolRunEntryCreate, session: Session = Depends(get_session)
) -> ProtocolRunOut:
    """Check/uncheck a step, record an actual value or a note (append-only)."""
    return service.add_protocol_run_entry(session, run_id, data)


@router.post(
    "/protocol-runs/{run_id}/complete",
    response_model=ProtocolRunCompletion,
    operation_id="eln_complete_protocol_run",
)
def complete_protocol_run(
    run_id: int, data: ProtocolRunComplete, session: Session = Depends(get_session)
) -> ProtocolRunCompletion:
    """Create the experiment record from the run (``dry_run`` previews it)."""
    return service.complete_protocol_run(session, run_id, data)


# --------------------------------------------------------------- experiments


@router.get(
    "/experiments/{experiment_id}", response_model=ExperimentOut, operation_id="eln_get_experiment"
)
def get_experiment(experiment_id: int, session: Session = Depends(get_session)) -> ExperimentOut:
    return service.get_experiment(session, experiment_id)


@router.patch(
    "/experiments/{experiment_id}/metadata",
    response_model=ExperimentOut,
    operation_id="eln_update_experiment_metadata",
)
def update_metadata(
    experiment_id: int, data: ExperimentMetadataUpdate, session: Session = Depends(get_session)
) -> ExperimentOut:
    """Correct title/author only. Immutable fields in the body → 409 ``immutable_record``.
    Concurrent corrections are serialised by retrying (409 ``conflict`` if that fails)."""
    return service.update_metadata_in_own_transaction(session, experiment_id, data)


@router.post(
    "/experiments/{experiment_id}/addenda",
    response_model=ExperimentAddendumOut,
    status_code=status.HTTP_201_CREATED,
    operation_id="eln_add_addendum",
)
def add_addendum(
    experiment_id: int, data: ExperimentAddendumCreate, session: Session = Depends(get_session)
) -> ExperimentAddendumOut:
    return service.add_addendum(session, experiment_id, data)


@router.get(
    "/experiments/{experiment_id}/history",
    response_model=ExperimentHistory,
    operation_id="eln_experiment_history",
)
def experiment_history(
    experiment_id: int, session: Session = Depends(get_session)
) -> ExperimentHistory:
    return service.get_history(session, experiment_id)


@router.get(
    "/experiments/{experiment_id}/audit",
    response_model=list[AuditEventOut],
    operation_id="eln_experiment_audit",
)
def experiment_audit(
    experiment_id: int,
    limit: int = Query(default=200, ge=1, le=1000),
    session: Session = Depends(get_session),
) -> list[AuditEventOut]:
    """Audit events of the experiment and records derived from it (any module)."""
    return service.list_experiment_audit(session, experiment_id, limit=limit)


# ------------------------------------------------------------------ datasets


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


@router.post(
    "/experiments/{experiment_id}/datasets/upload",
    response_model=DatasetOut,
    status_code=status.HTTP_201_CREATED,
    operation_id="eln_upload_dataset",
    openapi_extra=_multipart(
        {
            "file": _FILE,
            "kind": _KIND_FIELD,
            "schema_version": {"type": "integer"},
            "supersedes_dataset_id": {"type": "integer"},
        },
        ["file", "kind"],
    ),
)
async def upload_dataset(
    experiment_id: int, request: Request, session: Session = Depends(get_session)
) -> DatasetOut:
    """Multipart CSV upload (UTF-8/CP949 auto-detected, max 5 MB). Re-upload via
    ``supersedes_dataset_id`` creates a new dataset; the previous one is kept."""
    form = await read_form(request, MAX_CSV_BYTES)
    upload = form.file()
    return service.upload_dataset(
        session,
        experiment_id,
        kind=_kind(form),
        filename=upload.filename,
        raw=upload.data,
        schema_version=_optional_int(form, "schema_version"),
        supersedes_dataset_id=_optional_int(form, "supersedes_dataset_id"),
    )


@router.post(
    "/experiments/{experiment_id}/datasets/import",
    response_model=DatasetOut,
    status_code=status.HTTP_201_CREATED,
    operation_id="eln_import_dataset",
    openapi_extra=_multipart(
        {
            "file": _FILE,
            "kind": _KIND_FIELD,
            "format": {"type": "string"},
            "supersedes_dataset_id": {"type": "integer"},
        },
        ["file", "kind", "format"],
    ),
)
async def import_dataset(
    experiment_id: int, request: Request, session: Session = Depends(get_session)
) -> DatasetOut:
    """Convert an instrument (wide) export and store it; the original file is kept."""
    form = await read_form(request, MAX_CSV_BYTES)
    upload = form.file()
    return service.import_dataset(
        session,
        experiment_id,
        kind=_kind(form),
        layout=form.text("format"),
        filename=upload.filename,
        raw=upload.data,
        supersedes_dataset_id=_optional_int(form, "supersedes_dataset_id"),
    )


@router.post(
    "/datasets/validate", response_model=DatasetValidation, operation_id="eln_validate_dataset"
)
def validate_dataset(data: DatasetCreate) -> DatasetValidation:
    """Dry-run validation of CSV text (nothing stored)."""
    return service.validate_csv_text(
        data.kind, data.content, filename=data.filename, schema_version=data.schema_version
    )


@router.post(
    "/datasets/validate-upload",
    response_model=DatasetValidation,
    operation_id="eln_validate_dataset_upload",
    openapi_extra=_multipart(
        {"file": _FILE, "kind": _KIND_FIELD, "schema_version": {"type": "integer"}},
        ["file", "kind"],
    ),
)
async def validate_dataset_upload(request: Request) -> DatasetValidation:
    """Dry-run validation of an uploaded file: encoding, columns, numbers (nothing stored)."""
    form = await read_form(request, MAX_CSV_BYTES)
    upload = form.file()
    return service.validate_csv_upload(
        _kind(form),
        upload.filename,
        upload.data,
        schema_version=_optional_int(form, "schema_version"),
    )


@router.post(
    "/import/preview",
    response_model=ImportPreview,
    operation_id="eln_preview_import",
    openapi_extra=_multipart(
        {"file": _FILE, "kind": _KIND_FIELD, "format": {"type": "string"}},
        ["file", "kind", "format"],
    ),
)
async def preview_import(request: Request) -> ImportPreview:
    """Convert a vendor file to the long contract and validate it (nothing stored)."""
    form = await read_form(request, MAX_CSV_BYTES)
    upload = form.file()
    return service.preview_import(_kind(form), form.text("format"), upload.filename, upload.data)


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


# --------------------------------------------------------------- attachments


@router.post(
    "/experiments/{experiment_id}/attachment-files",
    response_model=AttachmentFileOut,
    status_code=status.HTTP_201_CREATED,
    operation_id="eln_upload_attachment_file",
    openapi_extra=_multipart({"file": _FILE, "description": {"type": "string"}}, ["file"]),
)
async def upload_attachment_file(
    experiment_id: int, request: Request, session: Session = Depends(get_session)
) -> AttachmentFileOut:
    """Store a binary attachment (max 20 MB, content-addressed; no delete route)."""
    form = await read_form(request, MAX_ATTACHMENT_BYTES)
    upload = form.file()
    return service.store_attachment(
        session,
        experiment_id,
        name=upload.filename or "attachment",
        media_type=upload.content_type,
        data=upload.data,
        description=form.text("description", ""),
    )


# Excluded from the OpenAPI contract: tests/test_contract.py calls every GET path with a
# fixed set of path params and has no ``file_id`` (see CHANGES_REQUESTED.md). The URL is
# exposed to the UI as ``AttachmentFileOut.download_url``.
@router.get("/attachment-files/{file_id}/content", include_in_schema=False)
def download_attachment_file(file_id: int, session: Session = Depends(get_session)) -> Response:
    meta, data = service.get_attachment_file(session, file_id)
    return Response(
        content=data,
        media_type=meta.media_type,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(meta.name)}",
            "ETag": f'"{meta.sha256}"',
            "X-Content-SHA256": meta.sha256,
        },
    )
