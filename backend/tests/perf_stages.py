"""Per-fix attribution for PERFORMANCE.md: the scale benchmark with the fixes enabled one
at a time, cumulatively, in the order of :data:`tests.perf_reference.FIXES`.

Usage (from ``backend/``; the ``--db`` file is built by ``app.scripts.bench_scale`` when
missing and never modified)::

    python -m tests.perf_stages --db /tmp/bench1000.db --repeats 3 --json stages.json

Stage *k* runs the current code with fixes ``FIXES[k:]`` swapped back to their verbatim
pre-optimisation implementations (:func:`tests.perf_reference.install`); the dataset index
is dropped from the working copy while ``dataset_index`` is not yet applied. Every stage
must return the same responses as the first one — the script exits with status 1 otherwise.
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text

from app.core.db import Database
from app.memory import facts
from app.scripts import bench_scale
from tests import perf_reference

INDEX = "ix_eln_datasets_supersedes_dataset_id"


def _drop_index(db: Database) -> None:
    with db.session() as s:
        s.execute(text(f"DROP INDEX IF EXISTS {INDEX}"))
        s.commit()


def run(db_path: Path, repeats: int) -> list[dict[str, Any]]:
    """One benchmark report per stage (stage 0 = every fix reverted)."""
    stages: list[dict[str, Any]] = []
    first: str | None = None
    fixes = perf_reference.FIXES
    for k in range(len(fixes) + 1):
        revert = set(fixes[k:])
        name = "before (all reverted)" if k == 0 else f"+ {fixes[k - 1]}"
        facts._dataset_cache.clear()  # each stage starts like a fresh process
        with pytest.MonkeyPatch.context() as mp:
            perf_reference.install(mp, revert)
            report, responses = bench_scale.run(
                0, repeats, db_path, _drop_index if "dataset_index" in revert else None
            )
        # A digest, not the responses: keeping ~10⁷ objects alive would slow every later
        # stage's garbage collection and distort its timings.
        digest = hashlib.sha256(
            json.dumps(bench_scale.normalized(responses), sort_keys=True).encode()
        ).hexdigest()
        del responses
        gc.collect()
        if first is None:
            first = digest
        report["stage"] = name
        report["identical_to_stage_0"] = digest == first
        stages.append(report)
        print(f"{name}: identical={report['identical_to_stage_0']}", file=sys.stderr)
    return stages


def markdown(stages: list[dict[str, Any]]) -> str:
    """Median ms per measurement (rows) and stage (columns)."""
    head = "| measurement | " + " | ".join(s["stage"] for s in stages) + " |"
    lines = [head, "|---|" + "---:|" * len(stages)]
    for i, row in enumerate(stages[0]["rows"]):
        cells = [f"{s['rows'][i]['median_ms']:.0f}" for s in stages]
        lines.append(f"| {row['name']} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n", 1)[0])
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--experiments", type=int, default=1000, help="when building --db")
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args(argv)
    if not args.db.exists():
        bench_scale.build(args.db, args.experiments)
    stages = run(args.db, args.repeats)
    if args.json:
        args.json.write_text(json.dumps(stages, ensure_ascii=False, indent=2), encoding="utf-8")
    print(markdown(stages))
    if not all(s["identical_to_stage_0"] for s in stages):
        sys.exit(1)


if __name__ == "__main__":
    main()
