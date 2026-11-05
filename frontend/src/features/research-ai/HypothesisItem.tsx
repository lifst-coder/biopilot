import { useState } from "react";
import { useChangeHypothesisStatus } from "@/api/queries";
import type { HypothesisOut } from "@/api/types";
import { Badge, CodeText, ErrorState } from "@/components";

const NEXT: Record<HypothesisOut["status"], HypothesisOut["status"][]> = {
  proposed: ["open"],
  open: ["supported", "refuted"],
  supported: [],
  refuted: [],
};
const LABEL: Record<HypothesisOut["status"], string> = {
  proposed: "제안됨",
  open: "검증 중",
  supported: "지지됨",
  refuted: "반박됨",
};

/** One hypothesis with its audited status transitions (PAR-1). */
export function HypothesisItem({ hypothesis, resultIds }: { hypothesis: HypothesisOut; resultIds: number[] }) {
  const change = useChangeHypothesisStatus();
  const [rationale, setRationale] = useState("");
  const options = NEXT[hypothesis.status];
  return (
    <li className="rounded-md border border-border p-3 text-sm">
      <div className="mb-1 flex flex-wrap items-center gap-2">
        <Badge tone={hypothesis.origin === "user" ? "neutral" : "ai"}>{hypothesis.origin}</Badge>
        <Badge>{LABEL[hypothesis.status]}</Badge>
        <span className="text-ink-faint">H{hypothesis.id}</span>
      </div>
      <p className="bp-prose font-medium">
        <CodeText text={hypothesis.statement} />
      </p>
      {hypothesis.rationale && (
        <p className="bp-prose mt-0.5 text-ink-muted">
          <CodeText text={hypothesis.rationale} />
        </p>
      )}
      {hypothesis.transitions.map((t) => (
        <p key={t.id} className="mt-0.5 text-ink-faint">
          {LABEL[t.from_status]} → {LABEL[t.to_status]}: {t.rationale}
        </p>
      ))}
      {options.length > 0 && (
        <div className="mt-2 flex flex-wrap items-center gap-1">
          <input
            className="bp-input max-w-xs"
            placeholder="전이 사유 (필수)"
            value={rationale}
            onChange={(e) => setRationale(e.target.value)}
          />
          {options.map((s) => (
            <button
              key={s}
              type="button"
              className="bp-btn-ghost"
              disabled={!rationale.trim() || change.isPending || (s !== "open" && resultIds.length === 0)}
              onClick={() =>
                change.mutate({
                  hypothesisId: hypothesis.id,
                  body: {
                    status: s,
                    rationale,
                    evidence_result_ids: s === "open" ? [] : resultIds,
                    decided_by: "researcher",
                  },
                })
              }
            >
              {LABEL[s]}
            </button>
          ))}
          {change.isError && <ErrorState error={change.error} />}
        </div>
      )}
    </li>
  );
}
