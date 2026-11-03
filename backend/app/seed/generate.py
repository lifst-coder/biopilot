"""Deterministic generator for the seed CSV files in ``app/seed/data``.

The committed CSVs are the source of truth; this script documents *how* they were
designed (true recoveries, noise model, IS suppression) and lets tests assert they are
reproducible. Run ``python -m app.seed.generate`` to rewrite them.

Design targets (what the *analysis code* should recover from the CSVs):
* #018 baseline protocol: mean recovery ≈ 89 %
* #019 unbuffered pH: ≈ 86 % (benzimidazoles drop)
* #020 column change: ≈ 89 % (chromatography only)
* #021 matrix effect: imidacloprid ≈ −27 % (significant), others within ±20 %
* #022 repeatability (n=6 at 10 ng/g): ≈ 89 %, low RSD
* #023 calibration 1–200 ng/mL: 1/x weighting beats unweighted on back-calculation
* #024 5-min extraction + GCB sorbent: ≈ 62 %, IS suppression in 3 of 10 injections
"""

from __future__ import annotations

import csv
import io
from pathlib import Path

import numpy as np

DATA_DIR = Path(__file__).parent / "data"
SEED = 20261103

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
    return _csv(["injection_id", "level_ng_ml", "analyte", "analyte_area", "is_area"], rows)


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
    return _csv(
        ["injection_id", "sample_id", "analyte", "spike_ng_g", "analyte_area", "is_area"], rows
    )


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
    return _csv(["injection_id", "curve", "level_ng_ml", "analyte", "analyte_area"], rows)


def generate() -> dict[str, str]:
    """Return ``{filename: csv_text}`` for every seed dataset (deterministic)."""
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
    return files


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    for name, text in generate().items():
        (DATA_DIR / name).write_text(text, encoding="utf-8")
        print(f"wrote {name}")


if __name__ == "__main__":
    main()
