"""FTS5 search (Korean partial match, ranking, highlights) and keyword recall / Q&A."""

from __future__ import annotations

from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.memory import search_index, service
from app.memory.models import IndexState
from app.memory.schemas import KnowledgeNoteCreate, MemoryAnswerDraft, MemoryAskRequest


def test_fts_korean_partial_match_ranked_with_highlights(
    session: Session, seeded: dict[str, int]
) -> None:
    hits = service.search(session, seeded["project"], "회수율")
    assert hits and all(h.score > 0 for h in hits)
    assert [h.score for h in hits] == sorted((h.score for h in hits), reverse=True)
    for h in hits:
        assert h.highlights
        s, e = h.highlights[0]
        assert h.snippet[s:e] == "회수율"
        assert h.source is not None and h.source.experiment_id == h.experiment_id
    # particle-attached forms are found by substring ("회수율이", "회수율은" …)
    assert {h.code for h in hits} >= {"#018", "#024"}
    # two-character term: below trigram size, served by LIKE on the same index
    short = service.search(session, seeded["project"], "회수")
    assert {h.experiment_id for h in short} >= {h.experiment_id for h in hits}


def test_search_fields_and_and_semantics(session: Session, seeded: dict[str, int]) -> None:
    pid = seeded["project"]
    gcb = service.search(session, pid, "gcb")
    assert {h.code for h in gcb} == {"#024"}
    assert {h.field for h in gcb} >= {"raw_note", "condition_block"}
    critique = service.search(session, pid, "비판적 검토")
    assert [(h.code, h.field) for h in critique] == [("#024", "critique")]
    assert critique[0].source is not None and critique[0].source.ref_type == "partner.Critique"
    both = service.search(session, pid, "GCB 정제")
    assert both and {h.code for h in both} == {"#024"}
    assert service.search(session, pid, "GCB 존재하지않는") == []  # AND semantics
    assert service.search(session, pid, "carbendazim")[0].field in ("dataset", "critique", "digest")
    assert service.search(session, pid, "   ") == []
    assert service.search(session, pid, "존재하지않는검색어") == []
    assert any(h.field == "dataset" for h in service.search(session, pid, "R10-1"))
    assert service.search(session, pid, "100%_x") == []


def test_index_is_incremental_and_transactional(session: Session, seeded: dict[str, int]) -> None:
    pid = seeded["project"]
    service.search(session, pid, "gcb")
    state = session.get(IndexState, f"search:{pid}")
    assert state is not None and state.last_event_id > 0
    assert search_index.sync(session, pid) == 0
    service.create_knowledge_note(
        session,
        pid,
        KnowledgeNoteCreate(
            statement="흑연화 카본은 평면 분자를 흡착", linked_experiment_ids=[seeded["#024"]]
        ),
    )
    assert search_index.sync(session, pid) == 1
    hit = service.search(session, pid, "흑연화")
    assert [(h.code, h.field) for h in hit] == [("#024", "knowledge_note")]
    # dropping the derived index forces a full rebuild on the next search
    session.execute(text(f"DROP TABLE {search_index.FTS_TABLE}"))
    assert service.search(session, pid, "흑연화")


def test_python_fallback_matches_fts(session: Session, seeded: dict[str, int]) -> None:
    pid = seeded["project"]
    service.search(session, pid, "gcb")
    fts = {(d.doc_key, d.field) for d, _ in search_index._query_sqlite(session, pid, ["gcb"])}
    py = {(d.doc_key, d.field) for d, _ in search_index._query_python(session, pid, ["gcb"])}
    assert fts == py and fts


def test_documents_for_missing_entities_are_empty(session: Session, seeded: dict[str, int]) -> None:
    pid = seeded["project"]
    for et in (
        "eln.Experiment",
        "eln.Dataset",
        "memory.ExperimentDigest",
        "memory.KnowledgeNote",
        "partner.Critique",
        "eln.Project",
    ):
        assert search_index.documents_for(session, et, 999, pid, {}) == []


