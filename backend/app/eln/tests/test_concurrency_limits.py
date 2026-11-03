"""Concurrent metadata corrections (revision race) and CSV size caps (security review).

The revision race needs two real connections, so these tests use a file-backed SQLite
database instead of the shared in-memory one.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import AuditEvent
from app.core.config import Settings
from app.core.db import Database
from app.core.errors import ValidationFailedError
from app.eln import csv_ingest, service
from app.eln.models import ExperimentRevision
from app.eln.schemas import (
    ConditionBlock,
    DatasetCreate,
    ExperimentCreate,
    ExperimentMetadataUpdate,
    ProjectCreate,
)
from app.main import create_app

HEADER = "injection_id,level_ng_ml,analyte,analyte_area,is_area\n"


@pytest.fixture
def file_db(tmp_path: Path) -> Database:
    db = Database(f"sqlite:///{tmp_path / 'race.db'}")
    db.create_all()
    return db


def _experiment(db: Database) -> int:
    with db.session() as s:
        project = service.create_project(s, ProjectCreate(name="race"))
        exp = service.create_experiment(
            s,
            project.id,
            ExperimentCreate(
                code="#R1",
                title="원래 제목",
                author="a",
                performed_on=date(2026, 11, 1),
                raw_note="n",
                condition_block=ConditionBlock(),
            ),
        )
        s.commit()
        return exp.id


def _chain(db: Database, experiment_id: int) -> list[ExperimentRevision]:
    with db.session() as s:
        return list(
            s.scalars(
                select(ExperimentRevision)
                .where(ExperimentRevision.experiment_id == experiment_id)
                .order_by(ExperimentRevision.revision)
            )
        )


def _assert_consistent_chain(revisions: list[ExperimentRevision], first_title: str) -> None:
    """Revision numbers are 2..n+1 and each `before` is the previous `after`."""
    assert [r.revision for r in revisions] == list(range(2, len(revisions) + 2))
    title = first_title
    for r in revisions:
        assert r.changes["title"]["before"] == title
        title = r.changes["title"]["after"]


def test_lost_revision_race_is_retried_against_the_winner(
    file_db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A correction committed between our count and our insert → retry, not 500."""
    exp_id = _experiment(file_db)
    original = service._revision_count
    raced = False

    def stale_count(session: Session, experiment_id: int) -> int:
        nonlocal raced
        count = original(session, experiment_id)
        if not raced:  # another request wins the race right after we counted
            raced = True
            with file_db.session() as other:
                service.update_metadata(
                    other, experiment_id, ExperimentMetadataUpdate(title="경쟁 제목")
                )
                other.commit()
        return count

    monkeypatch.setattr(service, "_revision_count", stale_count)
    with file_db.session() as s:
        out = service.update_metadata_in_own_transaction(
            s, exp_id, ExperimentMetadataUpdate(title="내 제목", reason="오타")
        )
        s.commit()
    assert raced and out.title == "내 제목"
    revisions = _chain(file_db, exp_id)
    _assert_consistent_chain(revisions, "원래 제목")
    assert [r.changes["title"]["after"] for r in revisions] == ["경쟁 제목", "내 제목"]


