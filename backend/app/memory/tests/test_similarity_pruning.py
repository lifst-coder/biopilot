"""The pruned :func:`similar_pairs` returns exactly what scoring every pair returns.

Randomised condition blocks cover what the pruning and the vectorised scoring must not
get wrong: shared and missing keys, text values differing only in case/whitespace,
numeric keys with zero range, keys that are numeric in some experiments and text in
others, booleans, integers beyond 2**53, NaN and infinity, empty blocks, and thresholds
from 0.5 to 1.0 (the graphs use 0.9).
"""

from __future__ import annotations

import math
import random
from typing import Any

import pytest

from app.eln.schemas import ConditionBlock, ExperimentOut
from app.memory.conditions import similar_pairs, similar_pairs_bruteforce, similarity


def _exp(i: int, cond: dict[str, Any]) -> ExperimentOut:
    return ExperimentOut.model_construct(id=i, condition_block=ConditionBlock.model_validate(cond))


def _block(rng: random.Random, exotic: bool) -> dict[str, Any]:
    cond: dict[str, Any] = {}
    if rng.random() < 0.95:
        cond["matrix"] = rng.choice(["apple", "Apple ", "pear", "rice"])
    if rng.random() < 0.9:
        cond["cleanup_sorbent"] = rng.choice(["PSA 50 mg", "psa  50 mg", "GCB 7.5 mg", "C18"])
    if rng.random() < 0.9:
        cond["ph"] = rng.choice([4.5, 5.0, 5.5, 6.0, 6.5])
    if rng.random() < 0.9:
        cond["sample_mass_g"] = rng.choice([5, 10, 15])
    if rng.random() < 0.9:
        cond["extraction_volume_ml"] = rng.uniform(9.0, 11.0)
    cond["column_temp_c"] = 40.0  # zero range
    if rng.random() < 0.5:
        cond["instrument"] = rng.choice(["QqQ-1", "QqQ-2"])
    if exotic:
        if rng.random() < 0.5:  # numeric in some experiments, text in others
            cond["batch"] = rng.choice([1, 2, "1", "2", "B"])
        if rng.random() < 0.3:
            cond["flagged"] = rng.choice([True, False])
        if rng.random() < 0.2:
            cond["big"] = rng.choice([2**60, 2**60 + 1, 3])
        if rng.random() < 0.1:
            cond["dose"] = rng.choice([math.nan, math.inf, 1.0, 2.0])
    if rng.random() < 0.03:
        cond = {}
    return cond


@pytest.mark.parametrize("exotic", [False, True])
@pytest.mark.parametrize("seed", range(6))
def test_pruned_pairs_equal_all_pairs(seed: int, exotic: bool) -> None:
    rng = random.Random(seed)
    exps = [_exp(i, _block(rng, exotic)) for i in rng.sample(range(1, 1000), 160)]
    for threshold in (0.5, 0.75, 0.85, 0.9, 0.95, 1.0):
        expected = similar_pairs_bruteforce(exps, threshold)
        assert similar_pairs(exps, threshold) == expected, (seed, exotic, threshold)


def test_scores_equal_similarity_exactly() -> None:
    rng = random.Random(42)
    exps = [_exp(i, _block(rng, False)) for i in range(1, 120)]
    by_id = {e.id: e for e in exps}
    from app.memory.conditions import conditions, numeric_ranges

    ranges = numeric_ranges(exps)
    pairs = similar_pairs(exps, 0.6)
    assert len(pairs) > 100
    for a, b, score in pairs:
        expected, _ = similarity(conditions(by_id[a]), conditions(by_id[b]), ranges)
        assert score == expected  # bit-identical, not approx
