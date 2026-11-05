import type { DecisionLink } from "@/api/types";
import { formatWithUnit } from "@/lib/format";
import { Badge } from "./Badge";
import { CodeText } from "./CodeText";
import { ExperimentChip } from "./ExperimentChip";

const ACTION: Record<DecisionLink["action"], { glyph: string; label: string; tone: "ok" | "warn" | "crit" }> = {
  accept: { glyph: "✓", label: "채택", tone: "ok" },
  modify: { glyph: "~", label: "수정 채택", tone: "warn" },
  reject: { glyph: "✕", label: "기각", tone: "crit" },
};

/**
 * One recorded researcher decision: action (glyph + word), the proposal, the stored
 * rationale, and the follow-up experiment that implemented it (stored values only).
 */
export function DecisionLine({
  decision,
  projectId,
  projectLabel,
}: {
  decision: DecisionLink;
  projectId: number;
  projectLabel?: string | null;
}) {
  const a = ACTION[decision.action];
  return (
    <li className="space-y-1">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={a.tone}>
          <span aria-hidden>{a.glyph}&nbsp;</span>
          {a.label}
        </Badge>
        <span className="text-sm font-medium">
          <CodeText text={decision.proposal_title} projectId={projectId} />
        </span>
      </div>
      <p className="bp-prose text-ink-muted">
        <CodeText text={decision.rationale} projectId={projectId} />
      </p>
      {decision.follow_up && (
        <p className="flex flex-wrap items-center gap-1 text-sm">
          <span className="text-ink-muted">→ 후속 실험</span>
          <ExperimentChip
            id={decision.follow_up.experiment_id}
            code={decision.follow_up.code}
            projectId={projectId}
            projectLabel={projectLabel}
            qc={decision.follow_up.qc_status}
            value={decision.follow_up.recovery_mean_pct != null ? formatWithUnit(decision.follow_up.recovery_mean_pct, "%") : null}
          />
          <span className="min-w-0 text-ink-muted">
            <CodeText text={decision.follow_up.title} projectId={projectId} />
          </span>
        </p>
      )}
    </li>
  );
}
