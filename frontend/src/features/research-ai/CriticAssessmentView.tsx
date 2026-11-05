import clsx from "clsx";
import type { ReactNode } from "react";
import type { ProposalOut } from "@/api/types";
import { Badge, Card, CodeText, Term } from "@/components";
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
    <section className="space-y-2">
      <div>
        <h3 className="text-sm font-semibold text-ink">
          {title} <span className="font-normal text-ink-faint">({count})</span>
        </h3>
        {note && <p className="mt-0.5 text-sm text-ink-faint">{note}</p>}
      </div>
      {count === 0 ? <p className="text-sm text-ink-faint">없음</p> : children}
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
    <li className="rounded-md border border-border p-3">
      <p className="bp-prose">
        <span className="mr-1.5 inline-block align-[0.1em]">
          <Badge tone={BASIS_TONE[arg.basis]}>{BASIS_LABEL[arg.basis]}</Badge>
        </span>
        <CodeText text={arg.statement} />
      </p>
      <EvidenceList keys={arg.evidence_keys} evidence={evidence} max={maxChips} />
    </li>
  );
}

const PROPOSAL_STATUS: Record<ProposalOut["status"], string> = {
  pending: "결정 대기",
  accepted: "채택",
  modified: "수정 채택",
  rejected: "기각",
};

/**
 * "이 대조군을 포함한 제안 →": the proposals whose design addresses this missing control
 * (`design.addresses_controls`), each a jump to its card in the Next Experiment Designer.
 */
