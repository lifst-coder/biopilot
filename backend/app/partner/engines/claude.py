"""Claude-backed critique engine (only when ANTHROPIC_API_KEY is configured).

Claude receives the same grounded context the rules engine uses and must return a
:class:`CritiqueDraft`. The service re-validates the draft (evidence keys exist,
no ungrounded numbers) and falls back to rules if validation fails.
"""

from __future__ import annotations

import json

from app.core.llm import LLMGateway
from app.partner.context import CritiqueContext
from app.partner.schemas import CritiqueDraft

SYSTEM_PROMPT = """\
You are BioPilot's research partner for an analytical chemistry lab (pesticide residues,
QuEChERS extraction, LC-MS/MS). Your job is scientific critique, not cheerleading.

Rules you must follow:
- Write all prose in Korean.
- Use ONLY the facts in the provided EVIDENCE list, CONDITIONS and CRITERIA. Every
  finding, hypothesis and proposal must cite the evidence keys (e.g. "E3") it relies on.
- Do not compute new numbers. You may restate a number only exactly as it appears in the
  evidence (rounded to at most 3 decimals). Prefer citing the key instead of the number.
- Point out confounded designs, missing controls, and alternative explanations.
- Proposals describe the next experiment as condition-block changes (key/value).
"""


def build_prompt(ctx: CritiqueContext) -> str:
    """Serialise the grounded context for Claude."""
    payload = {
        "experiment": {
            "code": ctx.experiment.code,
            "title": ctx.experiment.title,
            "raw_note": ctx.experiment.raw_note,
        },
        "baseline": ctx.baseline.code if ctx.baseline else None,
        "CONDITIONS": ctx.experiment.condition_block.model_dump(exclude_none=True),
        "CONDITION_CHANGES": (
            [c.model_dump() for c in ctx.diff.condition_changes] if ctx.diff else []
        ),
        "CRITERIA": ctx.criteria.model_dump(),
        "QC_FLAG_CODES": sorted({f.code for f in ctx.metrics.flags}),
        "EVIDENCE": [e.model_dump(exclude_none=True) for e in ctx.evidence.items],
    }
    return "Critique this experiment. Context (JSON):\n" + json.dumps(
        payload, ensure_ascii=False, indent=2
    )


class ClaudeCritiqueEngine:
    """Delegates to the shared LLM gateway with the CritiqueDraft output schema."""

    name = "claude"

    def __init__(self, gateway: LLMGateway) -> None:
        self._gateway = gateway

    def critique(self, ctx: CritiqueContext) -> CritiqueDraft | None:
        return self._gateway.generate(
            system=SYSTEM_PROMPT, prompt=build_prompt(ctx), schema=CritiqueDraft
        )
