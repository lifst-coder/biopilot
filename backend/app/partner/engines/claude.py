"""Claude-backed critique engine (only when ANTHROPIC_API_KEY is configured).

Claude receives the same grounded context the rules engine uses and must return a
:class:`CritiqueDraft` — the *same schema* as the rules engine, including the
structured ``assessments`` (Research Critic) and ``design`` (Next Experiment
Designer). The service re-validates the draft (evidence keys exist, no ungrounded
numbers, no repeat of a decided proposal) and falls back to rules if validation fails.
"""

from __future__ import annotations

import json
from typing import Any

from app.core.llm import LLMGateway
from app.partner.context import CritiqueContext, ProjectContext
from app.partner.feedback import DecisionMemory
from app.partner.knowledge import CONTROLS, DESIGNS, EXPLANATIONS
from app.partner.schemas import CritiqueDraft

SYSTEM_PROMPT = """\
You are BioPilot's research partner for an analytical chemistry lab (pesticide residues,
QuEChERS extraction, LC-MS/MS). Your job is scientific critique, not cheerleading.

Rules you must follow:
- Write all prose in Korean.
- Use ONLY the facts in the provided EVIDENCE list, CONDITIONS and CRITERIA. Every
  finding, hypothesis, proposal and critic argument must cite the evidence keys (e.g.
  "E3") it relies on. Mark arguments that rest on general domain knowledge with
  basis="domain_rule" and arguments that rest on a researcher decision with basis="decision".
- Do not compute new numbers. You may restate a number only exactly as it appears in the
  evidence (rounded). Prefer citing the key instead of the number. Replicates in a design
  must equal an evidence value.
- Fill `assessments` with a structured critique: claim, verdict (supported / refuted /
  indeterminate / no_issue), 지지 근거 (supporting_evidence), 반대 근거 (opposing_evidence),
  누락 대조군 (missing_controls), 대안 설명 (alternative_explanations) and 현재 데이터로 확정
  불가한 이유 (undetermined_reasons). Distinguish extraction/clean-up loss from matrix
  effects: recovery against a solvent curve mixes both; only a pre- vs post-extraction spike
  under the same protocol, or a matrix-matched curve, separates them.
- Proposals describe the next experiment as condition-block changes plus a `design`
  (variables, controls, replicates, measurements, expected_outcomes, discriminating_power,
  basis_experiment_ids).
- DECISION_HISTORY lists researcher decisions. NEVER repeat a decided proposal (same
  changes). When a rejection names a constraint (e.g. no blank matrix), propose an
  alternative that avoids it and cite the decision evidence key. Fill `decision_feedback`.
"""


def _decisions_payload(memory: DecisionMemory) -> list[dict[str, Any]]:
    return [
        {
            "decision_evidence_key": d.evidence.key if d.evidence else None,
            "proposal_id": d.proposal_id,
            "title": d.title,
            "action": d.action,
            "rationale": d.rationale,
            "reason_category": d.reason_category,
            "unavailable_resources": d.constraints,
            "addresses_controls": d.addresses_controls,
            "decided_changes": [m.model_dump() for m in d.modifications] or None,
        }
        for d in memory.decisions
    ]


def _knowledge_payload() -> dict[str, Any]:
    return {
        "explanations": {k: v.label for k, v in EXPLANATIONS.items()},
        "controls": {k: v.name for k, v in CONTROLS.items()},
        "design_templates": {
            k: {"title": v.title, "requires": list(v.requires), "power": v.power}
            for k, v in DESIGNS.items()
        },
    }


def build_prompt(ctx: CritiqueContext) -> str:
    """Serialise the grounded context for Claude."""
    payload = {
        "experiment": {
            "id": ctx.experiment.id,
            "code": ctx.experiment.code,
            "title": ctx.experiment.title,
            "raw_note": ctx.experiment.raw_note,
        },
        "baseline": ctx.baseline.code if ctx.baseline else None,
        "project_experiments": {e.code: e.id for e in ctx.project_experiments},
        "CONDITIONS": ctx.experiment.condition_block.model_dump(exclude_none=True),
        "CONDITION_CHANGES": (
            [c.model_dump() for c in ctx.diff.condition_changes] if ctx.diff else []
        ),
        "MATRIX_EFFECT_PROTOCOL_CHANGES": [c.model_dump() for c in ctx.me_protocol_changes],
        "CRITERIA": ctx.criteria.model_dump(),
        "QC_FLAG_CODES": sorted({f.code for f in ctx.metrics.flags}),
        "EVIDENCE": [e.model_dump(exclude_none=True) for e in ctx.evidence.items],
        "DECISION_HISTORY": _decisions_payload(ctx.decisions),
        "DOMAIN_KNOWLEDGE": _knowledge_payload(),
    }
    return "Critique this experiment. Context (JSON):\n" + json.dumps(
        payload, ensure_ascii=False, indent=2
    )


def build_project_prompt(ctx: ProjectContext) -> str:
    """Serialise a project-level context (PAR-7) for Claude."""
    payload = {
        "project": ctx.project_name,
        "experiments": [
            {
                "id": e.id,
                "code": e.code,
                "parent_experiment_id": e.parent_experiment_id,
                "CONDITIONS": e.condition_block.model_dump(exclude_none=True),
            }
            for e in ctx.experiments
        ],
        "CRITERIA": ctx.criteria.model_dump(),
        "EVIDENCE": [e.model_dump(exclude_none=True) for e in ctx.evidence.items],
        "DECISION_HISTORY": _decisions_payload(ctx.decisions),
    }
    return (
        "Critique this whole project (trends across experiments; no proposals). "
        "Context (JSON):\n" + json.dumps(payload, ensure_ascii=False, indent=2)
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

    def critique_project(self, ctx: ProjectContext) -> CritiqueDraft | None:
        return self._gateway.generate(
            system=SYSTEM_PROMPT, prompt=build_project_prompt(ctx), schema=CritiqueDraft
        )
