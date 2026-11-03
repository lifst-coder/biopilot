"""Deterministic generator for every seed CSV in ``app/seed/data/<project>/``.

The committed CSVs are the source of truth; this module documents *how* they were
designed (true recoveries, noise model, IS behaviour, missing values and outliers) and
lets ``tests/test_seed*.py`` assert that they are reproducible. Run
``python -m app.seed.generate`` to rewrite them.

Two generations live here:

* **Legacy** (residue #018–#024, 12 files): one shared random stream in a fixed order.
  Kept *verbatim* so the ``reference`` profile is byte-identical to the original seed.
* **Designs** (every other experiment): one independent random stream per file,
  ``default_rng([SEED, project_no, experiment_no, kind_no])``, so adding or editing one
  experiment never changes another experiment's numbers.

Noise model (designs)
---------------------
* Calibration: response ratio ``(slope·x + intercept)·(1 + N(0, prop_cv)) + N(0, abs_sd)``,
  IS area ``is_area·(1 + N(0, 0.03))``.
* Recovery: per-sample recovery ``R·(1 + N(0, rec_cv))`` — ``rec_cv`` encodes the
  operator's habit (manual shaking ≈ 6–8 %, mechanical shaker ≈ 2.5–3.5 %); measurement
  noise ``N(0, 0.02)`` on the ratio; IS factors per injection (drift / suppression) with
  imperfect analyte co-suppression ``N(0, 0.04)``.
* Matrix effect: absolute areas ``abs_slope·x·(1 + ME)·(1 + N(0, 0.015))``.
* Real-lab defects are explicit in each design: ``missing`` rows (unreported peaks),
  ``skipped`` injections (broken vial), ``injected`` (sequence aborted) and
  ``outliers`` (double spike, interference). Numeric cells are never blank because the
  analysis service does not accept NaN yet (see CHANGES_REQUESTED.md).

The *apparent* recovery ``R`` already contains everything the IS does not correct
(adsorption losses, uncompensated ESI suppression); the generator does not simulate
chemistry, it reproduces designed outcomes with realistic scatter.
"""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

DATA_DIR = Path(__file__).parent / "data"
SEED = 20261103

# =========================================================================== legacy
# Residue #018–#024. Do not edit: the reference profile depends on these bytes.

ANALYTES: tuple[str, ...] = (
    "azoxystrobin",
    "carbendazim",
    "imidacloprid",
    "tebuconazole",
    "thiabendazole",
)
#: True response-ratio slope (per ng/mL) and intercept of each analyte.
SLOPE = {
    "azoxystrobin": 0.0150,
    "carbendazim": 0.0120,
    "imidacloprid": 0.0068,
    "tebuconazole": 0.0081,
    "thiabendazole": 0.0095,
}
INTERCEPT = 0.0015
IS_AREA = 1.20e6
#: Absolute area per ng/mL in solvent (matrix-effect experiment, no IS).
ABS_SLOPE = {a: SLOPE[a] * IS_AREA for a in ANALYTES}

TRUE_RECOVERY: dict[str, dict[str, float]] = {
    "018": {
        "azoxystrobin": 90,
        "carbendazim": 87,
        "imidacloprid": 91,
        "tebuconazole": 89,
        "thiabendazole": 88,
    },
    "019": {
        "azoxystrobin": 89,
        "carbendazim": 79,
        "imidacloprid": 90,
        "tebuconazole": 88,
        "thiabendazole": 82,
    },
    "020": {
        "azoxystrobin": 91,
        "carbendazim": 88,
        "imidacloprid": 90,
        "tebuconazole": 88,
        "thiabendazole": 87,
    },
    "022": {
        "azoxystrobin": 90,
        "carbendazim": 88,
        "imidacloprid": 89,
        "tebuconazole": 89,
        "thiabendazole": 87,
    },
    "024": {
        "azoxystrobin": 71,
        "carbendazim": 46,
        "imidacloprid": 73,
        "tebuconazole": 70,
        "thiabendazole": 50,
    },
}
MATRIX_EFFECT = {
    "azoxystrobin": -6.0,
    "carbendazim": -14.0,
    "imidacloprid": -27.0,
    "tebuconazole": -9.0,
    "thiabendazole": -11.0,
}
#: Injection id → IS suppression factor (fraction of normal IS area) for #024.
IS_SUPPRESSION_024 = {"S-03": 0.40, "S-07": 0.45, "S-09": 0.42}