function ControlProposals({ controlId, proposals }: { controlId: string; proposals: ProposalOut[] }) {
  const matching = proposals.filter((p) => p.design?.addresses_controls.includes(controlId));
  if (matching.length === 0) {
    return <p className="mt-1.5 text-sm text-ink-faint">이 대조군을 포함한 제안은 아직 없습니다.</p>;
  }
  return (
    <p className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
      <span className="text-ink-muted">이 대조군을 포함한 제안</span>
      {matching.map((p) => (
        <a
          key={p.id}
          href={`#proposal-${p.id}`}
          onClick={(e) => {
            const card = document.getElementById(`proposal-${p.id}`);
            if (!card) return;
            e.preventDefault();
            card.scrollIntoView({ block: "start", behavior: "smooth" });
            card.focus({ preventScroll: true });
          }}
          className="font-medium text-brand underline decoration-brand/30 underline-offset-2 hover:decoration-brand"
        >
          P{p.id} · {PROPOSAL_STATUS[p.status]} →
        </a>
      ))}
    </p>
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
 * "결론 — 세부" → the conclusion and its detail on separate lines (display only: the text is
 * the backend's verdict_reason, split once at the first em dash if it has one).
 */
export function splitReason(reason: string): [string, string | null] {
  const at = reason.indexOf(" — ");
  if (at <= 0) return [reason, null];
  return [reason.slice(0, at), reason.slice(at + 3)];
}

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
  proposals = [],
}: {
  assessment: CriticAssessment;
  evidence: Evidence[];
  feedback: DecisionFeedback[];
  /** This experiment's proposals — each missing control links to the ones that include it. */
  proposals?: ProposalOut[];
}) {
  const byKey = new Map(evidence.map((e) => [e.key, e]));
  const [reasonHead, reasonDetail] = splitReason(assessment.verdict_reason);
  const nEvidence =
    assessment.supporting_evidence.length +
    assessment.opposing_evidence.length +
    assessment.alternative_explanations.length;
  return (
    <Card title="Research Critic" subtitle={<CodeText text={assessment.question} />}>
      <div className={clsx("mb-5 rounded-md border px-4 py-3.5", VERDICT_FRAME[assessment.verdict])}>
        <p className={clsx("text-lg font-bold", VERDICT_TEXT[assessment.verdict])}>
          <span>{VERDICT_LABEL[assessment.verdict]}</span>
        </p>
        <div className="bp-prose mt-1.5 text-ink" data-testid="verdict-reason">
          <p className="font-semibold">
            판정: <CodeText text={reasonHead} />
          </p>
          {reasonDetail && (
            <p className="mt-0.5">
              <CodeText text={reasonDetail} />
            </p>
          )}
        </div>
        <p className="bp-prose mt-2.5 border-t border-ink/10 pt-2 text-ink-muted">
          <span className="font-semibold">검토한 주장 · </span>
          <CodeText text={assessment.claim} />
        </p>
      </div>
      <div className="grid gap-x-5 gap-y-6 xl:grid-cols-2">
        <Section
          title="현재 데이터로 확정 불가한 이유"
          count={assessment.undetermined_reasons.length}
          note="지금 기록만으로는 원인을 가를 수 없는 이유"
        >
          <ul className="space-y-2">
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
          <ul className="space-y-2">
            {assessment.missing_controls.map((m) => (
              <li key={m.id} className="rounded-md border border-brand/30 bg-brand-soft/50 p-3">
                <p className="text-sm font-semibold text-brand-strong">{m.name}</p>
                <p className="bp-prose mt-0.5 text-ink-muted">
                  <CodeText text={m.purpose} />
                </p>
                {m.decision_note && (
                  <p className="bp-prose mt-1 text-ink">
                    결정 이력: <CodeText text={m.decision_note} />
                  </p>
                )}
                <EvidenceList keys={m.evidence_keys} evidence={byKey} max={3} />
                <ControlProposals controlId={m.id} proposals={proposals} />
              </li>
            ))}
          </ul>
        </Section>
      </div>
      {feedback.length > 0 && (
        <div className="mt-6">
          <Section title="반영된 연구자 결정" count={feedback.length}>
            <ul className="space-y-2">
              {feedback.map((f) => (
                <li key={f.decision_id} className="rounded-md bg-subtle p-3">
                  <p className="bp-prose">
                    <span className="mr-1.5 inline-block align-[0.1em]">
                      <Badge tone="neutral">P{f.proposal_id}</Badge>
                    </span>
                    <CodeText text={f.note} />
                  </p>
                </li>
              ))}
            </ul>
          </Section>
        </div>
      )}
      <details className="group mt-6 rounded-md border border-border">
        <summary className="select-none px-3 py-2.5 text-sm font-medium text-ink-muted">
          주장의 근거 보기 — 지지 {assessment.supporting_evidence.length} · 반대 {assessment.opposing_evidence.length} · 대안
          설명 {assessment.alternative_explanations.length}
          <span className="font-normal text-ink-faint"> (총 {nEvidence}건)</span>
        </summary>
        <div className="grid gap-x-5 gap-y-6 border-t border-border p-3 xl:grid-cols-2">
          <Section title="지지 근거" count={assessment.supporting_evidence.length}>
            <ul className="space-y-2">
              {assessment.supporting_evidence.map((a) => (
                <ArgumentItem key={a.statement} arg={a} evidence={byKey} />
              ))}
            </ul>
          </Section>
          <Section title="반대 근거" count={assessment.opposing_evidence.length}>
            <ul className="space-y-2">
              {assessment.opposing_evidence.map((a) => (
                <ArgumentItem key={a.statement} arg={a} evidence={byKey} />
              ))}
            </ul>
          </Section>
          <div className="xl:col-span-2">
            <Section title="대안 설명" count={assessment.alternative_explanations.length}>
              <ul className="grid gap-2 xl:grid-cols-2">
                {assessment.alternative_explanations.map((alt) => (
                  <li key={alt.id} className="rounded-md border border-border p-3 text-sm leading-relaxed">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-medium">{alt.label}</span>
                      <Badge tone={alt.status === "weakened" ? "neutral" : "ai"}>{STATUS_LABEL[alt.status]}</Badge>
                      <Badge tone="warn">추정</Badge>
                    </div>
                    <p className="mt-0.5 text-ink-muted">
                      <CodeText text={alt.mechanism} />
                    </p>
                    {alt.supporting.map((a) => (
                      <p key={`s-${a.statement}`} className="mt-1">
                        <span className="font-semibold text-ok">＋ 지지</span> <CodeText text={a.statement} />
                      </p>
                    ))}
                    {alt.opposing.map((a) => (
                      <p key={`o-${a.statement}`} className="mt-1">
                        <span className="font-semibold text-crit">－ 반대</span> <CodeText text={a.statement} />
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
