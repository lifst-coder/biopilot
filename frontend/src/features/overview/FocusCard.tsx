import clsx from "clsx";
import { Link } from "react-router-dom";
import { useCritiques, useMetrics } from "@/api/queries";
import type { AcceptanceCriteria, ExperimentSummary, HypothesisOut, ProposalOut, TrendPoint } from "@/api/types";
import { Term } from "@/components";
import { formatWithUnit } from "@/lib/format";
import { josa } from "@/lib/korean";

/**
 * Which experiment needs attention now — from stored data only, in this order:
 * 1. the most recent experiment whose mean recovery is outside the criteria *and* still
 *    has unresolved work (pending proposals / open hypotheses),
 * 2. the most recent experiment outside the criteria,
 * 3. the most recent one with QC flags, 4. the most recent analysed experiment.
 */
export function pickFocus(
  points: TrendPoint[],
  criteria: AcceptanceCriteria | null,
  unresolved: ReadonlySet<number> = new Set(),
): TrendPoint | null {
  const latestFirst = points.filter((p) => p.recovery_mean_pct !== null).reverse();
  const outOfRange = criteria
    ? latestFirst.filter(
        (p) =>
          p.recovery_mean_pct !== null &&
          (p.recovery_mean_pct < criteria.recovery_min_pct || p.recovery_mean_pct > criteria.recovery_max_pct),
      )
    : [];
  return (
    outOfRange.find((p) => unresolved.has(p.experiment_id)) ??
    outOfRange[0] ??
    latestFirst.find((p) => p.flag_count > 0) ??
    latestFirst[0] ??
    null
  );
}

const VERDICT_WORD = {
  indeterminate: "현재 데이터로 확정 불가",
  supported: "지지됨",
  refuted: "반박됨",
  no_issue: "문제 없음",
} as const;

interface Props {
  focus: TrendPoint;
  experiments: ExperimentSummary[];
  criteria: AcceptanceCriteria | null;
  proposals: ProposalOut[];
  hypotheses: HypothesisOut[];
}

/**
 * "지금 봐야 할 것": the one experiment to look at, what is wrong with it (stored metrics
 * vs stored criteria and its baseline), the open question from the latest critique, and
 * where to go next.
 */
export function FocusCard({ focus, experiments, criteria, proposals, hypotheses }: Props) {
  const exp = experiments.find((e) => e.id === focus.experiment_id) ?? null;
  const baselineId = exp?.parent_experiment_id ?? null;
  const baselineCode = experiments.find((e) => e.id === baselineId)?.code ?? null;
  const { data: m } = useMetrics(focus.experiment_id);
  const { data: base } = useMetrics(baselineId);
  const { data: critiques = [] } = useCritiques(focus.experiment_id);
  const assessment = critiques[0]?.assessments[0] ?? null;

  const status = m?.qc_status ?? null;
  const needsReview = status === "fail" || status === "warning";
  const mean = focus.recovery_mean_pct;
  const low = criteria && mean !== null && mean < criteria.recovery_min_pct;
  const high = criteria && mean !== null && mean > criteria.recovery_max_pct;
  const failedAnalytes = (m?.qc_verdicts ?? []).filter((v) => v.status === "fail").map((v) => v.analyte);
  const pending = proposals.filter((p) => p.status === "pending" && p.experiment_id === focus.experiment_id);
  const open = hypotheses.filter(
    (h) => (h.status === "proposed" || h.status === "open") && h.experiment_id === focus.experiment_id,
  );
  const search = `?exp=${focus.experiment_id}`;
  const tone = status === "fail" ? "crit" : status === "warning" ? "warn" : "ok";

  return (
    <section
      aria-label="지금 봐야 할 것"
      className={clsx(
        "rounded-card border px-5 py-4",
        tone === "crit" ? "border-crit/40 bg-crit-soft/50" : tone === "warn" ? "border-warn/40 bg-warn-soft/50" : "border-ok/30 bg-ok-soft/40",
      )}
    >
      <p className="text-xs font-semibold text-ink-muted">
        지금 봐야 할 것 ·{" "}
        <span className={tone === "crit" ? "text-crit" : tone === "warn" ? "text-warn" : "text-ok"}>
          {needsReview ? "검토가 필요한 실험" : status === "pass" ? "최근 실험 합격" : "최근 실험"}
        </span>
      </p>
      <h2 className="mt-1 text-xl font-bold text-ink">
        <Link to={{ pathname: "/notebook", search }} className="hover:underline">
          {focus.code}
        </Link>{" "}
        <span className="font-semibold">{exp?.title}</span>
      </h2>

      <p className="mt-2 text-base">
        <Term k="recovery">평균 회수율</Term>{" "}
        <b className={clsx("tabular-nums", low || high ? "text-crit" : "text-ink")}>{formatWithUnit(mean, "%")}</b>
        <span className="text-ink-muted">
          {criteria && mean !== null && (
            <>
              {" "}
              — 기준({criteria.recovery_min_pct}–{criteria.recovery_max_pct}%) {low ? "미달" : high ? "초과" : "충족"}
            </>
          )}
          {baselineCode && base?.recovery_mean_pct != null && (
            <>
              , 기준 실험 {josa(baselineCode, "은/는")} {formatWithUnit(base.recovery_mean_pct, "%")}
            </>
          )}
        </span>
      </p>
      {failedAnalytes.length > 0 && (
        <p className="mt-0.5 text-sm text-crit">
          불합격 분석물: {failedAnalytes.join(", ")}
          {focus.flag_count > 0 && <span className="text-ink-muted"> · QC 플래그 {focus.flag_count}건</span>}
        </p>
      )}

      {assessment && (
        <div className="mt-3 rounded-md border border-border bg-surface/80 px-3 py-2 text-sm">
          <p className="text-xs text-ink-muted">해결되지 않은 질문</p>
          <p className="font-medium">{assessment.question}</p>
          <p className="mt-0.5 text-xs">
            <span className="font-semibold text-warn">{VERDICT_WORD[assessment.verdict]}</span>
            {assessment.missing_controls.length > 0 && (
              <span className="text-ink-muted">
                {" "}
                · 누락 대조군 {assessment.missing_controls.length}개: {assessment.missing_controls.map((c) => c.name).join(", ")}
              </span>
            )}
          </p>
        </div>
      )}

      <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
        <Link to={{ pathname: "/analysis", search }} className="bp-btn-primary px-3 py-1 text-xs">
          결과를 믿을 수 있나 → Analysis
        </Link>
        <Link to={{ pathname: "/research-ai", search, hash: "#critic" }} className="bp-btn-ghost px-3 py-1 text-xs">
          왜 그런가 → Critic
        </Link>
        {pending.length > 0 && (
          <Link to={{ pathname: "/research-ai", search, hash: "#proposals" }} className="bp-btn-ghost px-3 py-1 text-xs">
            결정 대기 제안 {pending.length}건
          </Link>
        )}
        {open.length > 0 && <span className="text-ink-muted">미해결 가설 {open.length}건</span>}
      </div>
    </section>
  );
}
