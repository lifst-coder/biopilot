import clsx from "clsx";
import { Link, useLocation } from "react-router-dom";
import { useCriteria, useDiff, useMetrics } from "@/api/queries";
import type { ExperimentSummary } from "@/api/types";
import { Badge, type BadgeTone } from "@/components";
import { formatConditionValue, formatWithUnit } from "@/lib/format";
import { josa } from "@/lib/korean";
import type { ExperimentOut } from "./types";

const QC: Record<string, { label: string; tone: BadgeTone }> = {
  pass: { label: "QC 합격", tone: "ok" },
  warning: { label: "QC 검토 필요", tone: "warn" },
  fail: { label: "QC 불합격", tone: "crit" },
  not_analyzed: { label: "미분석", tone: "neutral" },
};

/**
 * "무슨 실험이고 결과가 어땠나" in two lines: the stored result (QC status, mean recovery
 * vs criterion and baseline) and only the conditions that differ from the baseline
 * (parent) experiment. Everything else about the record stays below. Missing data
 * (not analysed, root experiment) simply hides the line.
 */
export function ExperimentHeadline({
  exp,
  experiments,
  onCompare,
}: {
  exp: ExperimentOut;
  experiments: ExperimentSummary[];
  onCompare: () => void;
}) {
  const { search } = useLocation();
  const baselineId = exp.parent_experiment_id ?? null;
  const baselineCode = experiments.find((e) => e.id === baselineId)?.code ?? null;
  const { data: m } = useMetrics(exp.id);
  const { data: base } = useMetrics(baselineId);
  const { data: criteria } = useCriteria(exp.project_id);
  const { data: diff } = useDiff(baselineId, exp.id);

  const mean = m?.analyzed ? (m.recovery_mean_pct ?? null) : null;
  const low = criteria && mean !== null && mean < criteria.recovery_min_pct;
  const high = criteria && mean !== null && mean > criteria.recovery_max_pct;
  const failed = (m?.qc_verdicts ?? []).filter((v) => v.status === "fail").map((v) => v.analyte);
  const qc = m ? QC[m.qc_status] : null;

  return (
    <div className="space-y-4">
      <div>
        <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-faint">결과</h3>
        {!m ? (
          <p className="text-sm text-ink-faint">분석 결과를 불러오는 중이거나 없습니다.</p>
        ) : !m.analyzed ? (
          <p className="text-sm text-ink-muted">아직 분석되지 않았습니다.</p>
        ) : (
          <>
            <p className="mt-0.5 flex flex-wrap items-baseline gap-x-2 text-base">
              {qc && <Badge tone={qc.tone}>{qc.label}</Badge>}
              <span>
                평균 회수율{" "}
                <b className={clsx("tabular-nums", low || high ? "text-crit" : "text-ink")}>{formatWithUnit(mean, "%")}</b>
              </span>
              <span className="text-sm text-ink-muted">
                {criteria && mean !== null && (
                  <>
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
            {failed.length > 0 && <p className="text-sm text-crit">불합격 분석물: {failed.join(", ")}</p>}
            <p className="mt-0.5 text-sm">
              <Link to={{ pathname: "/analysis", search }} className="text-brand hover:underline">
                판정 근거 보기 → Analysis
              </Link>
            </p>
          </>
        )}
      </div>

      <div>
        <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-faint">
          {baselineCode ? `기준 실험 ${josa(baselineCode, "과/와")} 다른 조건` : "조건"}
        </h3>
        {!baselineId ? (
          <p className="text-sm text-ink-muted">루트 실험 — 다른 실험의 기준입니다. 전체 조건은 아래 원본에 있습니다.</p>
        ) : !diff ? (
          <p className="text-sm text-ink-faint">조건 차이를 불러오는 중…</p>
        ) : diff.condition_changes.length === 0 ? (
          <p className="text-sm text-ink-muted">기준 실험과 조건이 같습니다 (동일 조건 {diff.unchanged_keys.length}개).</p>
        ) : (
          <>
            <ul className="mt-1 flex flex-wrap gap-2" aria-label="기준 실험과 다른 조건">
              {diff.condition_changes.map((c) => (
                <li key={c.key} className="rounded-md border border-warn/40 bg-warn-soft/60 px-2.5 py-1 text-sm">
                  <span className="text-ink-muted">{c.label}</span>{" "}
                  <span className="font-mono text-ink-faint line-through">{formatConditionValue(c.value_a)}</span>{" "}
                  → <span className="font-mono font-semibold text-warn">{formatConditionValue(c.value_b)}</span>
                </li>
              ))}
            </ul>
            <p className="mt-1.5 text-sm text-ink-faint">
              나머지 {diff.unchanged_keys.length}개 조건은 동일 ·{" "}
              <button type="button" className="text-brand hover:underline" onClick={onCompare}>
                결과까지 나란히 비교
              </button>
            </p>
          </>
        )}
      </div>
    </div>
  );
}
