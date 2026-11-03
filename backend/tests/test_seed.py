"""Seed files: reproducible CSVs, valid scenario specs and a stable reference profile."""

from __future__ import annotations

import csv
import hashlib
import io

import pytest
from pydantic import ValidationError

from app.seed import generate as gen
from app.seed.generate import DATA_DIR, generate
from app.seed.loader import PROFILE_ENV, resolve_profile
from app.seed.spec import REFERENCE_CODES, DecisionSpec, SeedSpec, load_seed_spec

#: sha256 of the 12 original seed CSVs (before the lab expansion). The reference
#: profile — and every module test built on it — depends on these exact bytes.
ORIGINAL_SHA256 = {
    "exp018_calibration.csv": "db3ba6a142f520fcf190ec2795152925949b1e8a14059402a00acd260499834e",
    "exp018_recovery.csv": "c9e49f85fc625c2da0b0631e06374a0457e07e34adfefd571122219c1b885bfc",
    "exp019_calibration.csv": "554b580c819e5620c6a3b21b1c36a9564e548ea9744341130888b554d4d81c7f",
    "exp019_recovery.csv": "f68111cb07e34e4d3e2ca6a65cadcc176291d2e595e0a85a1cec95e5868d26b6",
    "exp020_calibration.csv": "b565126ae86cf8f94ff71be7d2228fc985719768318575c51d2754c982266460",
    "exp020_recovery.csv": "5cb6d4cf93370abc8064177711a08590f3b69256fa94a7a185abd90271ed8a33",
    "exp021_matrix_effect.csv": "594e0d49b5b14fd801443dbba9e2c86dcb6ac78d7db6e57ceb600e85041cacc4",
    "exp022_calibration.csv": "a419c0a11ee9cbb42f1bdb0740f7391642fd1e1e60daf0f89378aee4e93d8335",
    "exp022_recovery.csv": "12f919cd7514e2a7ef48c6c80738030834f4b7d01bd933f2faff0e22cf6403d3",
    "exp023_calibration.csv": "86cf26a1a7da5eca39143143ba563993720a7a8b98556cc62faa3c8627c67278",
    "exp024_calibration.csv": "e58785191e3e40330d978eb811e317ef0c6d7bc6c933eada0ccbbeb40aed8cd7",
    "exp024_recovery.csv": "16a69c59678855bc5977c01ef268c70261f0b086ea1923abd468beb3b8c4ecd4",
}


def _spec_files(spec: SeedSpec) -> set[str]:
    return {
        f"{p.data_dir}/{d.file}" for p in spec.projects for e in p.experiments for d in e.datasets
    }


def test_committed_csvs_match_generator() -> None:
    for name, text in generate().items():
        assert (DATA_DIR / name).read_text(encoding="utf-8") == text, name


def test_every_csv_is_referenced_exactly_once() -> None:
    on_disk = {str(p.relative_to(DATA_DIR)) for p in DATA_DIR.rglob("*.csv")}
    spec = load_seed_spec("lab")
    referenced = [
        f"{p.data_dir}/{d.file}" for p in spec.projects for e in p.experiments for d in e.datasets
    ]
    assert len(referenced) == len(set(referenced))
    assert set(referenced) == on_disk == set(generate())


def test_generator_streams_are_independent() -> None:
    """Re-generating one design must not depend on the order designs are generated in."""
    project_no, designs = gen.DESIGNS["residue"]
    d = designs["#030"]
    assert d.calibration is not None
    alone = gen.calibration_csv(gen._rng(project_no, "#030", "calibration"), d.panel, d.calibration)
    assert alone == generate()[gen.file_name("residue", "#030", "calibration")]


def test_reference_profile_is_the_original_seed() -> None:
    spec = load_seed_spec("reference")
    (project,) = spec.projects
    assert [e.code for e in project.experiments] == list(REFERENCE_CODES)
    assert project.experiments[0].parent_code is None  # #018 is the root
    assert all(e.parent_code == "#018" for e in project.experiments[1:])
    assert [(c.project, c.experiment) for c in spec.history.critiques] == [("residue", "#024")]
    assert spec.history.decisions == []
    lab_residue = load_seed_spec("lab").project("residue")
    for exp in project.experiments:  # same originals as in the lab profile
        lab_exp = lab_residue.experiment(exp.code)
        assert exp.raw_note == lab_exp.raw_note
        assert exp.condition_block == lab_exp.condition_block


def test_reference_csvs_keep_original_bytes() -> None:
    legacy = gen.generate_legacy()
    assert set(legacy) == _spec_files(load_seed_spec("reference"))
    for path, text in legacy.items():
        name = path.split("/")[-1]
        assert hashlib.sha256(text.encode("utf-8")).hexdigest() == ORIGINAL_SHA256[name], name


def test_lab_profile_shape() -> None:
    spec = load_seed_spec("lab")
    residue, acids = spec.project("residue"), spec.project("organic_acids")
    assert [e.code for e in residue.experiments] == [f"#{n:03d}" for n in range(1, 31)]
    assert [e.code for e in acids.experiments] == [f"#OA{n:02d}" for n in range(1, 13)]
    assert sum(len(p.experiments) for p in spec.projects) == 42
    for project in spec.projects:
        assert all(e.datasets for e in project.experiments), "every experiment has data"
        dates = [e.performed_on for e in project.experiments]
        assert dates == sorted(dates)


def test_csvs_contain_designed_defects() -> None:
    """Missing values, aborted runs and outliers are present (not just clean noise)."""

    def rows(name: str) -> list[dict[str, str]]:
        text = (DATA_DIR / name).read_text(encoding="utf-8")
        return list(csv.DictReader(io.StringIO(text)))

    rec002 = rows("residue/exp002_recovery.csv")
    assert len(rec002) == 10 * 5 - 1  # S-07 thiabendazole not reported
    assert not any(r["injection_id"] == "S-07" and r["analyte"] == "thiabendazole" for r in rec002)
    assert {r["injection_id"] for r in rows("residue/exp012_recovery.csv")} == {
        f"S-{n:02d}" for n in range(1, 7)
    }  # sequence aborted after S-06
    assert "S-05" not in {r["injection_id"] for r in rows("organic_acids/oa03_recovery.csv")}
    rec007 = rows("residue/exp007_recovery.csv")
    s04 = [float(r["analyte_area"]) for r in rec007 if r["injection_id"] == "S-04"]
    s03 = [float(r["analyte_area"]) for r in rec007 if r["injection_id"] == "S-03"]
    assert sum(s04) > 1.5 * sum(s03)  # double spike
    for name in generate():  # no blank cells: analysis does not accept NaN yet
        assert all(all(v != "" for v in r.values()) for r in rows(name)), name


def test_decision_spec_validation() -> None:
    with pytest.raises(ValidationError):
        DecisionSpec(
            id="X",
            project="residue",
            experiment="#009",
            proposal_change_keys=["ph"],
            action="reject",
            rationale="사유 없음",
            decided_by="김연구",
        )
    ok = DecisionSpec(
        id="Y",
        project="residue",
        experiment="#009",
        proposal_change_keys=["ph"],
        action="reject",
        reason="budget",
        rationale="예산 부족",
        decided_by="김연구",
    )
    assert ok.stored_rationale() == "[예산] 예산 부족"


def test_profile_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(PROFILE_ENV, raising=False)
    assert resolve_profile() == "reference"
    monkeypatch.setenv(PROFILE_ENV, "lab")
    assert resolve_profile() == "lab"
    assert resolve_profile("reference") == "reference"
    with pytest.raises(ValueError):
        resolve_profile("demo")
