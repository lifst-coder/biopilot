import clsx from "clsx";
import type { ReactNode } from "react";
import { Badge, Card, Term } from "@/components";
import type { BadgeTone } from "@/components";
import { EvidenceList } from "./EvidenceList";
import {
  BASIS_LABEL,
  STATUS_LABEL,
  VERDICT_LABEL,
  type CriticArgument,
  type CriticAssessment,
  type DecisionFeedback,
  type Evidence,
} from "./types";

const BASIS_TONE: Record<CriticArgument["basis"], BadgeTone> = { data: "brand", domain_rule: "ai", decision: "neutral" };

function Section({
  title,
  count,
  note,
  children,
}: {
  title: ReactNode;
  count: number;
  /** One-line explanation of what the section is for. */
  note?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="space-y-1.5">
      <h3 className="text-xs font-semibold text-ink-muted">
        {title} <span className="font-normal text-ink-faint">({count})</span>
      </h3>
      {note && <p className="text-[11px] text-ink-faint">{note}</p>}
      {count === 0 ? <p className="text-xs text-ink-faint">없음</p> : children}
    </section>
  );
}

function ArgumentItem({
  arg,
  evidence,
  maxChips,
}: {
  arg: CriticArgument;
  evidence: Map<string, Evidence>;
  maxChips?: number;
}) {
  return (
    <li className="rounded-md border border-border p-2 text-xs">
      <div className="flex items-start gap-2">
        <span className="shrink-0">
          <Badge tone={BASIS_TONE[arg.basis]}>{BASIS_LABEL[arg.basis]}</Badge>
        </span>
        <span>{arg.statement}</span>
      </div>
      <EvidenceList keys={arg.evidence_keys} evidence={evidence} max={maxChips} />
    </li>
  );
}

const VERDICT_FRAME: Record<CriticAssessment["verdict"], string> = {
  indeterminate: "border-warn/40 bg-warn-soft/60",
  supported: "border-ok/30 bg-ok-soft/50",
  refuted: "border-crit/40 bg-crit-soft/60",
  no_issue: "border-border bg-subtle",
};
const VERDICT_TEXT: Record<CriticAssessment["verdict"], string> = {
  indeterminate: "text-warn",
  supported: "text-ok",
  refuted: "text-crit",
  no_issue: "text-ink-muted",
};

/**
 * Research Critic output, ordered by practical value: the verdict, then **why the current
 * data cannot settle it** and **which controls are missing** (what to do next), the
 * researcher decisions it reflected, and only then the supporting / opposing evidence and
 * alternative explanations (collapsed). Every number shown is an EvidenceChip (stored
 * value); prose comes from the backend.
 */
