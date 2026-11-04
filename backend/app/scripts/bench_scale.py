"""Scale benchmark: response times with ~1000 experiments (PERFORMANCE.md).

Usage::

    python -m app.scripts.bench_scale                 # 1000 experiments, 5 repeats
    python -m app.scripts.bench_scale --experiments 200 --repeats 3 --json out.json
    # build the database once (≈ 2 min) and reuse it; dump every response and compare
    python -m app.scripts.bench_scale --db /tmp/bench1000.db --dump /tmp/before
    python -m app.scripts.bench_scale --db /tmp/bench1000.db --compare /tmp/before

``--db PATH`` keeps the grown database at ``PATH`` (built when missing). An existing
file is never modified: each run measures a fresh copy of it, so two runs (e.g. before
and after a code change) start from byte-identical data. ``--dump DIR`` writes the last
response of every measurement as JSON; ``--compare DIR`` checks the responses of this run
against such a dump (``created_at``/``occurred_at`` stripped — rows written during the run
get new timestamps) and exits with status 1 on any difference.

A throw-away file-backed SQLite database is seeded with the ``reference`` profile and
then grown with synthetic experiments: each one copies a reference experiment's
condition block (with a varied sample mass, pH, sorbent, author and date), note and CSV
datasets, hangs under a deterministic pseudo-random earlier experiment (so lineage depth
grows), and gets its analysis run — so Records has stored results to aggregate. Every
measurement goes through the **real HTTP API** (``TestClient``), rules mode, no network.

Measured: research-graph reconstruction (lineage and all relations), knowledge graph
(cold/warm), FTS indexing (full rebuild, incremental write, search, recall, cross-project
search) and Records aggregation (by condition, operator, period, failure archive).
"""

from __future__ import annotations

import argparse
import json
import random
import re
import shutil
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


#: Keys whose values depend on *when* a row was written (rows created during the run).
VOLATILE_KEYS = frozenset({"created_at", "occurred_at"})


def slug(name: str) -> str:
    """File-name slug of a measurement name."""
    return re.sub(r"[^0-9A-Za-z가-힣]+", "_", name).strip("_").lower()


def normalized(value: Any) -> Any:
    """``value`` with :data:`VOLATILE_KEYS` removed at every depth (for comparisons)."""
    if isinstance(value, dict):
        return {k: normalized(v) for k, v in value.items() if k not in VOLATILE_KEYS}
    if isinstance(value, list):
        return [normalized(v) for v in value]
    return value


def build(path: Path, experiments: int) -> float:
    """Seed ``reference`` into a new SQLite file at ``path`` and grow it. Returns seconds."""
    url = f"sqlite:///{path}"
    db = Database(url)
    app = create_app(Settings(auto_seed=True, database_url=url, anthropic_api_key=None), db)
    with TestClient(app) as client:
        pid = int(client.get("/api/eln/projects").json()[0]["id"])
        t0 = time.perf_counter()
        _grow(db, pid, experiments)
        elapsed = time.perf_counter() - t0
    db.engine.dispose()
    return elapsed


