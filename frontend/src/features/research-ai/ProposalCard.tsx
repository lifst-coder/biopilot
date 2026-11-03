import { useState } from "react";
import { useDecideProposal } from "@/api/queries";
import type { DecisionCreate, ProposalOut } from "@/api/types";
import { Badge, EngineBadge } from "@/components";
import { formatConditionValue, formatDateTime } from "@/lib/format";

const STATUS_TONE = { pending: "warn", accepted: "ok", modified: "brand", rejected: "neutral" } as const;

/** One proposal with the accept / modify / reject decision form (rationale required). */
export function ProposalCard({ proposal }: { proposal: ProposalOut }) {
  const decide = useDecideProposal();
  const [action, setAction] = useState<DecisionCreate["action"]>("accept");
  const [rationale, setRationale] = useState("");
  const [modKey, setModKey] = useState(proposal.changes[0]?.key ?? "");
  const [modValue, setModValue] = useState("");

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
    <article className="flex flex-col gap-2 rounded-md border border-border p-3 text-xs">
      <header className="flex flex-wrap items-center gap-2">
        <Badge tone={STATUS_TONE[proposal.status]}>{proposal.status}</Badge>
        {proposal.origin !== "user" && <EngineBadge engine={proposal.origin === "ai:claude" ? "claude" : "rules"} />}
        <span className="text-ink-faint">P{proposal.id}</span>
      </header>
      <h3 className="text-sm font-medium">{proposal.title}</h3>
      <p className="text-ink-muted">{proposal.description}</p>
      {proposal.changes.length > 0 && (
        <ul className="rounded-md bg-subtle p-2 font-mono text-[11px]">
          {proposal.changes.map((c) => (
            <li key={c.key}>
              {c.key} → {formatConditionValue(c.value)}
            </li>
          ))}
        </ul>
      )}

      {proposal.decision ? (
        <div className="rounded-md bg-subtle p-2">
          <b>{proposal.decision.action}</b> · {proposal.decision.decided_by} ·{" "}
          {formatDateTime(proposal.decision.created_at)}
          <p className="mt-0.5 text-ink-muted">{proposal.decision.rationale}</p>
          {proposal.decision.modifications.map((m) => (
            <p key={m.key} className="font-mono text-[11px]">
              {m.key} → {formatConditionValue(m.value)}
            </p>
          ))}
        </div>
      ) : (
        <div className="space-y-2 border-t border-border pt-2">
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
                {{ accept: "수락", modify: "수정", reject: "거절" }[a]}
              </button>
            ))}
          </div>
          {action === "modify" && (
            <div className="flex gap-2">
              <input className="bp-input" placeholder="조건 키" value={modKey} onChange={(e) => setModKey(e.target.value)} />
              <input className="bp-input" placeholder="새 값" value={modValue} onChange={(e) => setModValue(e.target.value)} />
            </div>
          )}
          <textarea
            className="bp-input h-16 resize-none"
            placeholder="결정 근거 (필수)"
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
          {decide.isError && <p className="text-crit">{decide.error.message}</p>}
        </div>
      )}
    </article>
  );
}
