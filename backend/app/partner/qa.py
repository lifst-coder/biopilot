"""Q&A building blocks for the conversational Partner panel (rules mode + validation).

An answer is a list of :class:`AnswerStatement`. Each statement is a *fact*
(restates stored evidence), an *inference* (rule-based judgement over cited
evidence) or an *estimate* (추정 — no direct supporting data). :func:`label` enforces
the rule "근거 없는 추정은 '추정'으로 표시": any statement without evidence keys is
downgraded to ``estimate`` and rendered with a ``[추정]`` prefix.
"""

from __future__ import annotations

import re

from app.partner.schemas import (
    AlternativeExplanation,
    AnswerStatement,
    AskIntent,
    CritiqueOut,
    DecisionHistoryEntry,
    Evidence,
    ProposalOut,
    SourceRef,
)

TOPIC_KEYWORDS: dict[str, tuple[str, ...]] = {
    "recovery": ("회수율", "recovery"),
    "internal_standard": ("내부표준", "internal standard", "억제", "suppression"),
    "matrix_effect": ("매트릭스", "matrix"),
    "calibration": ("검량", "calibration", "r²", "r2", "가중", "weight"),
    "changes": ("변경", "차이", "diff", "비교", "바뀐", "조건"),
}
TOPIC_PREFIXES: dict[str, tuple[str, ...]] = {
    "recovery": ("recovery", "baseline_recovery", "delta:"),
    "internal_standard": ("is_",),
    "matrix_effect": ("me:",),
    "calibration": ("min_r2", "max_back_calc", "weighting:"),
    "changes": ("change:",),
}
INTENT_KEYWORDS: dict[AskIntent, tuple[str, ...]] = {
    "decisions": ("결정", "기각", "채택", "수락", "거절", "이력", "decision"),
    "next_experiment": ("다음 실험", "후속", "제안", "설계", "next experiment", "어떻게 하면"),
    "cause": ("왜", "원인", "이유", "why", "어째서", "때문"),
}
CODE_RE = re.compile(r"#\d{2,4}")
ESTIMATE_PREFIX = "[추정] "
STATUS_LABEL = {"plausible": "가능성 있음", "weakened": "약화됨", "untested": "미검증"}


def detect_topics(question: str) -> list[str]:
    """Evidence topics mentioned in the question (keyword table)."""
    q = question.lower()
    topics = [t for t, words in TOPIC_KEYWORDS.items() if any(w in q for w in words)]
    if re.search(r"\bis\b", q) and "internal_standard" not in topics:
        topics.append("internal_standard")
    return topics


def detect_intent(question: str, has_experiment: bool) -> AskIntent:
    """What the question asks for; without an experiment context it is project-level."""
    q = question.lower()
    for intent, words in INTENT_KEYWORDS.items():
        if any(w in q for w in words):
            if intent != "decisions" and not has_experiment:
                return "project"
            return intent
    return "facts" if has_experiment else "project"


def mentioned_codes(question: str) -> list[str]:
    """Experiment codes like ``#024`` mentioned in the question."""
    return CODE_RE.findall(question)


def label(statements: list[AnswerStatement]) -> list[AnswerStatement]:
    """Downgrade statements without evidence to ``estimate`` (추정)."""
    return [
        s if s.evidence_keys or s.kind == "estimate" else s.model_copy(update={"kind": "estimate"})
        for s in statements
    ]


def render(statements: list[AnswerStatement], intro: str | None = None) -> str:
    """Answer text: ``[추정]`` prefix for estimates, ``[E1][E4]`` citations for the rest."""
    lines = [intro] if intro else []
    for s in label(statements):
        prefix = ESTIMATE_PREFIX if s.kind == "estimate" else ""
        cite = "".join(f"[{k}]" for k in s.evidence_keys)
        lines.append(f"{prefix}{s.text}{' ' + cite if cite else ''}")
    return "\n".join(lines)


def cited_evidence(statements: list[AnswerStatement], pool: list[Evidence]) -> list[Evidence]:
    """Evidence items cited by the statements, in first-citation order."""
    by_key = {e.key: e for e in pool}
    out: list[Evidence] = []
    for s in statements:
        for k in s.evidence_keys:
            if k in by_key and by_key[k] not in out:
                out.append(by_key[k])
    return out


def sources_for(evidence: list[Evidence], extra: list[SourceRef] | None = None) -> list[SourceRef]:
    """Unique stored records behind the evidence (for 출처 display)."""
    seen: set[tuple[str, int]] = set()
    out: list[SourceRef] = []
    for ref in [
        *(extra or []),
        *(SourceRef(ref_type=e.ref_type, ref_id=e.ref_id, label=e.label) for e in evidence),
    ]:
        if (ref.ref_type, ref.ref_id) in seen:
            continue
        seen.add((ref.ref_type, ref.ref_id))
        out.append(ref)
    return out


def fmt_evidence(e: Evidence) -> str:
    """One evidence line ``- [E3] label: value unit (text)`` (display rounding only)."""
    if e.value is None:
        return f"- [{e.key}] {e.label}: {e.text or ''}".rstrip()
    if float(e.value).is_integer():
        value = f"{e.value:.0f}"
    elif abs(e.value) < 1:
        value = f"{e.value:.4g}"
    else:
        value = f"{e.value:.1f}"
    extra = f" ({e.text})" if e.text else ""
    return f"- [{e.key}] {e.label}: {value}{e.unit or ''}{extra}"