def run(
    experiments: int,
    repeats: int,
    db_path: Path | None = None,
    setup: Callable[[Database], None] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build (or copy) the synthetic database and measure every endpoint group.

    ``setup`` runs on the working copy after start-up, before the first measurement.
    Returns ``(report, responses)`` — ``responses`` maps measurement slug → last response.
    """
    from app.memory import knowledge_graph, search_index
    from app.memory import service as memory

    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "bench.db"
        setup_s: float | None = None
        if db_path is not None and db_path.exists():
            shutil.copyfile(db_path, work)
        else:
            setup_s = build(work, experiments)
            if db_path is not None:
                shutil.copyfile(work, db_path)
        url = f"sqlite:///{work}"
        settings = Settings(auto_seed=True, database_url=url, anthropic_api_key=None)
        db = Database(url)
        app = create_app(settings, db)
        knowledge_graph.reset_cache()
        rows: list[dict[str, Any]] = []
        responses: dict[str, Any] = {}
        with TestClient(app) as client:
            pid = int(client.get("/api/eln/projects").json()[0]["id"])
            if setup is not None:
                setup(db)
            with db.session() as s:
                total = s.execute(text("SELECT count(*) FROM eln_experiments")).scalar_one()
                audit = s.execute(text("SELECT count(*) FROM core_audit_events")).scalar_one()
                results = s.execute(text("SELECT count(*) FROM analysis_results")).scalar_one()
                datasets = s.execute(text("SELECT count(*) FROM eln_datasets")).scalar_one()

            def add(group: str, name: str, fn: Callable[[], Any], n: int = repeats) -> Any:
                med, worst, result = _time(fn, n)
                rows.append({"group": group, "name": name, "median_ms": med, "max_ms": worst})
                responses[slug(name)] = result
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

            def rebuild() -> Any:
                with db.session() as s:
                    s.execute(text(f"DROP TABLE IF EXISTS {search_index.FTS_TABLE}"))
                    n = memory.sync_search_index(s).indexed_events
                    s.commit()
                    rows_ = s.execute(
                        text(
                            "SELECT doc_key, project_id, experiment_id, field, ref_type, ref_id, "
                            f"ref_field, text FROM {search_index.FTS_TABLE}"
                        )
                    ).all()
                    return {"indexed_events": n, "rows": sorted([list(r) for r in rows_])}

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
        db.engine.dispose()
        report = {
            "experiments": total,
            "synthetic_added": experiments,
            "datasets": datasets,
            "analysis_results": results,
            "audit_events": audit,
            "setup_seconds": round(setup_s, 1) if setup_s is not None else None,
            "repeats": repeats,
            "python": sys.version.split()[0],
            "date": date.today().isoformat(),
            "rows": rows,
        }
        return report, responses


#: Written next to the responses: runs are only comparable with the same data and repeats
#: (``POST knowledge note`` runs once per repeat, and later searches see those notes).
META_FILE = "_meta.json"


def _meta(report: dict[str, Any]) -> dict[str, Any]:
    keys = ("experiments", "datasets", "analysis_results", "audit_events", "repeats")
    return {k: report[k] for k in keys}


def dump(responses: dict[str, Any], directory: Path, report: dict[str, Any]) -> None:
    """Write each response to ``directory/<slug>.json`` (normalized, sorted keys)."""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / META_FILE).write_text(json.dumps(_meta(report)), encoding="utf-8")
    for name, body in responses.items():
        (directory / f"{name}.json").write_text(
            json.dumps(normalized(body), ensure_ascii=False, sort_keys=True, indent=1),
            encoding="utf-8",
        )


def compare(responses: dict[str, Any], directory: Path, report: dict[str, Any]) -> list[str]:
    """Measurement slugs whose response differs from the dump in ``directory``."""
    meta_path = directory / META_FILE
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else None
    if meta != _meta(report):
        raise SystemExit(
            f"{directory} was dumped from a different run ({meta}); compare runs with the same "
            f"--db and --repeats ({_meta(report)})"
        )
    different: list[str] = []
    for name, body in responses.items():
        path = directory / f"{name}.json"
        if not path.exists():
            different.append(f"{name} (missing in {directory})")
            continue
        if json.loads(path.read_text(encoding="utf-8")) != json.loads(
            json.dumps(normalized(body), ensure_ascii=False)
        ):
            different.append(name)
    return different


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        f"experiments={report['experiments']} datasets={report['datasets']} "
        f"analysis_results={report['analysis_results']} audit_events={report['audit_events']} "
        f"(setup {report['setup_seconds'] if report['setup_seconds'] is not None else 'reused'}"
        f"{' s' if report['setup_seconds'] is not None else ''}, repeats={report['repeats']})",
        "",
        "| group | measurement | median ms | max ms |",
        "|---|---|---:|---:|",
    ]
    for r in report["rows"]:
        lines.append(f"| {r['group']} | {r['name']} | {r['median_ms']:.0f} | {r['max_ms']:.0f} |")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n", 1)[0])
    parser.add_argument("--experiments", type=int, default=1000)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--json", type=Path, default=None, help="write the report as JSON")
    parser.add_argument(
        "--db", type=Path, default=None, help="reuse (or build and keep) the grown database"
    )
    parser.add_argument("--dump", type=Path, default=None, help="write every response here")
    parser.add_argument(
        "--compare", type=Path, default=None, help="compare responses with an earlier --dump"
    )
    args = parser.parse_args(argv)
    report, responses = run(args.experiments, args.repeats, args.db)
    if args.json:
        args.json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.dump:
        dump(responses, args.dump, report)
    print(_markdown(report))
    if args.compare:
        different = compare(responses, args.compare, report)
        if different:
            print(f"\nRESPONSES DIFFER from {args.compare}: " + ", ".join(different))
            sys.exit(1)
        print(f"\nall {len(responses)} responses identical to {args.compare}")


if __name__ == "__main__":
    main()