def test_recall_classifies_terms_and_bundles(session: Session, seeded: dict[str, int]) -> None:
    b = service.recall(session, seeded["project"], "GCB 쓴 실험의 carbendazim 회수율은?")
    facets = {t.term: t.facet for t in b.terms}
    assert facets == {"gcb": "condition", "carbendazim": "analyte", "회수율": "keyword"}
    assert b.experiments[0].experiment.code == "#024"
    reasons = b.experiments[0].reasons
    assert any(r.field == "condition_block" and "GCB" in r.snippet for r in reasons)
    assert all(r.source is not None for r in reasons)
    assert b.protocols[0].codes == ["#024"]
    assert set(b.protocols[1].differs_from_first) >= {"cleanup_sorbent", "extraction_time_min"}
    analytes = {r.analyte for r in b.results}
    assert analytes <= {None, "carbendazim"} and "carbendazim" in analytes
    assert all(r.source.ref_type == "analysis.AnalysisResult" for r in b.results)


def test_recall_sample_facet_and_keyword_only(session: Session, seeded: dict[str, int]) -> None:
    sample = service.recall(session, seeded["project"], "사과")
    assert sample.terms[0].facet == "sample" and len(sample.experiments) == 7
    by_id = service.recall(session, seeded["project"], "R50-2")
    assert by_id.terms[0].facet == "sample"
    nothing = service.recall(session, seeded["project"], "zzzz")
    assert nothing.experiments == [] and nothing.terms[0].facet == "keyword"
    assert all(r.analyte is None for r in sample.results)


def test_recall_terms_strip_particles_and_stopwords() -> None:
    assert service.recall_terms("GCB를 사용한 실험에서 회수율이 어땠나?") == [
        "gcb",
        "회수율",
        "어땠나",
    ]
    assert service.recall_terms("pH 6.5 영향") == ["ph", "6.5", "영향"]


def test_ask_rules_returns_evidence_fragments(session: Session, seeded: dict[str, int]) -> None:
    ans = service.ask(
        session, seeded["project"], MemoryAskRequest(question="GCB 사용 시 carbendazim 회수율은?")
    )
    assert ans.engine == "rules" and ans.fallback_reason is None
    assert ans.fragments and ans.fragment_keys == [f.key for f in ans.fragments]
    assert all(f"[{f.key}]" in ans.answer for f in ans.fragments)
    assert {f.source.ref_type for f in ans.fragments} >= {"analysis.AnalysisResult"}
    assert len({f.code for f in ans.fragments}) > 1
    empty = service.ask(session, seeded["project"], MemoryAskRequest(question="zzzz"))
    assert empty.fragments == [] and "찾지 못했습니다" in empty.answer


def test_ask_claude_grounded_and_fallbacks(
    session: Session, seeded: dict[str, int], fake_gateway_factory
) -> None:
    pid = seeded["project"]
    req = MemoryAskRequest(question="GCB 사용 시 carbendazim 회수율은?")
    base = service.ask(session, pid, req)
    first = base.fragments[0]
    quoted = first.text.split(": ")[-1].split(" ")[0]

    def good(schema: type[BaseModel], _p: str) -> BaseModel:
        return MemoryAnswerDraft(
            answer=f"#024에서 {quoted} 확인 [{first.key}]", fragment_keys=[first.key]
        )

    ok = service.ask(session, pid, req, gateway=fake_gateway_factory(good))
    assert ok.engine == "claude" and ok.model == "fake-claude" and ok.fallback_reason is None

    def invented(schema: type[BaseModel], _p: str) -> BaseModel:
        return MemoryAnswerDraft(answer="회수율은 12.345%이다 [F1]", fragment_keys=["F1"])

    bad = service.ask(session, pid, req, gateway=fake_gateway_factory(invented))
    assert bad.engine == "rules" and bad.fallback_reason == "ungrounded_numbers: 12.345"

    def unknown(schema: type[BaseModel], _p: str) -> BaseModel:
        return MemoryAnswerDraft(answer="근거 없음", fragment_keys=["F99"])

    unk = service.ask(session, pid, req, gateway=fake_gateway_factory(unknown))
    assert unk.fallback_reason == "unknown_fragment_keys: F99"

    def uncited(schema: type[BaseModel], _p: str) -> BaseModel:
        return MemoryAnswerDraft(answer="근거 없음", fragment_keys=[])

    unc = service.ask(session, pid, req, gateway=fake_gateway_factory(uncited))
    assert unc.fallback_reason == "unknown_fragment_keys: (none cited)"

    down = service.ask(session, pid, req, gateway=fake_gateway_factory(lambda _s, _p: None))
    assert down.engine == "rules" and down.fallback_reason == "claude_unavailable"
    assert down.answer == base.answer
