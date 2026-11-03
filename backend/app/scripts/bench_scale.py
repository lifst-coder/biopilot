"""Scale benchmark: response times with ~1000 experiments (PERFORMANCE.md).

Usage::

    python -m app.scripts.bench_scale                 # 1000 experiments, 5 repeats
    python -m app.scripts.bench_scale --experiments 200 --repeats 3 --json out.json

A throw-away file-backed SQLite database is seeded with the ``reference`` profile and
then grown with synthetic experiments: each one copies a reference experiment's
condition block (with a varied sample mass, pH, sorbent, author and date), note and CSV
datasets, hangs under a deterministic pseudo-random earlier experiment (so lineage depth
grows), and gets its analysis run — so Records has stored results to aggregate. Every
measurement goes through the **real HTTP API** (``TestClient``), rules mode, no network.

Measured: research-graph reconstruction (lineage and all relations), knowledge graph
(cold/warm), FTS indexing (full rebuild, incremental write, search, recall, cross-project
search) and Records aggregation (by condition, operator, period). Nothing is optimised
here; the numbers are recorded as-is.
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
import tempfile
import time
from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.config import Settings
from app.core.db import Database
from app.eln.schemas import ConditionBlock, DatasetCreate, ExperimentCreate
from app.main import create_app

SORBENTS = (
    "PSA 50 mg + MgSO4 150 mg",
    "PSA 25 mg + C18 25 mg + MgSO4 150 mg",
    "PSA 50 mg + GCB 7.5 mg + MgSO4 150 mg",
    "EMR-Lipid 50 mg",
)
AUTHORS = ("김연구", "이분석", "박실험", "최측정", "정검증")


def _grow(db: Database, project_id: int, n: int, seed: int = 7) -> None:
    """Add ``n`` synthetic experiments (+ datasets, + analysis) to ``project_id``."""
    from app.analysis import service as analysis
    from app.eln import service as eln

    rng = random.Random(seed)
    with db.session() as s:
        templates = eln.list_experiments_full(s, project_id)
        datasets = {
            t.id: [
                (d.kind, d.filename, eln.get_dataset_content(s, d.id))
                for d in eln.list_datasets(s, t.id)
            ]
            for t in templates
        }
        ids = [t.id for t in templates]
        start = max(t.performed_on for t in templates)
    for i in range(n):
        with db.session() as s:
            template = templates[i % len(templates)]
            cond = template.condition_block.model_dump(exclude_none=True)
            cond["sample_mass_g"] = rng.choice([5, 10, 15])
            cond["ph"] = round(rng.uniform(4.5, 6.5), 1)
            cond["cleanup_sorbent"] = rng.choice(SORBENTS)
            exp = eln.create_experiment(
                s,
                project_id,
                ExperimentCreate(
                    code=f"#B{i:04d}",
                    title=f"합성 실험 {i} — {template.title}",
                    author=rng.choice(AUTHORS),
                    performed_on=start + timedelta(days=1 + i // 3),
                    parent_experiment_id=rng.choice(ids[-50:]),
                    raw_note=f"{template.raw_note}\n합성 반복 {i}: {cond['cleanup_sorbent']}",
                    condition_block=ConditionBlock.model_validate(cond),
                ),
            )
            for kind, filename, content in datasets[template.id]:
                eln.create_dataset(
                    s, exp.id, DatasetCreate(kind=kind, filename=filename, content=content)
                )
            analysis.run_experiment(s, exp.id)
            s.commit()
            ids.append(exp.id)


def _time(fn: Callable[[], Any], repeats: int) -> tuple[float, float, Any]:
    """(median ms, max ms, last result) of ``repeats`` calls."""
    samples: list[float] = []
    result: Any = None
    for _ in range(repeats):
        t0 = time.perf_counter()
        result = fn()
        samples.append((time.perf_counter() - t0) * 1000)
    return statistics.median(samples), max(samples), result


def _get(client: TestClient, url: str) -> Callable[[], Any]:
    def call() -> Any:
        r = client.get(url)
        r.raise_for_status()
        return r.json()

    return call


def run(experiments: int, repeats: int) -> dict[str, Any]:
    """Build the synthetic database and measure every endpoint group."""
    from app.memory import knowledge_graph, search_index
    from app.memory import service as memory

    with tempfile.TemporaryDirectory() as tmp:
        url = f"sqlite:///{Path(tmp) / 'bench.db'}"
        settings = Settings(auto_seed=True, database_url=url, anthropic_api_key=None)
        db = Database(url)
        app = create_app(settings, db)
        rows: list[dict[str, Any]] = []
        with TestClient(app) as client:
            pid = int(client.get("/api/eln/projects").json()[0]["id"])
            t0 = time.perf_counter()
            _grow(db, pid, experiments)
            setup_s = time.perf_counter() - t0
            with db.session() as s:
                total = s.execute(text("SELECT count(*) FROM eln_experiments")).scalar_one()
                audit = s.execute(text("SELECT count(*) FROM core_audit_events")).scalar_one()
                results = s.execute(text("SELECT count(*) FROM analysis_results")).scalar_one()
                datasets = s.execute(text("SELECT count(*) FROM eln_datasets")).scalar_one()

            def add(group: str, name: str, fn: Callable[[], Any], n: int = repeats) -> Any:
                med, worst, result = _time(fn, n)
                rows.append({"group": group, "name": name, "median_ms": med, "max_ms": worst})
                return result

            base = f"/api/memory/projects/{pid}"
            add("graph", "GET graph (derived_from)", _get(client, f"{base}/graph"))
            add(
                "graph",
                "GET graph (all relations)",
                _get(
                    client,
                    f"{base}/graph?relations=derived_from&relations=shares_conditions"
                    "&relations=tests_proposal",
                ),
            )

            def kg_cold() -> Any:
                knowledge_graph.reset_cache()
                return _get(client, f"{base}/knowledge-graph")()

            add("graph", "GET knowledge-graph (cold cache, full build)", kg_cold)
            add(
                "graph", "GET knowledge-graph (warm cache)", _get(client, f"{base}/knowledge-graph")
            )
            add("graph", "GET timeline", _get(client, f"{base}/timeline"))

            def rebuild() -> int:
                with db.session() as s:
                    s.execute(text(f"DROP TABLE IF EXISTS {search_index.FTS_TABLE}"))
                    n = memory.sync_search_index(s).indexed_events
                    s.commit()
                    return n

            add(
                "fts",
                "full index rebuild (start-up path, sync_search_index)",
                rebuild,
                max(1, repeats // 2),
            )
            counter = iter(range(10_000))
            exp_id = client.get(f"/api/eln/projects/{pid}/experiments?limit=1").json()[0]["id"]

            def write_note() -> Any:
                r = client.post(
                    f"{base}/knowledge-notes",
                    json={
                        "statement": f"벤치 메모 {next(counter)}",
                        "linked_experiment_ids": [exp_id],
                    },
                )
                r.raise_for_status()
                return r.json()

            add("fts", "POST knowledge note (write + incremental index)", write_note)
            add("fts", "GET search q=회수율", _get(client, f"{base}/search?q=회수율"))
            add("fts", "GET search q=GCB 정제 (2 terms)", _get(client, f"{base}/search?q=GCB 정제"))
            add("fts", "GET search q=회수 (short, LIKE)", _get(client, f"{base}/search?q=회수"))
            add(
                "fts",
                "GET recall q=GCB 쓴 실험의 회수율은?",
                _get(client, f"{base}/recall?q=GCB 쓴 실험의 회수율은?"),
            )
            add(
                "fts",
                "GET /api/memory/search q=GCB (all projects)",
                _get(client, "/api/memory/search?q=GCB"),
            )
            add(
                "records",
                "GET records/conditions key=cleanup_sorbent",
                _get(client, "/api/analysis/records/conditions?key=cleanup_sorbent"),
            )
            add("records", "GET records/operators", _get(client, "/api/analysis/records/operators"))
            add("records", "GET records/periods", _get(client, "/api/analysis/records/periods"))
            add("records", "GET memory/failures", _get(client, "/api/memory/failures"))
        return {
            "experiments": total,
            "synthetic_added": experiments,
            "datasets": datasets,
            "analysis_results": results,
            "audit_events": audit,
            "setup_seconds": round(setup_s, 1),
            "repeats": repeats,
            "python": sys.version.split()[0],
            "date": date.today().isoformat(),
            "rows": rows,
        }


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        f"experiments={report['experiments']} datasets={report['datasets']} "
        f"analysis_results={report['analysis_results']} audit_events={report['audit_events']} "
        f"(setup {report['setup_seconds']} s, repeats={report['repeats']})",
        "",
        "| group | measurement | median ms | max ms |",
        "|---|---|---:|---:|",
    ]
    for r in report["rows"]:
        lines.append(f"| {r['group']} | {r['name']} | {r['median_ms']:.0f} | {r['max_ms']:.0f} |")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--experiments", type=int, default=1000)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args(argv)
    report = run(args.experiments, args.repeats)
    if args.json:
        args.json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(_markdown(report))


if __name__ == "__main__":
    main()
