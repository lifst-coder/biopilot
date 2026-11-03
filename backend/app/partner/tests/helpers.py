"""Helpers for Partner tests: tweak a built context to simulate other data states."""

from __future__ import annotations

from typing import Any

from app.eln.schemas import ConditionBlock
from app.partner.context import CritiqueContext


def with_conditions(ctx: CritiqueContext, **extra: Any) -> CritiqueContext:
    """Return ``ctx`` whose experiment condition block has ``extra`` keys set."""
    block = ConditionBlock.model_validate(
        {**ctx.experiment.condition_block.model_dump(exclude_none=True), **extra}
    )
    ctx.experiment = ctx.experiment.model_copy(update={"condition_block": block})
    return ctx
