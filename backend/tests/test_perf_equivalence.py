"""Optimised code answers exactly like the pre-optimisation code (PERFORMANCE.md).

A database with two projects (``lab`` and ``reference`` seeds) grown with synthetic
experiments (the benchmark's generator) is queried through the HTTP API twice: with the
optimised code, and with every optimised function swapped for its verbatim
pre-optimisation implementation (:mod:`tests.perf_reference`). Every response — graphs,
knowledge graph, timeline, search, recall, Records, failure archive, metrics of every
experiment, comparisons, diffs, trends — and every row of a full FTS index rebuild
must be identical.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.config import Settings
from app.core.db import Database
from app.eln import service as eln
from app.main import create_app
from app.memory import knowledge_graph, search_index
from app.memory import service as memory
from app.scripts.bench_scale import _grow
from app.seed.loader import seed
from tests import perf_reference

Grown = tuple[TestClient, Database, dict[str, int]]


@pytest.fixture(scope="module")
def grown(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Grown]:
    """``lab`` + ``reference`` projects, each grown with synthetic experiments."""
    url = f"sqlite:///{Path(tmp_path_factory.mktemp('perf')) / 'perf.db'}"
    db = Database(url)
    settings = Settings(
        auto_seed=True, seed_profile="lab", database_url=url, anthropic_api_key=None
    )
    with TestClient(create_app(settings, db)) as client:
        with db.session() as s:
            reference = seed(s, "reference")
            s.commit()
            lab = next(p.id for p in eln.list_projects(s) if p.id != reference)
        _grow(db, lab, 40, seed=11)
        _grow(db, reference, 25, seed=13)
        yield client, db, {"lab": lab, "reference": reference}
    knowledge_graph.reset_cache()
    db.engine.dispose()


def _urls(db: Database, projects: dict[str, int]) -> list[str]:
    urls: list[str] = [
        "/api/analysis/records/conditions?key=cleanup_sorbent",
        "/api/analysis/records/conditions?key=ph&contains=5",
        "/api/analysis/records/operators",
        "/api/analysis/records/operators?window_days=60",
        "/api/analysis/records/periods",
        "/api/analysis/records/periods?gap_days=5",
        "/api/memory/failures",
        "/api/memory/search?q=GCB",
        "/api/memory/recall?q=GCB 쓴 실험의 회수율은?",
        "/api/memory/recall?q=carbendazim 회수율",
    ]
    with db.session() as s:
        for pid in projects.values():
            base = f"/api/memory/projects/{pid}"
            urls += [
                f"{base}/graph",
                f"{base}/graph?relations=derived_from&relations=shares_conditions"
                "&relations=tests_proposal",
                f"{base}/knowledge-graph",
                f"{base}/knowledge-graph?types=experiment&types=analyte&types=result",
                f"{base}/timeline",
                f"{base}/search?q=회수율",
                f"{base}/search?q=GCB 정제",
                f"{base}/search?q=회수",
                f"{base}/recall?q=GCB 쓴 실험의 회수율은?",
                f"{base}/recall?q=PSA pH",
                f"/api/analysis/projects/{pid}/trend",
            ]
            exps = eln.list_experiments(s, pid)
            urls += [f"/api/analysis/experiments/{e.id}/metrics" for e in exps]
            urls += [
                f"/api/memory/experiments/{e.id}/similar" for e in exps[:: max(1, len(exps) // 5)]
            ]
            for a, b in zip(exps[::7], exps[3::7], strict=False):
                urls.append(f"/api/analysis/compare?a={a.id}&b={b.id}")
                urls.append(f"/api/memory/diff?a={a.id}&b={b.id}")
    return urls


def _responses(client: TestClient, urls: list[str]) -> dict[str, Any]:
    knowledge_graph.reset_cache()  # every run builds the knowledge graph from scratch
    out: dict[str, Any] = {}
    for url in urls:
        r = client.get(url)
        assert r.status_code == 200, (url, r.text[:300])
        out[url] = r.json()
    return out


def _index_rows(db: Database) -> list[tuple[Any, ...]]:
    """Every FTS row (all columns) in rowid order."""
    with db.session() as s:
        return [
            tuple(r)
            for r in s.execute(
                text(
                    "SELECT text, doc_key, project_id, experiment_id, field, ref_type, ref_id, "
                    f"ref_field FROM {search_index.FTS_TABLE} ORDER BY rowid"
                )
            )
        ]


def test_optimised_code_answers_like_the_reference(
    grown: Grown, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, db, projects = grown
    urls = _urls(db, projects)
    assert len(urls) > 150

    with db.session() as s:  # full rebuild with the optimised sync
        s.execute(text(f"DROP TABLE IF EXISTS {search_index.FTS_TABLE}"))
        memory.sync_search_index(s)
        s.commit()
    optimised_rows = _index_rows(db)
    optimised = _responses(client, urls)

    perf_reference.install(monkeypatch)
    with db.session() as s:  # full rebuild the old way
        perf_reference.ref_rebuild_index(s)
        s.commit()
    reference_rows = _index_rows(db)
    reference = _responses(client, urls)

    assert len(optimised_rows) > 1000
    assert optimised_rows == reference_rows
    different = [u for u in urls if optimised[u] != reference[u]]
    assert not different, different
    # the data exercises every optimised path
    lab_graph = optimised[
        f"/api/memory/projects/{projects['lab']}/graph?relations=derived_from"
        "&relations=shares_conditions&relations=tests_proposal"
    ]
    relations = {e["relation"] for e in lab_graph["edges"]}
    assert {"derived_from", "shares_conditions", "tests_proposal"} <= relations
    assert optimised["/api/memory/failures"]["patterns"]
    assert optimised["/api/memory/failures"]["failure_count"] > 0


def test_batched_reads_equal_per_item_reads(grown: Grown) -> None:
    """Each batched read equals the per-item read it replaced, order included."""
    from app.analysis import service as analysis
    from app.memory import facts, ports

    _client, db, projects = grown
    ref_provider = perf_reference.RefAnalysisFactProvider()
    with db.session() as s:
        for pid in projects.values():
            exps = eln.list_experiments_full(s, pid)
            assert exps == perf_reference.ref_list_experiments_full(s, pid)
            ids = [e.id for e in exps]
            assert eln.get_experiments(s, ids) == {i: eln.get_experiment(s, i) for i in ids}

            by_exp = eln.list_project_datasets(s, pid)
            for i in ids:
                assert by_exp.get(i, []) == eln.list_datasets(s, i)
            ds_ids = [d.id for i in ids for d in by_exp.get(i, [])]
            assert eln.get_datasets(s, ds_ids) == {d: eln.get_dataset(s, d) for d in ds_ids}
            contents = eln.get_dataset_contents(s, ds_ids)
            assert contents == {d: eln.get_dataset_content(s, d) for d in ds_ids}

            vocabs = facts.experiment_vocabs(s, pid, exps)
            for e in exps:
                assert vocabs[e.id] == perf_reference.ref_experiment_vocab(s, e)

            metrics = analysis.get_metrics_many(s, ids)
            refs = analysis.latest_result_refs_many(s, ids)
            result_ids = analysis.latest_result_ids_many(s, ids)
            for i in ids:
                assert metrics[i] == perf_reference.ref_get_metrics(s, i)
                assert analysis.get_metrics(s, i) == metrics[i]
                latest = analysis.latest_results(s, i)
                assert list(refs[i]) == list(latest) == list(result_ids[i])  # kind order
                for kind, res in latest.items():
                    assert (refs[i][kind].id, refs[i][kind].flags) == (res.id, res.flags)
                    assert result_ids[i][kind] == res.id

            qc = ports.qc_flags_many(s, ids)
            results = ports.results_many(s, ids)
            for i in ids:
                assert qc[i] == ports.qc_flags(s, i) == ref_provider.qc_flags(s, i)
                assert results[i] == ports.results(s, i) == ref_provider.results(s, i)

            heads = [r.id for i in ids for r in analysis.latest_results(s, i).values()]
            items: list[tuple[int, dict[str, Any]]] = [(h, {}) for h in heads]
            described = ports.describe_many(s, "analysis.AnalysisResult", items, pid)
            assert described == [
                ref_provider.describe(s, "analysis.AnalysisResult", h, pid, {}) for h in heads
            ]
