import type { ReactNode } from "react";
import { Badge, Card } from "@/components";
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

const VERDICT_TONE: Record<CriticAssessment["verdict"], BadgeTone> = {
  indeterminate: "warn",
  supported: "ok",
  refuted: "crit",
  no_issue: "neutral",
};
const BASIS_TONE: Record<CriticArgument["basis"], BadgeTone> = { data: "brand", domain_rule: "ai", decision: "neutral" };

function Section({ title, count, children }: { title: string; count: number; children: ReactNode }) {
  return (
    <section className="space-y-1.5">
      <h3 className="text-xs font-semibold text-ink-muted">
        {title} <span className="font-normal text-ink-faint">({count})</span>
      </h3>
      {count === 0 ? <p className="text-xs text-ink-faint">없음</p> : children}
    </section>
  );
}

function ArgumentItem({ arg, evidence }: { arg: CriticArgument; evidence: Map<string, Evidence> }) {
  return (
    <li className="rounded-md border border-border p-2 text-xs">
      <div className="flex items-start gap-2">
        <span className="shrink-0">
          <Badge tone={BASIS_TONE[arg.basis]}>{BASIS_LABEL[arg.basis]}</Badge>
        </span>
        <span>{arg.statement}</span>
      </div>
      <EvidenceList keys={arg.evidence_keys} evidence={evidence} />
    </li>
  );
}

/**
 * Research Critic output: 지지 근거 / 반대 근거 / 누락 대조군 / 대안 설명 / 확정 불가 이유.
 * Every number shown is an EvidenceChip (stored value); prose comes from the backend.
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
  return (
    <Card
      title="Research Critic"
      subtitle={assessment.question}
      actions={<Badge tone={VERDICT_TONE[assessment.verdict]}>{VERDICT_LABEL[assessment.verdict]}</Badge>}
    >
      <div className="mb-4 rounded-md bg-subtle p-3 text-xs">
        <p>
          <span className="font-semibold">검토한 주장 · </span>
          {assessment.claim}
        </p>
        <p className="mt-1 font-medium" data-testid="verdict-reason">
          판정: {assessment.verdict_reason}
        </p>
      </div>
      <div className="grid gap-4 xl:grid-cols-2">
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
        <Section title="누락 대조군" count={assessment.missing_controls.length}>
          <ul className="space-y-1.5">
            {assessment.missing_controls.map((m) => (
              <li key={m.id} className="rounded-md border border-warn/30 bg-warn-soft/40 p-2 text-xs">
                <p className="font-medium">{m.name}</p>
                <p className="text-ink-muted">{m.purpose}</p>
                {m.decision_note && <p className="mt-1 text-ink">결정 이력: {m.decision_note}</p>}
                <EvidenceList keys={m.evidence_keys} evidence={byKey} />
              </li>
            ))}
          </ul>
        </Section>
        <Section title="대안 설명" count={assessment.alternative_explanations.length}>
          <ul className="space-y-1.5">
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
      <div className="mt-4">
        <Section title="현재 데이터로 확정 불가한 이유" count={assessment.undetermined_reasons.length}>
          <ul className="space-y-1.5">
            {assessment.undetermined_reasons.map((a) => (
              <ArgumentItem key={a.statement} arg={a} evidence={byKey} />
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
    </Card>
  );
}
