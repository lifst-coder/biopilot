"""Seed CSVs are reproducible from the documented generator."""

from __future__ import annotations

from app.seed.generate import DATA_DIR, generate
from app.seed.loader import load_seed_spec


def test_committed_csvs_match_generator() -> None:
    for name, text in generate().items():
        assert (DATA_DIR / name).read_text(encoding="utf-8") == text, name


def test_seed_spec_references_existing_files() -> None:
    spec = load_seed_spec()
    codes = [e["code"] for e in spec["experiments"]]
    assert codes == [f"#0{n}" for n in range(18, 25)]
    for exp in spec["experiments"]:
        for ds in exp["datasets"]:
            assert (DATA_DIR / ds["file"]).exists()