def test_race_that_never_resolves_is_a_409(
    file_db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    exp_id = _experiment(file_db)
    monkeypatch.setattr(service, "_revision_count", lambda _s, _e: 0)  # always revision 1+1
    with file_db.session() as s:
        service.update_metadata(s, exp_id, ExperimentMetadataUpdate(title="v2"))
        s.commit()
    with file_db.session() as s, pytest.raises(service.RevisionConflictError):
        service.update_metadata_in_own_transaction(
            s, exp_id, ExperimentMetadataUpdate(title="v3"), attempts=2
        )


def test_rolled_back_correction_leaves_nothing_behind(file_db: Database) -> None:
    """All-or-nothing with its audit event (a pysqlite SAVEPOINT here used to commit on
    RELEASE, keeping the new title and revision without an audit event)."""
    exp_id = _experiment(file_db)
    with file_db.session() as s:
        service.update_metadata(s, exp_id, ExperimentMetadataUpdate(title="버려질 제목"))
        s.rollback()
    with file_db.session() as s:
        assert service.get_experiment(s, exp_id).title == "원래 제목"
        assert _chain(file_db, exp_id) == []
        actions = s.scalars(select(AuditEvent.action).where(AuditEvent.entity_id == exp_id))
        assert "update_metadata" not in list(actions)


@pytest.fixture
def file_client(tmp_path: Path) -> Iterator[TestClient]:
    url = f"sqlite:///{tmp_path / 'api.db'}"
    app = create_app(Settings(auto_seed=True, database_url=url), Database(url))
    with TestClient(app) as c:
        yield c


def test_concurrent_metadata_patches_all_succeed(file_client: TestClient) -> None:
    """Eight simultaneous PATCHes: no 500, unique revisions, an unbroken before/after chain."""
    project = file_client.get("/api/eln/projects").json()[0]["id"]
    exp = file_client.get(f"/api/eln/projects/{project}/experiments").json()[0]
    url = f"/api/eln/experiments/{exp['id']}/metadata"
    n = 8
    barrier = threading.Barrier(n)

    def patch(i: int) -> int:
        barrier.wait()
        return file_client.patch(url, json={"title": f"동시 수정 {i}"}).status_code

    with ThreadPoolExecutor(n) as pool:
        statuses = list(pool.map(patch, range(n)))
    assert statuses == [200] * n
    history = file_client.get(f"/api/eln/experiments/{exp['id']}/history").json()
    assert history["current_revision"] == n + 1
    revisions = [e for e in history["entries"] if e["kind"] == "metadata"]
    assert sorted(e["revision"] for e in revisions) == list(range(2, n + 2))
    audit = [
        e
        for e in file_client.get(
            "/api/audit", params={"entity_type": "eln.Experiment", "entity_id": exp["id"]}
        ).json()
        if e["action"] == "update_metadata"
    ]
    chain = sorted(audit, key=lambda e: e["payload"]["revision"])
    title = exp["title"]
    for e in chain:
        assert e["payload"]["changes"]["title"]["before"] == title
        title = e["payload"]["changes"]["title"]["after"]


# ------------------------------------------------------------------ CSV caps


def test_row_cap_is_enforced_without_reading_further() -> None:
    ok = HEADER + "C1,1,x,1,1\n" * csv_ingest.MAX_CSV_ROWS
    assert len(csv_ingest.parse_frame(ok)) == csv_ingest.MAX_CSV_ROWS
    with pytest.raises(ValueError, match="행이 너무 많습니다"):
        csv_ingest.parse_frame(ok + "C1,1,x,1,1\n")


def test_column_cap_is_checked_before_pandas() -> None:
    cols = csv_ingest.MAX_CSV_COLUMNS
    assert len(csv_ingest.parse_frame(",".join(f"c{i}" for i in range(cols)) + "\n").columns)
    wide = ",".join(f"c{i}" for i in range(50_000)) + "\n" + "1," * 49_999 + "1\n"
    with pytest.raises(ValueError, match="열이 너무 많습니다"):
        csv_ingest.parse_frame(wide)
    report = service.validate_csv_upload("calibration", "w.csv", wide.encode())
    assert not report.ok and report.issues[0].code == "parse_error"


def test_wide_validation_is_linear_in_columns() -> None:
    """The duplicate-column check used list.count per column (28 s for 5 000 columns)."""
    import time

    header = ",".join(f"c{i}" for i in range(csv_ingest.MAX_CSV_COLUMNS))
    start = time.perf_counter()
    service.validate_csv_text("calibration", header + "\n" + "1," * 999 + "1\n")
    assert time.perf_counter() - start < 2.0


def test_header_width_tolerates_unreadable_headers() -> None:
    assert csv_ingest.header_width("\n\na,b,c\n1,2,3\n") == 3
    assert csv_ingest.header_width("") == 0
    assert csv_ingest.header_width('"' + "x" * 200_000 + '"\n') in (0, 1)


def test_json_dataset_content_has_a_length_cap() -> None:
    with pytest.raises(ValueError, match="at most"):
        DatasetCreate(kind="calibration", filename="a.csv", content="x" * (5 * 1024 * 1024 + 1))


def test_stored_oversized_dataset_preview_is_a_400(
    session: Session, seeded: dict[str, int], monkeypatch: pytest.MonkeyPatch
) -> None:
    dataset = service.list_datasets(session, seeded["#024"])[0]
    monkeypatch.setattr(csv_ingest, "MAX_CSV_ROWS", 1)  # as if stored before the cap
    with pytest.raises(ValidationFailedError, match="행이 너무 많습니다"):
        service.preview_dataset(session, dataset.id)
