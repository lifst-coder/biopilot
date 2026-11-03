"""ELN service: creation, auditing, CSV validation and immutability of originals."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy.orm import Session

from app.core.audit import list_events
from app.core.errors import ImmutableRecordError, NotFoundError, ValidationFailedError
from app.eln import service
from app.eln.models import Dataset, Experiment
from app.eln.schemas import ConditionBlock, DatasetCreate, ExperimentCreate, ProjectCreate

CAL_CSV = (
    "injection_id,level_ng_ml,analyte,analyte_area,is_area\n"
    "CAL-01,5,x,100,1000\nCAL-02,10,x,200,1000\n"
)


def _experiment(code: str = "#100", parent: int | None = None) -> ExperimentCreate:
    return ExperimentCreate(
        code=code,
        title="t",
        performed_on=date(2026, 1, 1),
        parent_experiment_id=parent,
        raw_note="original note",
        condition_block=ConditionBlock(extraction_time_min=10, custom_key="kept"),  # type: ignore[call-arg]
    )


@pytest.fixture
def project_id(session: Session) -> int:
    return service.create_project(session, ProjectCreate(name="P")).id


def test_create_experiment_is_audited_and_keeps_extra_condition_keys(
    session: Session, project_id: int
) -> None:
    exp = service.create_experiment(session, project_id, _experiment())
    assert exp.condition_block.model_dump(exclude_none=True) == {
        "extraction_time_min": 10.0,
        "custom_key": "kept",
    }
    events = list_events(session, entity_type="eln.Experiment", entity_id=exp.id)
    assert [e.action for e in events] == ["create"]
    assert service.get_project(session, project_id).experiment_count == 1


def test_duplicate_code_rejected(session: Session, project_id: int) -> None:
    service.create_experiment(session, project_id, _experiment())
    with pytest.raises(ValidationFailedError):
        service.create_experiment(session, project_id, _experiment())


def test_parent_must_be_in_same_project(session: Session, project_id: int) -> None:
    other = service.create_project(session, ProjectCreate(name="Other"))
    parent = service.create_experiment(session, other.id, _experiment("#1"))
    with pytest.raises(ValidationFailedError):
        service.create_experiment(session, project_id, _experiment("#2", parent=parent.id))


def test_missing_entities_raise_not_found(session: Session) -> None:
    with pytest.raises(NotFoundError):
        service.get_experiment(session, 999)
    with pytest.raises(NotFoundError):
        service.get_dataset(session, 999)


def test_dataset_roundtrip_and_hash(session: Session, project_id: int) -> None:
    exp = service.create_experiment(session, project_id, _experiment())
    ds = service.create_dataset(
        session, exp.id, DatasetCreate(kind="calibration", filename="c.csv", content=CAL_CSV)
    )
    assert ds.row_count == 2
    assert service.get_dataset_content(session, ds.id) == CAL_CSV
    assert len(ds.sha256) == 64
    preview = service.preview_dataset(session, ds.id, limit=1)
    assert preview.truncated is True and preview.rows[0]["analyte"] == "x"
    assert service.get_experiment(session, exp.id).dataset_kinds == ["calibration"]


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("injection_id,level_ng_ml\nA,1\n", "필수 컬럼 누락"),
        (CAL_CSV.replace("100,1000", "abc,1000"), "숫자가 아님"),
        ("injection_id,level_ng_ml,analyte,analyte_area,is_area\n", "데이터 행이 없습니다"),
    ],
)
def test_invalid_csv_rejected(
    session: Session, project_id: int, content: str, message: str
) -> None:
    exp = service.create_experiment(session, project_id, _experiment())
    with pytest.raises(ValidationFailedError, match=message):
        service.create_dataset(
            session, exp.id, DatasetCreate(kind="calibration", filename="c.csv", content=content)
        )


def test_raw_note_and_conditions_are_immutable(session: Session, project_id: int) -> None:
    exp = service.create_experiment(session, project_id, _experiment())
    session.commit()
    row = session.get(Experiment, exp.id)
    assert row is not None
    row.raw_note = "edited"
    with pytest.raises(ImmutableRecordError, match="raw_note"):
        session.flush()
    session.rollback()
    row = session.get(Experiment, exp.id)
    assert row is not None
    row.condition_block = {"ph": 7}
    with pytest.raises(ImmutableRecordError, match="condition_block"):
        session.flush()
    session.rollback()


def test_experiment_title_is_mutable_but_datasets_are_not(
    session: Session, project_id: int
) -> None:
    exp = service.create_experiment(session, project_id, _experiment())
    ds = service.create_dataset(
        session, exp.id, DatasetCreate(kind="calibration", filename="c.csv", content=CAL_CSV)
    )
    session.commit()
    row = session.get(Experiment, exp.id)
    assert row is not None
    row.title = "renamed"
    session.flush()  # title is not an original-record field
    ds_row = session.get(Dataset, ds.id)
    assert ds_row is not None
    session.delete(ds_row)
    with pytest.raises(ImmutableRecordError):
        session.flush()
    session.rollback()
