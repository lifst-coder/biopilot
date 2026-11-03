"""Digests (MEM-6 grounding, MEM-8 staleness) and knowledge notes (MEM-7)."""

from __future__ import annotations

import pytest
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.audit import list_events
from app.core.errors import ImmutableRecordError, NotFoundError, ValidationFailedError
from app.eln import service as eln
from app.eln.schemas import DatasetCreate, ProjectCreate
from app.memory import service
from app.memory.grounding import numbers, ungrounded_numbers
from app.memory.models import KnowledgeNote
from app.memory.schemas import DigestDraft, KnowledgeNoteCreate


def test_grounding_allows_rounding_and_rejects_invented() -> None:
    src = ["회수율 61.976 %", "시간 10분", "#024"]
    assert ungrounded_numbers("평균 62.0% 이고 61.98 %", src) == []
    assert ungrounded_numbers("10분 → 5분 [F3]", src) == ["5"]
    assert ungrounded_numbers("#024 기준", src) == []
    assert numbers("1,5 와 2.25") == ["1.5", "2.25"]


def test_rules_digest_stored_audited_and_fresh(session: Session, seeded: dict[str, int]) -> None:
    digests = service.list_digests(session, seeded["#024"])
    assert len(digests) == 1 and digests[0].engine == "rules"
    assert digests[0].fallback_reason is None and not digests[0].stale
    assert "#018 대비 변경" in digests[0].summary
    assert any("IS" in p for p in digests[0].key_points)
    events = list_events(session, entity_type="memory.ExperimentDigest")
    assert len(events) == 7 and {e.actor for e in events} == {"ai:rules"}


def test_claude_digest_grounded_and_fallbacks(
    session: Session, seeded: dict[str, int], fake_gateway_factory
) -> None:
    def ok(schema: type[BaseModel], _prompt: str) -> BaseModel:
        return DigestDraft(summary="#024: 추출 5분, GCB 7.5 mg 사용", key_points=["관찰"])

    created = service.create_digest(session, seeded["#024"], gateway=fake_gateway_factory(ok))
    assert created.engine == "claude" and created.model == "fake-claude"
    assert created.fallback_reason is None

    def lie(schema: type[BaseModel], _prompt: str) -> BaseModel:
        return DigestDraft(summary="회수율 97.5%로 우수", key_points=["추출 77분"])

    replaced = service.create_digest(session, seeded["#024"], gateway=fake_gateway_factory(lie))
    assert replaced.engine == "rules" and replaced.model is None
    assert replaced.fallback_reason == "ungrounded_numbers: 97.5, 77"

    failing = fake_gateway_factory(lambda _s, _p: None)
    fallback = service.create_digest(session, seeded["#018"], gateway=failing)
    assert fallback.engine == "rules" and fallback.fallback_reason == "claude_unavailable"
    assert len(failing.calls) == 1
    assert service.get_digest(session, fallback.id).id == fallback.id
    with pytest.raises(NotFoundError):
        service.get_digest(session, 9999)


def test_digest_becomes_stale_after_dataset_added(session: Session, seeded: dict[str, int]) -> None:
    exp_id = seeded["#021"]
    before = service.list_digests(session, exp_id)[0]
    assert not before.stale and before.input_fingerprint
    content = "injection_id,level_ng_ml,analyte,analyte_area,is_area\nC-1,1,captan,10,100\n"
    eln.create_dataset(
        session, exp_id, DatasetCreate(kind="calibration", filename="c.csv", content=content)
    )
    after = service.list_digests(session, exp_id)
    assert after[0].id == before.id and after[0].stale
    fresh = service.create_digest(session, exp_id)
    assert not fresh.stale
    assert [d.stale for d in service.list_digests(session, exp_id)] == [False, True]


def test_knowledge_notes_create_list_validate(session: Session, seeded: dict[str, int]) -> None:
    pid = seeded["project"]
    note = service.create_knowledge_note(
        session,
        pid,
        KnowledgeNoteCreate(
            statement="GCB는 벤즈이미다졸계를 흡착한다",
            linked_experiment_ids=[seeded["#024"], seeded["#024"], seeded["#018"]],
            author="김연구",
        ),
    )
    assert note.linked_experiment_ids == [seeded["#024"], seeded["#018"]]
    listing = service.list_knowledge_notes(session, pid)
    assert listing.total == 1 and listing.items[0].id == note.id
    events = list_events(session, entity_type="memory.KnowledgeNote", entity_id=note.id)
    assert events and events[0].payload["linked_experiment_ids"] == note.linked_experiment_ids

    with pytest.raises(ValidationFailedError, match="does not exist"):
        service.create_knowledge_note(
            session, pid, KnowledgeNoteCreate(statement="x", linked_experiment_ids=[999])
        )
    other = eln.create_project(session, ProjectCreate(name="다른 프로젝트"))
    with pytest.raises(ValidationFailedError, match="another project"):
        service.create_knowledge_note(
            session,
            other.id,
            KnowledgeNoteCreate(statement="x", linked_experiment_ids=[seeded["#018"]]),
        )
    with pytest.raises(NotFoundError):
        service.list_knowledge_notes(session, 999)

    row = session.get(KnowledgeNote, note.id)
    assert row is not None
    row.statement = "수정"
    with pytest.raises(ImmutableRecordError):
        session.flush()
    session.rollback()
