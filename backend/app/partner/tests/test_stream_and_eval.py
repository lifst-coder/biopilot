"""PAR-9 SSE streaming (rules + streaming Claude double) and PAR-3 evaluation script."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.llm import RulesOnlyGateway
from app.partner import service
from app.partner.context import build_context
from app.partner.schemas import AskRequest, CritiqueDraft
from app.partner.scripts import eval_partner


def _events(chunks: Iterator[str]) -> list[tuple[str, dict]]:
    out = []
    for block in "".join(chunks).strip().split("\n\n"):
        head, data = block.split("\n", 1)
        out.append((head.removeprefix("event: "), json.loads(data.removeprefix("data: "))))
    return out


class StreamingFake:
    """Claude-mode gateway double with ``stream_text`` (PAR-9 capability)."""

    def __init__(self, chunks: list[str], fail: bool = False) -> None:
        self.chunks, self.fail = chunks, fail

    mode = "claude"
    model_name = "fake-stream"

    def generate(self, *, system: str, prompt: str, schema: type) -> None:
        return None

    def stream_text(self, *, system: str, prompt: str) -> Iterator[str]:
        yield from self.chunks
        if self.fail:
            raise RuntimeError("boom")


def _req(seeded: dict[str, int]) -> AskRequest:
    return AskRequest(
        project_id=seeded["project"], experiment_id=seeded["#024"], question="IS 억제?"
    )


def test_rules_stream_ends_with_final_answer(session: Session, seeded: dict[str, int]) -> None:
    events = _events(service.ask_stream(session, _req(seeded), gateway=RulesOnlyGateway()))
    names = [e for e, _ in events]
    assert names[0] == "start" and names[-1] == "final" and "delta" in names
    final = events[-1][1]
    assert final["engine"] == "rules" and final["evidence"] and final["exchange_id"]


def test_claude_stream_validated(session: Session, seeded: dict[str, int]) -> None:
    key = build_context(session, seeded["#024"]).evidence.get("is_flagged").key  # type: ignore[union-attr]
    gw = StreamingFake([f"IS 이탈 주입이 있다 [{key}]\n", "[추정] 시료별 매트릭스 차이"])
    events = _events(service.ask_stream(session, _req(seeded), gateway=gw))  # type: ignore[arg-type]
    assert [e for e, _ in events].count("delta") == 2
    final = events[-1][1]
    assert final["engine"] == "claude"
    assert [s["kind"] for s in final["statements"]] == ["inference", "estimate"]


@pytest.mark.parametrize(
    ("gw", "reason"),
    [
        (StreamingFake(["회수율 12.34% 확인"]), "ungrounded"),
        (StreamingFake(["부분"], fail=True), "stream failed"),
    ],
)
def test_claude_stream_replaced_by_rules(
    session: Session, seeded: dict[str, int], gw: StreamingFake, reason: str
) -> None:
    events = _events(service.ask_stream(session, _req(seeded), gateway=gw))  # type: ignore[arg-type]
    names = [e for e, _ in events]
    assert "replace" in names and names[-1] == "final"
    final = events[-1][1]
    assert final["engine"] == "rules" and reason in final["fallback_reason"]


def test_stream_endpoint(client: TestClient) -> None:
    with client.stream(
        "POST",
        "/api/partner/ask/stream",
        json={"project_id": 1, "experiment_id": 7, "question": "#024 왜 낮나"},
    ) as r:
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
        body = "".join(r.iter_text())
    assert body.startswith("event: start") and "event: final" in body
    assert client.get("/api/partner/projects/1/exchanges").json()["items"]


def test_parse_stream_text() -> None:
    draft = service.parse_stream_text("사실 [E1][E2]\n\n[추정] 짐작\n근거 없음")
    assert [s.kind for s in draft.statements] == ["inference", "estimate", "estimate"]
    assert draft.evidence_keys == ["E1", "E2"]


# ------------------------------------------------------------------ PAR-3


def test_eval_rules_reference(tmp_path: Path) -> None:
    report = eval_partner.run("rules")
    assert not report.skipped and len(report.experiments) == 7
    assert report.grounding_pass_rate == 1.0 and report.expected_recall == 1.0
    out = tmp_path / "report.json"
    assert eval_partner.main(["--engine", "rules", "--output", str(out)]) == 0
    assert json.loads(out.read_text())["engine"] == "rules"


def test_eval_skips_without_key(capsys: pytest.CaptureFixture[str]) -> None:
    report = eval_partner.run("claude", gateway=RulesOnlyGateway())
    assert report.skipped and "ANTHROPIC_API_KEY" in (report.skip_reason or "")
    assert eval_partner.main(["--engine", "claude"]) == 0
    assert "skipped" in capsys.readouterr().out


def test_eval_claude_with_fake(fake_gateway_factory) -> None:
    bad = fake_gateway_factory(
        lambda _s, _p: CritiqueDraft(
            summary="회수율 99.9%", findings=[], hypotheses=[], proposals=[]
        )
    )
    report = eval_partner.run("claude", gateway=bad)
    assert report.engine == "claude" and report.grounding_pass_rate == 0.0
    assert report.expected_recall is not None and report.expected_recall < 1.0
    none = eval_partner.run("claude", gateway=fake_gateway_factory(lambda _s, _p: None))
    assert all(not e.produced for e in none.experiments)
