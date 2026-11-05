import clsx from "clsx";
import { useState } from "react";
import { isDemo } from "@/api/demo";
import { useDecideProposal, useProposalExperimentDraft } from "@/api/queries";
import type { DecisionCreate, ProposalOut } from "@/api/types";
import { Badge, CodeText, EngineBadge, ErrorState, ExperimentLink } from "@/components";
import { formatConditionValue, formatDate, formatDateTime } from "@/lib/format";
import { DesignDetails } from "./DesignDetails";

const STATUS_TONE = { pending: "warn", accepted: "ok", modified: "brand", rejected: "neutral" } as const;
const STATUS_LABEL = { pending: "결정 대기", accepted: "채택", modified: "수정 채택", rejected: "기각" } as const;
const ACTION_LABEL = { accept: "채택", modify: "수정", reject: "기각" } as const;

function DraftPreview({ proposalId }: { proposalId: number }) {
  const { data, isPending, isError, error } = useProposalExperimentDraft(proposalId);
  if (isPending) return <p className="text-ink-faint">초안 생성 중…</p>;
  if (isError) return <ErrorState error={error} />;
  return (
    <div className="space-y-1 rounded-md border border-border p-3 text-sm">
      <p>
        <b>{data.draft.code}</b> · 기준{" "}
        <ExperimentLink id={data.base_experiment_id}>{data.base_experiment_code}</ExperimentLink>{" "}
        {!data.ready && <Badge tone="warn">미리보기</Badge>}
      </p>
      {data.notes.map((n) => (
        <p key={n} className="text-ink-muted">
          {n}
        </p>
      ))}
      <pre className="whitespace-pre-wrap font-mono">{data.draft.raw_note}</pre>
    </div>
  );
}

