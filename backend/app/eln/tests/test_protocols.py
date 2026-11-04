"""Protocols: paste → condition candidates → confirm → save; lineage; runs at the bench.

Principles under test: extraction never guesses (unrecognized keys stay empty), the pasted
text is stored unchanged as an original record, every write is audited, run progress is
append-only and a completed run becomes an ordinary experiment record.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.audit import list_events
from app.core.errors import ImmutableRecordError
from app.eln import protocols, service
from app.eln.models import ProtocolRunEntry, ProtocolTemplate
from app.eln.schemas import (
    DraftField,
    DraftStep,
    ExtractionSnapshot,
    ProtocolExtractionDraft,
    ProtocolRunComplete,
    ProtocolRunCreate,
    ProtocolRunEntryCreate,
    ProtocolTemplateCreate,
)

PASTE = """잔류농약 QuEChERS SOP
1. 균질화한 사과 10 g을 50 mL 원심관에 칭량한다.
2. 1% 아세트산 아세토니트릴 10 mL를 넣고 추출 10분 진탕한다.
3. 아세테이트 완충염 (AOAC 2007.01) 첨가 후 1분 진탕, 원심분리 4000 rpm 5분.
4. 상등액을 d-SPE 튜브(PSA 50 mg + C18 50 mg + MgSO4 150 mg)로 옮긴다.
5. LC-MS/MS (ESI+, MRM), 컬럼 C18 2.1×100 mm, 1.8 µm, 컬럼 온도 40 °C
"""


def _by_key(fields: list[Any]) -> dict[str, Any]:
    return {f.key: f for f in fields}


# ------------------------------------------------------------------ rules


def test_rules_extract_written_values_and_leave_the_rest_empty() -> None:
    out = service.extract_protocol(PASTE)
    f = _by_key(out.fields)
    assert out.engine == "rules" and out.fallback_reason is None
    assert f["sample_mass_g"].value == 10 and f["sample_mass_g"].status == "recognized"
    assert f["extraction_solvent"].value == "1% 아세트산 아세토니트릴"
    assert f["extraction_volume_ml"].value == 10
    assert f["extraction_time_min"].value == 10
    assert f["buffer"].value == "아세테이트 완충염 (AOAC 2007.01)"
    assert f["cleanup_sorbent"].value == "PSA 50 mg + C18 50 mg + MgSO4 150 mg"
    assert f["column"].value == "C18 2.1×100 mm, 1.8 µm"
    assert f["column_temp_c"].value == 40
    assert f["instrument"].value == "LC-MS/MS (ESI+, MRM)"
    # Not written → not guessed.
    for key in ("ph", "internal_standard", "calibration_weighting"):
        assert f[key].status == "unrecognized" and f[key].value is None
    # The value is shown with the verbatim line it came from.
    assert f["extraction_time_min"].source_text in PASTE
    assert f["extraction_time_min"].line == 3
    assert out.recognized_count == sum(x.status == "recognized" for x in out.fields)
    assert [s.condition_keys for s in out.steps][1] == [
        "extraction_solvent",
        "extraction_volume_ml",
        "extraction_time_min",
    ]
    assert len(out.steps) == 5


def test_rules_table_paste_units_and_ranges_are_not_converted() -> None:
    table = "항목\t값\n시료량\t15 g\n추출 시간\t600 s\n컬럼 온도\t35–40 °C\n원심분리\t3000 rpm\n"
    out = service.extract_protocol(table)
    f = _by_key(out.fields)
    assert f["sample_mass_g"].value == 15
    assert f["extraction_time_min"].value is None and "단위" in f["extraction_time_min"].note
    assert f["column_temp_c"].status == "ambiguous" and f["column_temp_c"].value is None
    assert out.steps == []  # a condition table is not a procedure
    assert [u.text for u in out.unmatched_lines] == ["원심분리\t3000 rpm"]


@pytest.mark.parametrize(
    ("line", "key"),
    [
        ("컬럼 C18, 컬럼 온도 35–40 °C", "column_temp_c"),
        ("pH 5.0~5.5로 조정", "ph"),
        ("추출 5-10분", "extraction_time_min"),
    ],
)
def test_rules_ranges_in_free_text_are_left_empty(line: str, key: str) -> None:
    field = _by_key(service.extract_protocol(line).fields)[key]
    assert field.value is None and field.status != "recognized"


def test_rules_markdown_table_and_conflicting_values() -> None:
    md = "| 조건 | 값 |\n|---|---|\n| 추출 용매 | 아세토니트릴 |\n| pH | 5.5 |\n| pH | 6.5 |"
    f = _by_key(service.extract_protocol(md).fields)
    assert f["extraction_solvent"].value == "아세토니트릴"
    assert f["ph"].status == "ambiguous" and f["ph"].value is None
    assert len(f["ph"].candidates) == 2


@pytest.mark.parametrize(
    ("line", "key"),
    [
        ("추출 후 원심분리 5분", "extraction_time_min"),  # duration of another operation
        ("이동상 B: 메탄올", "extraction_solvent"),  # mobile phase, not extraction
        ("컬럼 C18 2.1×100 mm", "cleanup_sorbent"),  # column, not d-SPE
        ("시료 수화 10분", "sample_mass_g"),
    ],
)
def test_rules_do_not_read_lookalikes(line: str, key: str) -> None:
    f = _by_key(service.extract_protocol(line).fields)
    assert f[key].value is None


# ----------------------------------------------------------------- claude


def _draft(fields: list[tuple[str, str, str]], steps: list[DraftStep] | None = None) -> Any:
    def respond(schema: type[BaseModel], prompt: str) -> BaseModel | None:
        assert schema is ProtocolExtractionDraft and "추출 10분" in prompt
        return ProtocolExtractionDraft(
            fields=[DraftField(key=k, value=v, source_text=q) for k, v, q in fields],
            steps=steps or [],
        )

    return respond


def test_claude_draft_grounded_in_quotes_is_used(fake_gateway_factory: Any) -> None:
    line = "2. 1% 아세트산 아세토니트릴 10 mL를 넣고 추출 10분 진탕한다."
    gw = fake_gateway_factory(
        _draft(
            [("extraction_time_min", "10", line), ("extraction_solvent", "아세토니트릴", line)],
            [DraftStep(title="용매 추출", detail="", condition_keys=["extraction_time_min"])],
        )
    )
    out = service.extract_protocol(PASTE, gateway=gw)
    f = _by_key(out.fields)
    assert out.engine == "claude" and out.model == "fake-claude"
    assert f["extraction_time_min"].value == 10 and f["extraction_time_min"].line == 3
    assert f["ph"].status == "unrecognized"
    assert out.steps[0].condition_keys == ["extraction_time_min"]


@pytest.mark.parametrize(
    ("fields", "reason"),
    [
        ([("extraction_time_min", "7", "추출 10분 진탕한다.")], "number not in its quote"),
        ([("extraction_time_min", "10", "추출 시간은 10분")], "quote not found"),
        ([("shaking_rpm", "1500", "추출 10분")], "unknown condition key"),
        ([("buffer", "시트레이트", "아세테이트 완충염 (AOAC 2007.01)")], "not copied"),
    ],
)
def test_claude_draft_with_invented_value_falls_back_to_rules(
    fake_gateway_factory: Any, fields: list[tuple[str, str, str]], reason: str
) -> None:
    out = service.extract_protocol(PASTE, gateway=fake_gateway_factory(_draft(fields)))
    assert out.engine == "rules"
    assert out.fallback_reason is not None and reason in out.fallback_reason
    assert _by_key(out.fields)["extraction_time_min"].value == 10  # rules result


def test_claude_unavailable_falls_back(fake_gateway_factory: Any) -> None:
    out = service.extract_protocol(PASTE, gateway=fake_gateway_factory(lambda s, p: None))
    assert out.engine == "rules" and out.fallback_reason == "claude_unavailable"


# ------------------------------------------------------------ save + review


def _confirmed_template(session: Session, project_id: int) -> Any:
    ex = service.extract_protocol(PASTE)
    block = {f.key: f.value for f in ex.fields if f.value is not None}
    block["extraction_time_min"] = 12  # researcher edits one candidate
    block["ph"] = 5.0  # and fills one the extraction did not recognize
    del block["instrument"]  # and clears one
    return service.create_protocol_template(
        session,
        project_id,
        ProtocolTemplateCreate(
            name="붙여넣은 SOP",
            version_label="v1",
            condition_block=block,  # type: ignore[arg-type]
            steps=[s.model_dump() for s in ex.steps],  # type: ignore[misc]
            source_text=PASTE,
            extraction=ExtractionSnapshot(engine=ex.engine, fields=ex.fields),
        ),
    )


def test_confirmed_paste_is_stored_with_original_text_and_review(
    session: Session, seeded: dict[str, int]
) -> None:
    pid = seeded["project"]
    with pytest.raises(Exception, match="값이 없는 조건"):
        # steps may only name keys that have a confirmed value (instrument was cleared)
        _confirmed_template(session, pid)
    session.rollback()

    ex = service.extract_protocol(PASTE)
    block = {f.key: f.value for f in ex.fields if f.value is not None}
    block["extraction_time_min"] = 12
    block["ph"] = 5.0
    tpl = service.create_protocol_template(
        session,
        pid,
        ProtocolTemplateCreate(
            name="붙여넣은 SOP",
            version_label="v1",
            condition_block=block,  # type: ignore[arg-type]
            steps=[s.model_dump() for s in ex.steps],  # type: ignore[misc]
            source_text=PASTE,
            extraction=ExtractionSnapshot(engine=ex.engine, fields=ex.fields),
        ),
    )
    session.commit()
    assert tpl.source_text == PASTE and tpl.display_version == "v1" and not tpl.steps_derived
    assert tpl.extraction is not None
    outcomes = {i.key: i.outcome for i in tpl.extraction.items}
    assert outcomes["extraction_time_min"] == "edited"
    assert outcomes["ph"] == "added"
    assert outcomes["sample_mass_g"] == "accepted"
    assert outcomes["internal_standard"] == "left_empty"
    ev = list_events(session, entity_type="eln.ProtocolTemplate", entity_id=tpl.id)
    assert ev[0].payload["extraction"] == {
        "engine": "rules",
        "accepted": 9,
        "edited": 1,
        "added": 1,
    }
    assert "source_text_sha256" in ev[0].payload

    row = session.get(ProtocolTemplate, tpl.id)
    assert row is not None
    row.source_text = "고친 원문"
    with pytest.raises(ImmutableRecordError):
        session.flush()
    session.rollback()


def test_extraction_quote_must_come_from_source_text(client: TestClient) -> None:
    ex = client.post("/api/eln/protocol-extractions", json={"text": PASTE}).json()
    ex["fields"][0]["source_text"] = "원문에 없는 줄"
    res = client.post(
        "/api/eln/projects/1/protocol-templates",
        json={
            "name": "x",
            "condition_block": {"matrix": "사과"},
            "source_text": PASTE,
            "extraction": {"engine": "rules", "fields": ex["fields"]},
        },
    )
    assert res.status_code == 400


def test_legacy_template_steps_are_derived_from_the_note(client: TestClient) -> None:
    exps = client.get("/api/eln/projects/1/experiments").json()
    first = exps[0]["id"]
    tpl = client.post(
        "/api/eln/projects/1/protocol-templates",
        json={"name": "노트에서", "source_experiment_id": first},
    ).json()
    assert tpl["steps_derived"] is True and tpl["steps"]
    run = client.post(f"/api/eln/protocol-templates/{tpl['id']}/runs", json={}).json()
    keys = [k["key"] for s in run["steps"] for k in s["conditions"]]
    assert set(keys) == set(tpl["condition_block"])  # every condition is on some step


# ---------------------------------------------------------------- lineage


def test_lineage_lists_condition_changes_and_uses(client: TestClient) -> None:
    exps = {e["code"]: e["id"] for e in client.get("/api/eln/projects/1/experiments").json()}
    base = client.get(f"/api/eln/experiments/{exps['#018']}").json()["condition_block"]
    v1 = client.post(
        "/api/eln/projects/1/protocol-templates",
        json={"name": "SOP", "version_label": "v1", "condition_block": base},
    ).json()
    changed = {**base, "extraction_time_min": 5, "column_temp_c": None}
    changed = {k: v for k, v in changed.items() if v is not None}
    v2 = client.post(
        "/api/eln/projects/1/protocol-templates",
        json={"name": "SOP", "version_label": "v1.1", "condition_block": changed},
    ).json()
    assert v2["version"] == 2 and v2["display_version"] == "v1.1"
    draft = {
        "code": "#900",
        "title": "v1.1로 수행",
        "performed_on": "2026-11-01",
        "raw_note": "x",
        "condition_block": {**changed, "ph": 6.0},
        "protocol_template_id": v2["id"],
    }
    assert client.post("/api/eln/projects/1/experiments", json=draft).status_code == 201

    lineage = client.get("/api/eln/projects/1/protocol-lineage").json()
    item = next(i for i in lineage["lineages"] if i["name"] == "SOP")
    assert [v["template"]["display_version"] for v in item["versions"]] == ["v1", "v1.1"]
    changes = {c["key"]: c for c in item["versions"][1]["changes_from_previous"]}
    assert changes["extraction_time_min"]["before"] == base["extraction_time_min"]
    assert changes["extraction_time_min"]["after"] == 5
    assert changes["column_temp_c"]["kind"] == "removed"
    use = item["versions"][1]["experiments"][0]
    assert use["code"] == "#900" and [d["key"] for d in use["deviations"]] == ["ph"]

    diff = client.get("/api/eln/protocol-diff", params={"a": v1["id"], "b": v2["id"]}).json()
    assert {c["key"] for c in diff["changes"]} == {"extraction_time_min", "column_temp_c"}
    assert "matrix" in diff["unchanged_keys"]


# ------------------------------------------------------------------- runs


def _template_for_run(session: Session, project_id: int) -> int:
    ex = service.extract_protocol(PASTE)
    block = {f.key: f.value for f in ex.fields if f.value is not None}
    tpl = service.create_protocol_template(
        session,
        project_id,
        ProtocolTemplateCreate(
            name="실행용 SOP",
            condition_block=block,  # type: ignore[arg-type]
            steps=[s.model_dump() for s in ex.steps],  # type: ignore[misc]
            source_text=PASTE,
        ),
    )
    return tpl.id


def test_run_records_differences_and_becomes_an_experiment(
    session: Session, seeded: dict[str, int]
) -> None:
    pid = seeded["project"]
    tid = _template_for_run(session, pid)
    run = service.start_protocol_run(session, tid, ProtocolRunCreate(operator="김연구"))
    assert run.status == "in_progress" and run.current_step_index == 0
    extract_step = next(
        s.index for s in run.steps if any(c.key == "extraction_time_min" for c in s.conditions)
    )

    def add(**kw: Any) -> Any:
        return service.add_protocol_run_entry(session, run.id, ProtocolRunEntryCreate(**kw))

    add(kind="check", step_index=0)
    add(
        kind="actual",
        step_index=extract_step,
        key="extraction_time_min",
        value="7",
        note="타이머 오작동",
    )
    state = add(kind="check", step_index=extract_step)
    add(kind="note", step_index=extract_step + 1, note="원심분리 10분으로 연장")
    state = add(kind="actual", step_index=0, key="sample_mass_g", value=10)  # same as planned
    assert state.done_count == 2 and state.current_step_index == 2
    cond = next(c for c in state.steps[extract_step].conditions if c.key == "extraction_time_min")
    assert cond.planned == 10 and cond.actual == 7 and cond.deviated
    assert [d.kind for d in state.deviations] == ["value", "note"]  # equal value is no deviation

    with pytest.raises(Exception, match="숫자"):
        add(kind="actual", step_index=extract_step, key="extraction_time_min", value="약 7분쯤")
    with pytest.raises(Exception, match="조건 키"):
        add(kind="actual", step_index=0, key="column_temp_c", value=30)

    body = ProtocolRunComplete(
        code="#025",
        title="SOP 실행",
        performed_on="2026-11-04",  # type: ignore[arg-type]
        observations="추출액 맑음",
        dry_run=True,
    )
    preview = service.complete_protocol_run(session, run.id, body)
    assert preview.experiment_id is None and preview.dry_run
    assert "skipped" in {d.kind for d in preview.deviations}  # unchecked steps listed
    assert service.get_protocol_run(session, run.id).status == "in_progress"

    done = service.complete_protocol_run(
        session, run.id, body.model_copy(update={"dry_run": False})
    )
    session.commit()
    exp = service.get_experiment(session, done.experiment_id or 0)
    assert exp.condition_block.extraction_time_min == 7  # actual value
    assert exp.condition_block.column_temp_c == 40  # planned value kept
    assert exp.protocol_template_id == tid and exp.author == "김연구"
    assert "프로토콜과 다른 점:" in exp.raw_note
    assert "추출 시간 (min) 10 min → 7 min (타이머 오작동)" in exp.raw_note
    assert "원심분리 10분으로 연장" in exp.raw_note and "추출액 맑음" in exp.raw_note
    assert done.run.status == "completed" and done.run.experiment_id == exp.id

    with pytest.raises(ImmutableRecordError):
        add(kind="check", step_index=1)
    actions = [
        e.action for e in list_events(session, entity_type="eln.ProtocolRun", entity_id=run.id)
    ]
    assert actions.count("record") == 5 and "start" in actions and "complete" in actions

    entry = session.query(ProtocolRunEntry).filter_by(run_id=run.id).first()
    assert entry is not None
    entry.note = "고침"
    with pytest.raises(ImmutableRecordError):
        session.flush()
    session.rollback()


def test_run_api_roundtrip_and_listing(client: TestClient) -> None:
    ex = client.post("/api/eln/protocol-extractions", json={"text": PASTE}).json()
    block = {f["key"]: f["value"] for f in ex["fields"] if f["value"] is not None}
    tpl = client.post(
        "/api/eln/projects/1/protocol-templates",
        json={
            "name": "API SOP",
            "condition_block": block,
            "steps": ex["steps"],
            "source_text": PASTE,
        },
    ).json()
    run = client.post(f"/api/eln/protocol-templates/{tpl['id']}/runs", json={"operator": "이분석"})
    assert run.status_code == 201
    rid = run.json()["id"]
    bad = client.post(
        f"/api/eln/protocol-runs/{rid}/entries", json={"kind": "check", "step_index": 99}
    )
    assert bad.status_code == 400
    listed = client.get(
        "/api/eln/projects/1/protocol-runs", params={"status": "in_progress"}
    ).json()
    assert [r["id"] for r in listed["items"]] == [rid]
    assert client.get(f"/api/eln/protocol-runs/{rid}").json()["step_count"] == len(ex["steps"])


def test_pure_condition_changes_order_and_equality() -> None:
    a = {"ph": 5, "matrix": "사과", "extra_key": 1}
    b = {"ph": 5.0, "matrix": "사과 ", "column_temp_c": 30}
    changes = protocols.condition_changes(a, b)
    assert [(c.key, c.kind) for c in changes] == [
        ("column_temp_c", "added"),
        ("extra_key", "removed"),
    ]