CAL_HEADER = ["injection_id", "level_ng_ml", "analyte", "analyte_area", "is_area"]
REC_HEADER = ["injection_id", "sample_id", "analyte", "spike_ng_g", "analyte_area", "is_area"]
ME_HEADER = ["injection_id", "curve", "level_ng_ml", "analyte", "analyte_area"]


def _csv(header: list[str], rows: list[list[object]]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    return buf.getvalue()


def _calibration(
    rng: np.random.Generator, levels: list[float], reps: int, prop_cv: float, abs_sd: float
) -> str:
    rows: list[list[object]] = []
    n = 0
    for level in levels:
        for _ in range(reps):
            n += 1
            inj = f"CAL-{n:02d}"
            is_area = IS_AREA * (1 + rng.normal(0, 0.03))
            for a in ANALYTES:
                ratio = SLOPE[a] * level + INTERCEPT
                ratio = ratio * (1 + rng.normal(0, prop_cv)) + rng.normal(0, abs_sd)
                rows.append([inj, level, a, round(ratio * is_area), round(is_area)])
    return _csv(CAL_HEADER, rows)


def _recovery(
    rng: np.random.Generator,
    recovery: dict[str, float],
    spikes: list[tuple[float, int]],
    suppression: dict[str, float] | None = None,
) -> str:
    rows: list[list[object]] = []
    n = 0
    for spike, reps in spikes:
        for r in range(reps):
            n += 1
            inj, sample = f"S-{n:02d}", f"R{spike:g}-{r + 1}"
            s = (suppression or {}).get(inj, 1.0)
            is_area = IS_AREA * (1 + rng.normal(0, 0.03)) * s
            for a in ANALYTES:
                true_rec = recovery[a] / 100 * (1 + rng.normal(0, 0.03))
                conc_extract = spike * true_rec  # 10 g / 10 mL → factor 1
                ratio = (SLOPE[a] * conc_extract + INTERCEPT) * (1 + rng.normal(0, 0.02))
                # co-suppression: analyte suppressed slightly differently from the IS
                ratio *= 1 + (rng.normal(0, 0.04) if s < 1 else 0.0)
                rows.append([inj, sample, a, spike, round(ratio * is_area), round(is_area)])
    return _csv(REC_HEADER, rows)


def _matrix_effect(rng: np.random.Generator, levels: list[float]) -> str:
    rows: list[list[object]] = []
    n = 0
    for curve in ("solvent", "matrix"):
        for level in levels:
            n += 1
            inj = f"ME-{n:02d}"
            for a in ANALYTES:
                factor = 1 + (MATRIX_EFFECT[a] / 100 if curve == "matrix" else 0.0)
                area = ABS_SLOPE[a] * level * factor * (1 + rng.normal(0, 0.015))
                rows.append([inj, curve, level, a, round(area)])
    return _csv(ME_HEADER, rows)


def generate_legacy() -> dict[str, str]:
    """Residue #018–#024 files (``{path relative to DATA_DIR: csv_text}``)."""
    rng = np.random.default_rng(SEED)
    std_levels = [2.0, 5.0, 10.0, 20.0, 50.0, 100.0]
    spikes = [(10.0, 5), (50.0, 5)]
    files: dict[str, str] = {}
    for code in ("018", "019", "020"):
        files[f"exp{code}_calibration.csv"] = _calibration(rng, std_levels, 1, 0.02, 0.0003)
        files[f"exp{code}_recovery.csv"] = _recovery(rng, TRUE_RECOVERY[code], spikes)
    files["exp021_matrix_effect.csv"] = _matrix_effect(rng, [5.0, 10.0, 20.0, 50.0, 100.0])
    files["exp022_calibration.csv"] = _calibration(rng, std_levels, 1, 0.02, 0.0003)
    files["exp022_recovery.csv"] = _recovery(rng, TRUE_RECOVERY["022"], [(10.0, 6)])
    files["exp023_calibration.csv"] = _calibration(
        rng, [1.0, 2.0, 5.0, 10.0, 20.0, 50.0, 100.0, 200.0], 3, 0.03, 0.0015
    )
    files["exp024_calibration.csv"] = _calibration(rng, std_levels, 1, 0.02, 0.0003)
    files["exp024_recovery.csv"] = _recovery(rng, TRUE_RECOVERY["024"], spikes, IS_SUPPRESSION_024)
    return {f"residue/{name}": text for name, text in files.items()}


# ========================================================================== designs

#: ``(injection_id, analyte)`` — ``"*"`` as analyte means every analyte of the injection.
RowKey = tuple[str, str]


@dataclass(frozen=True)
class Panel:
    """Analytes of a project with IS-normalised response slopes (per ng/mL)."""

    analytes: tuple[str, ...]
    slope: Mapping[str, float]
    intercept: float
    is_area: float


@dataclass(frozen=True)
class CalibrationDesign:
    """Solvent calibration standards, injected in ascending order."""

    levels: tuple[float, ...]
    reps: int = 1
    prop_cv: float = 0.02
    abs_sd: float = 0.0003
    #: Scales every peak area incl. the IS (instrument sensitivity, injection volume).
    area_scale: float = 1.0
    missing: tuple[RowKey, ...] = ()
    outliers: Mapping[RowKey, float] = field(default_factory=dict)


@dataclass(frozen=True)
class RecoveryDesign:
    """Spiked samples. ``recovery`` is the apparent recovery (%) per analyte."""

    recovery: Mapping[str, float]
    spikes: tuple[tuple[float, int], ...] = ((10.0, 5), (50.0, 5))
    rec_cv: float = 0.03
    area_scale: float = 1.0
    #: Injection id → IS area factor (drift, suppression).
    is_factor: Mapping[str, float] = field(default_factory=dict)
    #: Sequence aborted after this many injections (later ones never run).
    injected: int | None = None
    skipped: tuple[str, ...] = ()
    missing: tuple[RowKey, ...] = ()
    outliers: Mapping[RowKey, float] = field(default_factory=dict)


@dataclass(frozen=True)
class MatrixEffectDesign:
    """Solvent vs matrix-matched curves (absolute areas, no IS)."""

    effect_pct: Mapping[str, float]
    levels: tuple[float, ...] = (5.0, 10.0, 20.0, 50.0, 100.0)
    cv: float = 0.015


@dataclass(frozen=True)
class ExperimentDesign:
    """Everything needed to synthesise one experiment's CSVs."""

    panel: Panel
    calibration: CalibrationDesign | None = None
    recovery: RecoveryDesign | None = None
    matrix_effect: MatrixEffectDesign | None = None


def _outlier(outliers: Mapping[RowKey, float], inj: str, analyte: str) -> float:
    return outliers.get((inj, analyte), outliers.get((inj, "*"), 1.0))


def calibration_csv(rng: np.random.Generator, panel: Panel, d: CalibrationDesign) -> str:
    """Calibration CSV for one design."""
    rows: list[list[object]] = []
    n = 0
    for level in d.levels:
        for _ in range(d.reps):
            n += 1
            inj = f"CAL-{n:02d}"
            is_area = panel.is_area * d.area_scale * (1 + rng.normal(0, 0.03))
            for a in panel.analytes:
                ratio = panel.slope[a] * level + panel.intercept
                ratio = ratio * (1 + rng.normal(0, d.prop_cv)) + rng.normal(0, d.abs_sd)
                ratio *= _outlier(d.outliers, inj, a)
                if (inj, a) in d.missing:
                    continue
                rows.append([inj, level, a, round(ratio * is_area), round(is_area)])
    return _csv(CAL_HEADER, rows)


def recovery_csv(
    rng: np.random.Generator, panel: Panel, d: RecoveryDesign, extract_factor: float
) -> str:
    """Recovery CSV. ``extract_factor`` = extraction volume (mL) / sample mass (g)."""
    rows: list[list[object]] = []
    n = 0
    for spike, reps in d.spikes:
        for r in range(reps):
            n += 1
            inj, sample = f"S-{n:02d}", f"R{spike:g}-{r + 1}"
            s = d.is_factor.get(inj, 1.0)
            is_area = panel.is_area * d.area_scale * (1 + rng.normal(0, 0.03)) * s
            values: list[list[object]] = []
            for a in panel.analytes:
                rec = d.recovery[a] / 100 * (1 + rng.normal(0, d.rec_cv))
                conc_extract = spike * rec / extract_factor
                ratio = (panel.slope[a] * conc_extract + panel.intercept) * (
                    1 + rng.normal(0, 0.02)
                )
                ratio *= 1 + (rng.normal(0, 0.04) if s < 1 else 0.0)
                ratio *= _outlier(d.outliers, inj, a)
                if (inj, a) not in d.missing:
                    values.append([inj, sample, a, spike, round(ratio * is_area), round(is_area)])
            # random draws happen before the skip checks so that a defect never shifts
            # the noise of the remaining injections
            if (d.injected is None or n <= d.injected) and inj not in d.skipped:
                rows += values
    return _csv(REC_HEADER, rows)


def matrix_effect_csv(rng: np.random.Generator, panel: Panel, d: MatrixEffectDesign) -> str:
    """Matrix-effect CSV (absolute areas)."""
    rows: list[list[object]] = []
    n = 0
    for curve in ("solvent", "matrix"):
        for level in d.levels:
            n += 1
            inj = f"ME-{n:02d}"
            for a in panel.analytes:
                factor = 1 + (d.effect_pct[a] / 100 if curve == "matrix" else 0.0)
                abs_slope = panel.slope[a] * panel.is_area
                area = abs_slope * level * factor * (1 + rng.normal(0, d.cv))
                rows.append([inj, curve, level, a, round(area)])
    return _csv(ME_HEADER, rows)


# ----------------------------------------------------------------- residue designs

RESIDUE = Panel(ANALYTES, SLOPE, INTERCEPT, IS_AREA)
STD6 = (2.0, 5.0, 10.0, 20.0, 50.0, 100.0)
STD8 = (1.0, 2.0, 5.0, 10.0, 20.0, 50.0, 100.0, 200.0)
CAL = CalibrationDesign(STD6)
KIM_CV, LEE_CV = 0.07, 0.03  # manual vs mechanical shaking


def _r(azox: float, carb: float, imid: float, teb: float, thiab: float) -> dict[str, float]:
    return dict(zip(ANALYTES, (azox, carb, imid, teb, thiab), strict=True))


def _me(azox: float, carb: float, imid: float, teb: float, thiab: float) -> MatrixEffectDesign:
    return MatrixEffectDesign(_r(azox, carb, imid, teb, thiab))


RESIDUE_DESIGNS: dict[str, ExperimentDesign] = {
    # SOP v1 (EN 15662 citrate, 15 g / 15 mL, PSA only, 35 °C, unweighted)
    "#001": ExperimentDesign(RESIDUE, CAL, RecoveryDesign(_r(84, 81, 86, 83, 80), rec_cv=KIM_CV)),
    "#002": ExperimentDesign(
        RESIDUE,
        CAL,
        RecoveryDesign(_r(89, 87, 90, 88, 86), rec_cv=LEE_CV, missing=(("S-07", "thiabendazole"),)),
    ),
    "#003": ExperimentDesign(RESIDUE, matrix_effect=_me(-9, -21, -38, -12, -17)),
    # v1.1: + C18 in d-SPE
    "#004": ExperimentDesign(RESIDUE, CAL, RecoveryDesign(_r(90, 88, 91, 89, 88), rec_cv=LEE_CV)),
    "#005": ExperimentDesign(RESIDUE, matrix_effect=_me(-6, -15, -29, -9, -12)),
    "#006": ExperimentDesign(RESIDUE, CalibrationDesign(STD8, reps=3, prop_cv=0.03, abs_sd=0.0015)),
    "#007": ExperimentDesign(
        RESIDUE,
        CAL,
        RecoveryDesign(
            _r(87, 84, 88, 86, 84), rec_cv=0.065, outliers={("S-04", "*"): 1.85}
        ),  # double spike
    ),
    # v1.2: column 40 °C
    "#008": ExperimentDesign(RESIDUE, CAL, RecoveryDesign(_r(90, 88, 91, 89, 88), rec_cv=LEE_CV)),
    "#009": ExperimentDesign(  # methanol, 10 g / 15 mL
        RESIDUE, CAL, RecoveryDesign(_r(70, 72, 86, 66, 74), rec_cv=KIM_CV)
    ),
    "#010": ExperimentDesign(
        RESIDUE,
        CAL,
        RecoveryDesign(_r(91, 89, 90, 90, 88), spikes=((10.0, 6),), rec_cv=0.025),
    ),
    "#011": ExperimentDesign(  # ion source fouling: IS drifts down along the sequence
        RESIDUE,
        CAL,
        RecoveryDesign(
            _r(87, 85, 88, 86, 85),
            rec_cv=0.06,
            is_factor={"S-06": 0.62, "S-07": 0.56, "S-08": 0.46, "S-09": 0.53, "S-10": 0.42},
        ),
    ),
    "#012": ExperimentDesign(  # sequence aborted after S-06
        RESIDUE,
        CAL,
        RecoveryDesign(
            _r(87, 85, 88, 86, 84),
            rec_cv=0.06,
            is_factor={"S-04": 0.45, "S-05": 0.38, "S-06": 0.31},
            injected=6,
        ),
    ),
    "#013": ExperimentDesign(  # after maintenance: more sensitive, one interference
        RESIDUE,
        CalibrationDesign(STD6, reps=2, area_scale=1.3, outliers={("CAL-03", "imidacloprid"): 1.3}),
    ),
    "#014": ExperimentDesign(  # hygroscopic MgSO4 lot → reproduction fails
        RESIDUE,
        CAL,
        RecoveryDesign(_r(68, 72, 78, 66, 70), spikes=((10.0, 6),), rec_cv=0.12, area_scale=1.3),
    ),
    "#015": ExperimentDesign(
        RESIDUE,
        CAL,
        RecoveryDesign(_r(72, 74, 79, 70, 73), spikes=((10.0, 6),), rec_cv=0.10, area_scale=1.3),
    ),
    "#016": ExperimentDesign(
        RESIDUE,
        CAL,
        RecoveryDesign(_r(88, 86, 89, 87, 86), spikes=((10.0, 6),), rec_cv=0.06, area_scale=1.3),
    ),
    # SOP v2 (AOAC acetate, 10 g / 10 mL)
    "#017": ExperimentDesign(RESIDUE, CAL, RecoveryDesign(_r(91, 88, 91, 89, 88), rec_cv=LEE_CV)),
    "#025": ExperimentDesign(RESIDUE, CAL, RecoveryDesign(_r(89, 86, 90, 88, 86), rec_cv=LEE_CV)),
    "#026": ExperimentDesign(RESIDUE, CAL, RecoveryDesign(_r(72, 45, 75, 72, 49), rec_cv=0.065)),
    "#027": ExperimentDesign(RESIDUE, CAL, RecoveryDesign(_r(84, 73, 86, 83, 76), rec_cv=LEE_CV)),
    "#028": ExperimentDesign(  # #024 conditions, 1 µL injection: IS fine, GCB loss remains
        RESIDUE,
        CalibrationDesign(STD6, area_scale=0.2, abs_sd=0.0006),
        RecoveryDesign(_r(71, 46, 73, 70, 50), rec_cv=0.065, area_scale=0.2),
    ),
    "#029": ExperimentDesign(RESIDUE, CAL, RecoveryDesign(_r(86, 83, 87, 85, 83), rec_cv=0.075)),
    "#030": ExperimentDesign(RESIDUE, CAL, RecoveryDesign(_r(91, 89, 92, 90, 89), rec_cv=0.025)),
}

# ------------------------------------------------------------ organic-acid designs

ACIDS: tuple[str, ...] = (
    "citric acid",
    "fumaric acid",
    "lactic acid",
    "malic acid",
    "succinic acid",
)
_ACID_SLOPE = dict(zip(ACIDS, (0.0009, 0.0012, 0.0006, 0.0010, 0.0014), strict=True))
#: TPP measured in ESI+ by polarity switching (shared with the residue project).
ACIDS_TPP = Panel(ACIDS, _ACID_SLOPE, 0.002, IS_AREA)
#: Succinic acid-13C4: lower IS area → 2.5× steeper ratio slopes.
ACIDS_13C = Panel(ACIDS, {a: s * 2.5 for a, s in _ACID_SLOPE.items()}, 0.002, 4.8e5)
STD_OA = (20.0, 50.0, 100.0, 200.0, 500.0, 1000.0, 2000.0)
CAL_OA = CalibrationDesign(STD_OA, prop_cv=0.025, abs_sd=0.0002)
SPIKES_OA = ((5000.0, 5), (25000.0, 5))
ME_OA_LEVELS = (50.0, 100.0, 200.0, 500.0, 1000.0)


def _a(cit: float, fum: float, lac: float, mal: float, suc: float) -> dict[str, float]:
    return dict(zip(ACIDS, (cit, fum, lac, mal, suc), strict=True))


def _rec_oa(
    recovery: dict[str, float],
    rec_cv: float,
    *,
    is_factor: Mapping[str, float] | None = None,
    skipped: tuple[str, ...] = (),
    missing: tuple[RowKey, ...] = (),
    outliers: Mapping[RowKey, float] | None = None,
) -> RecoveryDesign:
    return RecoveryDesign(
        recovery,
        spikes=SPIKES_OA,
        rec_cv=rec_cv,
        is_factor=is_factor or {},
        skipped=skipped,
        missing=missing,
        outliers=outliers or {},
    )


ACID_DESIGNS: dict[str, ExperimentDesign] = {
    "#OA01": ExperimentDesign(ACIDS_TPP, CAL_OA, _rec_oa(_a(64, 82, 79, 69, 85), rec_cv=0.035)),
    "#OA02": ExperimentDesign(
        ACIDS_TPP, matrix_effect=MatrixEffectDesign(_a(-45, -8, -25, -38, -12), ME_OA_LEVELS)
    ),
    "#OA03": ExperimentDesign(  # doenjang; vial S-05 broken; IS drift (same week as #012)
        ACIDS_TPP,
        CAL_OA,
        _rec_oa(
            _a(55, 76, 70, 60, 79),
            rec_cv=0.07,
            is_factor={"S-08": 0.48, "S-09": 0.44},
            skipped=("S-05",),
        ),
    ),
    "#OA04": ExperimentDesign(ACIDS_TPP, CAL_OA, _rec_oa(_a(88, 90, 87, 86, 91), rec_cv=0.035)),
    "#OA05": ExperimentDesign(
        ACIDS_TPP, matrix_effect=MatrixEffectDesign(_a(-18, -5, -14, -15, -8), ME_OA_LEVELS)
    ),
    "#OA06": ExperimentDesign(  # PSA removes organic acids
        ACIDS_TPP,
        CAL_OA,
        _rec_oa(_a(18, 31, 42, 24, 36), rec_cv=0.09, outliers={("S-03", "citric acid"): 2.2}),
    ),
    "#OA07": ExperimentDesign(ACIDS_TPP, CAL_OA, _rec_oa(_a(84, 88, 86, 83, 89), rec_cv=0.035)),
    "#OA08": ExperimentDesign(ACIDS_13C, CAL_OA, _rec_oa(_a(95, 96, 94, 94, 99), rec_cv=0.025)),
    "#OA09": ExperimentDesign(
        ACIDS_13C,
        CAL_OA,
        _rec_oa(
            _a(92, 94, 91, 90, 98),
            rec_cv=0.065,
            is_factor={"S-02": 0.46, "S-05": 0.43, "S-09": 0.47},
        ),
    ),
    "#OA10": ExperimentDesign(ACIDS_13C, CAL_OA, _rec_oa(_a(70, 86, 82, 74, 88), rec_cv=0.03)),
    "#OA11": ExperimentDesign(
        ACIDS_13C,
        CAL_OA,
        _rec_oa(_a(96, 96, 95, 95, 99), rec_cv=0.06, missing=(("S-07", "fumaric acid"),)),
    ),
    "#OA12": ExperimentDesign(
        ACIDS_13C,
        CalibrationDesign((*STD_OA, 5000.0), reps=3, prop_cv=0.03, abs_sd=0.0006),
    ),
}

#: Scenario key → (project number for the RNG stream, designs).
DESIGNS: dict[str, tuple[int, dict[str, ExperimentDesign]]] = {
    "residue": (1, RESIDUE_DESIGNS),
    "organic_acids": (2, ACID_DESIGNS),
}
KIND_NO = {"calibration": 1, "recovery": 2, "matrix_effect": 3}


def _rng(project_no: int, code: str, kind: str) -> np.random.Generator:
    number = int("".join(ch for ch in code if ch.isdigit()))
    return np.random.default_rng([SEED, project_no, number, KIND_NO[kind]])


def _extract_factor(project_key: str, code: str) -> float:
    """``extraction_volume_ml / sample_mass_g`` read from the scenario JSON (single source)."""
    spec = json.loads((DATA_DIR / f"{project_key}.json").read_text(encoding="utf-8"))
    for exp in spec["experiments"]:
        if exp["code"] == code:
            cond = exp["condition_block"]
            return float(cond["extraction_volume_ml"]) / float(cond["sample_mass_g"])
    raise KeyError(code)


def file_name(project_key: str, code: str, kind: str) -> str:
    """Path (relative to DATA_DIR) of a designed dataset."""
    stem = code.lstrip("#").lower()
    prefix = "exp" if project_key == "residue" else ""
    return f"{project_key}/{prefix}{stem}_{kind}.csv"


def generate_designs() -> dict[str, str]:
    """Every designed (non-legacy) dataset."""
    files: dict[str, str] = {}
    for key, (project_no, designs) in DESIGNS.items():
        for code, d in designs.items():
            if d.calibration is not None:
                files[file_name(key, code, "calibration")] = calibration_csv(
                    _rng(project_no, code, "calibration"), d.panel, d.calibration
                )
            if d.recovery is not None:
                files[file_name(key, code, "recovery")] = recovery_csv(
                    _rng(project_no, code, "recovery"),
                    d.panel,
                    d.recovery,
                    _extract_factor(key, code),
                )
            if d.matrix_effect is not None:
                files[file_name(key, code, "matrix_effect")] = matrix_effect_csv(
                    _rng(project_no, code, "matrix_effect"), d.panel, d.matrix_effect
                )
    return files


def generate() -> dict[str, str]:
    """Return ``{path relative to DATA_DIR: csv_text}`` for every seed dataset."""
    return {**generate_legacy(), **generate_designs()}


def main() -> None:
    """Rewrite every seed CSV."""
    for name, text in generate().items():
        path = DATA_DIR / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        print(f"wrote {name}")


if __name__ == "__main__":
    main()
