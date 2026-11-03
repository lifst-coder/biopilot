"""Claude-mode evaluation set for the Partner critique (PAR-3).

Runs the critique engine on the 7 seed experiments and scores each draft:

* **grounding pass** — the draft passes the same validation the service applies
  (known evidence keys, no ungrounded numbers, no repeat of a decided proposal);
* **expected-finding recall** — share of expected points (keyword alternatives, see
  :data:`EXPECTED`) found in the draft's findings/assessment prose.

Usage::

    python -m app.partner.scripts.eval_partner [--engine claude|rules] [--output report.json]

Without ``ANTHROPIC_API_KEY`` the Claude evaluation is skipped (exit 0, ``skipped`` report).
``--engine rules`` evaluates the offline engine (the reference: recall should be 1.0).
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import Database
from app.core.llm import LLMGateway, get_gateway
from app.eln import service as eln
from app.partner.context import build_context
from app.partner.engines.claude import ClaudeCritiqueEngine
from app.partner.engines.rules import RulesCritiqueEngine
from app.partner.schemas import CritiqueDraft
from app.partner.service import validate_draft

#: Expected critique points per seed experiment; each point is a tuple of alternatives.
EXPECTED: dict[str, list[tuple[str, ...]]] = {
    "#018": [("허용 기준 충족", "기준 충족", "위반이 발견되지")],
    "#019": [("회수율 저하", "낮아"), ("원인 분리 불가", "동시에 바뀌", "동시 변경"), ("pH",)],
    "#020": [("동시에 바뀌", "동시 변경", "원인 분리 불가")],
    "#021": [("매트릭스 효과",), ("imidacloprid",)],
    "#022": [("용매", "매트릭스 매칭")],
    "#023": [("1/x",), ("가중",)],
    "#024": [
        ("허용 범위", "기준 미달"),
        ("carbendazim",),
        ("동시에 바뀌", "동시 변경", "원인 분리 불가"),
        ("구분 불가", "분리할 수 없", "확정 불가"),
        ("전·후 첨가", "post-extraction", "추출 후 첨가"),
        ("IS",),
    ],
}


class ExperimentScore(BaseModel):
    code: str
    produced: bool
    grounded: bool
    failure_reason: str | None
    recall: float
    missed: list[str]


class EvalReport(BaseModel):
    engine: str
    model: str | None
    generated_at: str
    skipped: bool = False
    skip_reason: str | None = None
    experiments: list[ExperimentScore] = []
    grounding_pass_rate: float | None = None
    expected_recall: float | None = None


def draft_text(draft: CritiqueDraft) -> str:
    """All prose an evaluator may match expectations against."""
    parts = [draft.summary] + [f"{f.title} {f.body}" for f in draft.findings]
    for a in draft.assessments:
        parts += [a.claim, a.verdict_reason]
        parts += [m.name for m in a.missing_controls]
        parts += [x.statement for x in a.undetermined_reasons]
    return "\n".join(parts)


def score(code: str, draft: CritiqueDraft | None, failure: str | None) -> ExperimentScore:
    """Score one draft against :data:`EXPECTED`."""
    expected = EXPECTED.get(code, [])
    if draft is None:
        return ExperimentScore(
            code=code,
            produced=False,
            grounded=False,
            failure_reason=failure or "no draft",
            recall=0.0,
            missed=[alts[0] for alts in expected],
        )
    text = draft_text(draft)
    missed = [alts[0] for alts in expected if not any(a in text for a in alts)]
    recall = 1.0 if not expected else (len(expected) - len(missed)) / len(expected)
    return ExperimentScore(
        code=code,
        produced=True,
        grounded=failure is None,
        failure_reason=failure,
        recall=recall,
        missed=missed,
    )


def evaluate(session: Session, project_id: int, gateway: LLMGateway | None) -> EvalReport:
    """Evaluate Claude (``gateway``) or, with ``None``, the rules engine on every experiment."""
    scores: list[ExperimentScore] = []
    for exp in eln.list_experiments(session, project_id):
        ctx = build_context(session, exp.id)
        if gateway is None:
            draft: CritiqueDraft | None = RulesCritiqueEngine().critique(ctx)
        else:
            draft = ClaudeCritiqueEngine(gateway).critique(ctx)
        failure = validate_draft(draft, ctx) if draft is not None else "no draft"
        scores.append(score(exp.code, draft, failure))
    n = len(scores) or 1
    return EvalReport(
        engine="rules" if gateway is None else "claude",
        model=None if gateway is None else gateway.model_name,
        generated_at=datetime.now(UTC).isoformat(),
        experiments=scores,
        grounding_pass_rate=sum(s.grounded for s in scores) / n,
        expected_recall=sum(s.recall for s in scores) / n,
    )


def run(engine: str, gateway: LLMGateway | None = None) -> EvalReport:
    """Seed an in-memory DB and evaluate. Claude without a key → skipped report."""
    if engine == "claude":
        gateway = gateway or get_gateway()
        if gateway.mode != "claude":
            return EvalReport(
                engine="claude",
                model=None,
                generated_at=datetime.now(UTC).isoformat(),
                skipped=True,
                skip_reason="ANTHROPIC_API_KEY not set — Claude evaluation skipped",
            )
    from app.seed.loader import seed

    db = Database("sqlite://")
    db.create_all()
    with db.session() as session:
        project_id = seed(session)
        return evaluate(session, project_id, gateway if engine == "claude" else None)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--engine", choices=["claude", "rules"], default="claude")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)
    get_settings.cache_clear()
    report = run(args.engine)
    text = report.model_dump_json(indent=2)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
    print(report.skip_reason if report.skipped else text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