export function CriticAssessmentView({
  assessment,
  evidence,
  feedback,
}: {
  assessment: CriticAssessment;
  evidence: Evidence[];
  feedback: DecisionFeedback[];
}) {
  const byKey = new Map(evidence.map((e) => [e.key, e]));
  const nEvidence =
    assessment.supporting_evidence.length +
    assessment.opposing_evidence.length +
    assessment.alternative_explanations.length;
  return (
    <Card title="Research Critic" subtitle={assessment.question}>
      <div className={clsx("mb-4 rounded-md border px-4 py-3", VERDICT_FRAME[assessment.verdict])}>
        <p className={clsx("text-lg font-bold", VERDICT_TEXT[assessment.verdict])}>
          <span>{VERDICT_LABEL[assessment.verdict]}</span>
        </p>
        <p className="mt-1 text-sm font-medium text-ink" data-testid="verdict-reason">
          판정: {assessment.verdict_reason}
        </p>
        <p className="mt-1.5 text-xs text-ink-muted">
          <span className="font-semibold">검토한 주장 · </span>
          {assessment.claim}
        </p>
      </div>
      <div className="grid gap-4 xl:grid-cols-2">
        <Section
          title="현재 데이터로 확정 불가한 이유"
          count={assessment.undetermined_reasons.length}
          note="지금 기록만으로는 원인을 가를 수 없는 이유"
        >
          <ul className="space-y-1.5">
            {assessment.undetermined_reasons.map((a) => (
              <ArgumentItem key={a.statement} arg={a} evidence={byKey} maxChips={3} />
            ))}
          </ul>
        </Section>
        <Section
          title={<Term k="missingControl">누락 대조군</Term>}
          count={assessment.missing_controls.length}
          note="이 비교를 하면 위 질문에 답할 수 있다 — 다음 실험의 출발점"
        >
          <ul className="space-y-1.5">
            {assessment.missing_controls.map((m) => (
              <li key={m.id} className="rounded-md border border-brand/30 bg-brand-soft/50 p-2.5 text-xs">
                <p className="text-sm font-semibold text-brand-strong">{m.name}</p>
                <p className="mt-0.5 text-ink-muted">{m.purpose}</p>
                {m.decision_note && <p className="mt-1 text-ink">결정 이력: {m.decision_note}</p>}
                <EvidenceList keys={m.evidence_keys} evidence={byKey} max={3} />
              </li>
            ))}
          </ul>
        </Section>
      </div>
      {feedback.length > 0 && (
        <div className="mt-4">
          <Section title="반영된 연구자 결정" count={feedback.length}>
            <ul className="space-y-1.5">
              {feedback.map((f) => (
                <li key={f.decision_id} className="flex items-start gap-2 rounded-md bg-subtle p-2 text-xs">
                  <span className="shrink-0">
                    <Badge tone="neutral">P{f.proposal_id}</Badge>
                  </span>
                  <span>{f.note}</span>
                </li>
              ))}
            </ul>
          </Section>
        </div>
      )}
      <details className="group mt-4 rounded-md border border-border">
        <summary className="cursor-pointer select-none px-3 py-2 text-xs font-medium text-ink-muted hover:bg-subtle/60">
          주장의 근거 보기 — 지지 {assessment.supporting_evidence.length} · 반대 {assessment.opposing_evidence.length} · 대안
          설명 {assessment.alternative_explanations.length}
          <span className="font-normal text-ink-faint"> (총 {nEvidence}건)</span>
        </summary>
        <div className="grid gap-4 border-t border-border p-3 xl:grid-cols-2">
          <Section title="지지 근거" count={assessment.supporting_evidence.length}>
            <ul className="space-y-1.5">
              {assessment.supporting_evidence.map((a) => (
                <ArgumentItem key={a.statement} arg={a} evidence={byKey} />
              ))}
            </ul>
          </Section>
          <Section title="반대 근거" count={assessment.opposing_evidence.length}>
            <ul className="space-y-1.5">
              {assessment.opposing_evidence.map((a) => (
                <ArgumentItem key={a.statement} arg={a} evidence={byKey} />
              ))}
            </ul>
          </Section>
          <div className="xl:col-span-2">
            <Section title="대안 설명" count={assessment.alternative_explanations.length}>
              <ul className="grid gap-1.5 xl:grid-cols-2">
                {assessment.alternative_explanations.map((alt) => (
                  <li key={alt.id} className="rounded-md border border-border p-2 text-xs">
                    <div className="flex items-center gap-2">
                      <span className="font-medium">{alt.label}</span>
                      <Badge tone={alt.status === "weakened" ? "neutral" : "ai"}>{STATUS_LABEL[alt.status]}</Badge>
                      <Badge tone="warn">추정</Badge>
                    </div>
                    <p className="mt-0.5 text-ink-muted">{alt.mechanism}</p>
                    {alt.supporting.map((a) => (
                      <p key={`s-${a.statement}`} className="mt-1">
                        <span className="text-ok">＋</span> {a.statement}
                      </p>
                    ))}
                    {alt.opposing.map((a) => (
                      <p key={`o-${a.statement}`} className="mt-1">
                        <span className="text-crit">－</span> {a.statement}
                      </p>
                    ))}
                  </li>
                ))}
              </ul>
            </Section>
          </div>
        </div>
      </details>
    </Card>
  );
}