/** One proposal: design, priority factors, and the accept / modify / reject form (rationale required). */
export function ProposalCard({ proposal, codeOf }: { proposal: ProposalOut; codeOf: (id: number) => string }) {
  const decide = useDecideProposal();
  const [action, setAction] = useState<DecisionCreate["action"]>("accept");
  const [rationale, setRationale] = useState("");
  const [modKey, setModKey] = useState(proposal.changes[0]?.key ?? "");
  const [modValue, setModValue] = useState("");
  const [showDraft, setShowDraft] = useState(false);

  const submit = () => {
    const body: DecisionCreate = {
      action,
      rationale,
      modifications: action === "modify" ? [{ key: modKey, value: modValue }] : [],
      decided_by: "researcher",
    };
    decide.mutate({ proposalId: proposal.id, body });
  };

  return (
    <article
      id={`proposal-${proposal.id}`}
      tabIndex={-1}
      className={clsx(
        "scroll-mt-4 outline-none focus-visible:ring-2 focus-visible:ring-brand/50",
        "flex min-w-0 flex-col gap-3 rounded-md border p-4 text-sm",
        proposal.status === "pending" ? "border-border bg-surface" : "border-border bg-subtle/60",
      )}
    >
      <header className="flex flex-wrap items-center gap-2">
        <Badge tone={STATUS_TONE[proposal.status]}>{STATUS_LABEL[proposal.status]}</Badge>
        {proposal.origin !== "user" && <EngineBadge engine={proposal.origin === "ai:claude" ? "claude" : "rules"} />}
        <span className="text-ink-faint">P{proposal.id}</span>
        <span className="ml-auto" title={proposal.priority_factors.map((f) => `${f.name} +${f.points}: ${f.detail}`).join("\n")}>
          <Badge tone="brand">우선순위 {proposal.priority}</Badge>
        </span>
      </header>
      <div>
        <h3 className="text-base font-semibold leading-snug">
          <CodeText text={proposal.title} />
        </h3>
        <p className="bp-prose mt-1 text-ink-muted">
          <CodeText text={proposal.description} />
        </p>
      </div>
      {proposal.supersedes_proposal_ids.length > 0 && (
        <p className="text-ai">기각 사유 반영: {proposal.supersedes_proposal_ids.map((id) => `P${id}`).join(", ")} 대체</p>
      )}
      {(proposal.design || proposal.changes.length > 0 || proposal.priority_factors.length > 0) && (
        <details className="rounded-md border border-border">
          <summary className="select-none px-3 py-2 font-medium text-ink-muted">
            설계 자세히 — 변수 · 대조군 · 반복 수 · 판별력 · 우선순위 근거
          </summary>
          <div className="space-y-3 border-t border-border p-3">
            {proposal.design && <DesignDetails design={proposal.design} codeOf={codeOf} />}
            {proposal.changes.length > 0 && (
              <ul className="rounded-md bg-subtle p-2 font-mono text-xs">
                {proposal.changes.map((c) => (
                  <li key={c.key}>
                    {c.key} → {formatConditionValue(c.value)}
                  </li>
                ))}
              </ul>
            )}
            {proposal.priority_factors.length > 0 && (
              <ul className="flex flex-wrap gap-1">
                {proposal.priority_factors.map((f) => (
                  <li key={f.name}>
                    <Badge>
                      {f.name} +{f.points}
                    </Badge>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </details>
      )}
      {proposal.status !== "rejected" && (
        <button type="button" className="bp-btn-ghost self-start" onClick={() => setShowDraft((v) => !v)}>
          {showDraft ? "실험 초안 닫기" : "실험 초안 보기"}
        </button>
      )}
      {showDraft && <DraftPreview proposalId={proposal.id} />}

      {proposal.decision ? (
        <div className="rounded-md bg-subtle p-3">
          <b>{ACTION_LABEL[proposal.decision.action]}</b> · {proposal.decision.decided_by} ·{" "}
          {proposal.decision.decided_on
            ? `${formatDate(proposal.decision.decided_on)} 결정`
            : formatDateTime(proposal.decision.created_at)}
          <p className="bp-prose mt-1 text-ink-muted">
            사유: <CodeText text={proposal.decision.rationale} />
          </p>
          {proposal.decision.constraints.length > 0 && (
            <p className="text-ink-faint">인식된 제약: {proposal.decision.constraints.join(", ")}</p>
          )}
          {proposal.decision.modifications.map((m) => (
            <p key={m.key} className="font-mono text-xs">
              {m.key} → {formatConditionValue(m.value)}
            </p>
          ))}
        </div>
      ) : (
        <div className="space-y-2 border-t border-border pt-3">
          <div className="flex gap-1" role="radiogroup" aria-label="결정">
            {(["accept", "modify", "reject"] as const).map((a) => (
              <button
                key={a}
                type="button"
                role="radio"
                aria-checked={action === a}
                onClick={() => setAction(a)}
                className={action === a ? "bp-btn-primary" : "bp-btn-ghost"}
              >
                {ACTION_LABEL[a]}
              </button>
            ))}
          </div>
          {action === "modify" && (
            <div className="flex flex-wrap gap-2 sm:flex-nowrap">
              <input className="bp-input" placeholder="조건 키" value={modKey} onChange={(e) => setModKey(e.target.value)} />
              <input className="bp-input" placeholder="새 값" value={modValue} onChange={(e) => setModValue(e.target.value)} />
            </div>
          )}
          <textarea
            className="bp-input h-20 resize-y"
            placeholder="결정 사유 (필수) — 이후 비판·제안이 이 사유를 참조합니다"
            value={rationale}
            onChange={(e) => setRationale(e.target.value)}
          />
          <button
            type="button"
            className="bp-btn-primary"
            disabled={!rationale.trim() || (action === "modify" && (!modKey || !modValue)) || decide.isPending}
            onClick={submit}
          >
            결정 기록
          </button>
          {isDemo && (
            <p className="text-xs text-ink-muted">
              데모는 읽기 전용이라 결정이 저장되지 않습니다. 이미 기록된 결정과 그 사유가 다음 제안에 어떻게 반영됐는지는
              다른 제안 카드의 ‘기각 사유 반영’과 Critic의 ‘반영된 연구자 결정’에서 볼 수 있습니다.
            </p>
          )}
          {decide.isError && <ErrorState error={decide.error} />}
        </div>
      )}
    </article>
  );
}