def _alt_statement(alt: AlternativeExplanation) -> AnswerStatement:
    keys = sorted({k for a in alt.supporting + alt.opposing for k in a.evidence_keys})
    return AnswerStatement(
        text=f"대안 설명 — {alt.label} ({STATUS_LABEL[alt.status]}): {alt.mechanism}",
        kind="estimate",
        evidence_keys=keys,
    )


def cause_statements(critique: CritiqueOut, proposals: list[ProposalOut]) -> list[AnswerStatement]:
    """Why-question answer built from a stored critique and its proposals."""
    out: list[AnswerStatement] = []
    feedback = [
        AnswerStatement(
            text=f"결정 반영: {fb.note}",
            kind="fact",
            evidence_keys=[fb.evidence_key] if fb.evidence_key else [],
        )
        for fb in critique.decision_feedback
    ]
    for f in critique.findings:
        if f.severity == "critical" or "대비 회수율" in f.title:
            out.append(AnswerStatement(text=f.body, kind="fact", evidence_keys=f.evidence_keys))
    assessment = next(iter(critique.assessments), None)
    if assessment is None:
        out += [
            AnswerStatement(
                text=f"{f.title}: {f.body}", kind="inference", evidence_keys=f.evidence_keys
            )
            for f in critique.findings
            if f.severity != "critical"
        ]
        out += feedback
    else:
        out.append(
            AnswerStatement(
                text=f"판정: {assessment.verdict_reason}",
                kind="inference",
                evidence_keys=sorted(
                    {k for m in assessment.missing_controls for k in m.evidence_keys}
                ),
            )
        )
        out += feedback
        for arg in assessment.supporting_evidence:
            kind = "fact" if arg.basis == "data" else "inference"
            prefix = "지지 근거" if arg.basis == "data" else "지지 근거(도메인 지식)"
            out.append(
                AnswerStatement(
                    text=f"{prefix}: {arg.statement}", kind=kind, evidence_keys=arg.evidence_keys
                )
            )
        out += [
            AnswerStatement(
                text=f"반대 근거: {arg.statement}", kind="fact", evidence_keys=arg.evidence_keys
            )
            for arg in assessment.opposing_evidence
        ]
        for m in assessment.missing_controls:
            text = f"누락 대조군: {m.name} — {m.purpose}"
            if m.decision_note:
                text += f" (결정 이력: {m.decision_note})"
            out.append(AnswerStatement(text=text, kind="inference", evidence_keys=m.evidence_keys))
        out += [
            AnswerStatement(
                text=f"확정 불가 이유: {arg.statement}",
                kind="inference" if arg.basis != "data" else "fact",
                evidence_keys=arg.evidence_keys,
            )
            for arg in assessment.undetermined_reasons
        ]
        out += [_alt_statement(alt) for alt in assessment.alternative_explanations]
    out += proposal_statements(proposals)
    return out


def proposal_statements(proposals: list[ProposalOut]) -> list[AnswerStatement]:
    """Pending proposals, highest priority first, with their design summary."""
    ranked = sorted(
        (p for p in proposals if p.status == "pending"), key=lambda p: (-p.priority, p.id)
    )
    out: list[AnswerStatement] = []
    for i, p in enumerate(ranked):
        head = "가장 우선 제안" if i == 0 else "다음 제안"
        text = f"{head} P{p.id}: {p.title}"
        keys = list(p.evidence_keys)
        if p.design is not None:
            d = p.design
            varied = ", ".join(v.label for v in d.variables if v.role == "varied")
            if varied:
                text += f" — 변수: {varied}"
            if d.replicates is not None and d.replicates_evidence_key:
                text += f", 반복 {d.replicates}회"
                keys.append(d.replicates_evidence_key)
            text += f", 예상 판별력 {d.discriminating_power}"
        if p.supersedes_proposal_ids:
            text += " (기각된 " + ", ".join(f"P{x}" for x in p.supersedes_proposal_ids) + " 대체)"
        out.append(AnswerStatement(text=text, kind="inference", evidence_keys=keys))
    if not out:
        out.append(AnswerStatement(text="대기 중인 후속 실험 제안이 없다.", kind="estimate"))
    return out


def decision_statements(
    entries: list[DecisionHistoryEntry], evidence: list[Evidence]
) -> list[AnswerStatement]:
    """Decision History answer; each entry cites its ``partner.Decision`` evidence."""
    keys = {e.ref_id: e.key for e in evidence if e.ref_type == "partner.Decision"}
    out = [
        AnswerStatement(
            text=(
                f"P{e.proposal_id} '{e.proposal_title}' ({e.experiment_code}) — "
                f"{e.decision.action}, 사유: '{e.decision.rationale}'"
                + (
                    " · 이후 비판 "
                    + ", ".join(f"#{c}" for c in e.reflected_in_critique_ids)
                    + "에 반영"
                    if e.reflected_in_critique_ids
                    else ""
                )
            ),
            kind="fact",
            evidence_keys=[keys[e.decision.id]] if e.decision.id in keys else [],
        )
        for e in entries
    ]
    if not out:
        out.append(AnswerStatement(text="기록된 연구자 결정이 없다.", kind="estimate"))
    return out
