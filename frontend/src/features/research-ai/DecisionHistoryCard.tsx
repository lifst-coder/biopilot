import { Badge, Card, CodeText, EmptyState, ExperimentLink } from "@/components";
import { formatDateTime } from "@/lib/format";
import type { DecisionHistoryEntry } from "./types";

const TONE = { accept: "ok", modify: "brand", reject: "neutral" } as const;
const LABEL = { accept: "채택", modify: "수정", reject: "기각" } as const;

/** Decision History: every decision with its rationale and the critiques that reflected it. */
export function DecisionHistoryCard({ entries }: { entries: DecisionHistoryEntry[] }) {
  return (
    <Card title="결정 이력" subtitle="기각·수정 사유는 이후 비판과 제안에 반영됩니다">
      {entries.length === 0 ? (
        <EmptyState>기록된 결정이 없습니다 — 아래 제안 카드에서 채택·수정·기각을 사유와 함께 남기면 여기에 쌓입니다.</EmptyState>
      ) : (
        <ul className="space-y-2">
          {entries.map((e) => (
            <li key={e.decision.id} className="rounded-md border border-border p-3 text-sm">
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone={TONE[e.decision.action]}>{LABEL[e.decision.action]}</Badge>
                <span className="text-ink-faint">
                  P{e.proposal_id} ·{" "}
                  <ExperimentLink id={e.experiment_id} tab="/research-ai">
                    {e.experiment_code}
                  </ExperimentLink>{" "}
                  · {formatDateTime(e.decision.created_at)}
                </span>
                <Badge>{e.decision.reason_category}</Badge>
              </div>
              <p className="mt-1 font-medium">
                <CodeText text={e.proposal_title} />
              </p>
              <p className="bp-prose text-ink-muted">
                사유: <CodeText text={e.decision.rationale} />
              </p>
              <p className="text-ink-faint">
                {e.reflected_in_critique_ids.length > 0
                  ? `반영된 비판: ${e.reflected_in_critique_ids.map((id) => `#${id}`).join(", ")}`
                  : "아직 이후 비판에 반영되지 않음"}
              </p>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
