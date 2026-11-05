import clsx from "clsx";
import { Link, useLocation } from "react-router-dom";
import type { ExperimentMetrics } from "@/api/types";
import { CodeText, StatTile, Term } from "@/components";
import { formatNumber, formatWithUnit } from "@/lib/format";
import { GLOSSARY, type GlossaryKey } from "@/lib/glossary";
import { josa } from "@/lib/korean";
import { FLAG_LABELS, QC_STATUS } from "./labels";
import type { AcceptanceCriteria, QCFlag, QCStatus } from "./types";

type CheckCode = QCFlag["code"];

/** Status → what it means for the reader (presentation of the deterministic status only). */
const STATUS_MEANING: Record<QCStatus, string> = {
  fail: "허용 기준을 벗어난 분석물이 있어, 이 결과를 그대로 보고에 쓸 수 없습니다.",
  warning: "허용 기준은 충족했지만 확인이 필요한 항목이 있습니다.",
  pass: "모든 분석물이 허용 기준을 충족했습니다.",
  not_analyzed: "저장된 분석 결과가 없습니다.",
};

const STATUS_FRAME: Record<QCStatus, string> = {
  fail: "border-crit/40 bg-crit-soft/70",
  warning: "border-warn/40 bg-warn-soft/70",
  pass: "border-ok/30 bg-ok-soft/50",
  not_analyzed: "border-border bg-surface",
};

const STATUS_TEXT: Record<QCStatus, string> = {
  fail: "text-crit",
  warning: "text-warn",
  pass: "text-ok",
  not_analyzed: "text-ink-muted",
};

const STATUS_ICON: Record<QCStatus, string> = { fail: "✕", warning: "!", pass: "✓", not_analyzed: "–" };

/** Glossary entry explaining each QC check. */
const CHECK_TERM: Partial<Record<CheckCode, GlossaryKey>> = {
  recovery_out_of_range: "recovery",
  recovery_rsd_high: "rsd",
  calibration_r2_low: "r2",
  calibration_back_calc_error: "calibration",
  is_suppression: "isSuppression",
  is_enhancement: "is",
  matrix_effect_significant: "matrixEffect",
  outlier_suspected: "grubbs",
  uncertainty_high: "uncertainty",
  ion_ratio_out_of_range: "ionRatio",
  loq_above_lowest_level: "loq",
};

/** The acceptance criterion each check is judged against, as stored in the criteria version. */
export function criterionText(code: CheckCode, c: AcceptanceCriteria | undefined): string | null {
  if (!c) return null;
  switch (code) {
    case "recovery_out_of_range":
      return `기준 ${c.recovery_min_pct}–${c.recovery_max_pct}%`;
    case "recovery_rsd_high":
      return `기준 ≤${c.rsd_max_pct}%`;
    case "calibration_r2_low":
      return `기준 ≥${c.r_squared_min}`;
    case "calibration_back_calc_error":
      return `기준 ±${c.back_calc_tolerance_pct}%`;
    case "is_suppression":
    case "is_enhancement":
      return `기준 ${c.is_response_min_pct}–${c.is_response_max_pct}%`;
    case "matrix_effect_significant":
      return `기준 ±${c.matrix_effect_abs_max_pct}%`;
    case "outlier_suspected":
      return `α=${c.grubbs_alpha}`;
    case "uncertainty_high":
      return `기준 U ≤${c.expanded_uncertainty_max_pct}%`;
    case "ion_ratio_out_of_range":
      return `기준 ±${c.ion_ratio_tolerance_pct}%`;
    default:
      return null;
  }
}

/** "회수율 범위 이탈 4 · IS 억제 3" — counts of stored flags by label; empty → null. */
export function flagSummary(flags: QCFlag[]): string | null {
  if (flags.length === 0) return null;
  const counts = new Map<CheckCode, number>();
  for (const f of flags) counts.set(f.code, (counts.get(f.code) ?? 0) + 1);
  return [...counts.entries()].map(([code, n]) => `${FLAG_LABELS[code]} ${n}`).join(" · ");
}

/** Marker tone of an evidence section from its stored flags. */
export function flagTone(flags: QCFlag[]): "crit" | "warn" | "ok" | "default" {
  if (flags.some((f) => f.severity === "critical")) return "crit";
  if (flags.some((f) => f.severity === "warning")) return "warn";
  if (flags.length === 0) return "ok";
  return "default";
}

interface CheckGroup {
  code: CheckCode;
  analytes: string[];
}

function groupChecks(m: ExperimentMetrics, kind: "failed_checks" | "warning_checks"): CheckGroup[] {
  const groups = new Map<CheckCode, string[]>();
  for (const v of m.qc_verdicts) for (const c of v[kind]) groups.set(c, [...(groups.get(c) ?? []), v.analyte]);
  return [...groups.entries()].map(([code, analytes]) => ({ code, analytes }));
}

function CheckLine({
  group,
  m,
  criteria,
  strong,
}: {
  group: CheckGroup;
  m: ExperimentMetrics;
  criteria?: AcceptanceCriteria;
  strong: boolean;
}) {
  const term = CHECK_TERM[group.code];
  const recovery = new Map(m.per_analyte_recovery.map((r) => [r.analyte, r.mean_pct]));
  const showRecovery = group.code === "recovery_out_of_range";
  const crit = criterionText(group.code, criteria);
  return (
    <li className={clsx("flex flex-wrap items-baseline gap-x-2 text-sm", strong ? "text-ink" : "text-ink-muted")}>
      <span className={clsx("font-semibold", strong ? "text-crit" : "text-warn")}>
        <span aria-hidden className="mr-1 inline-block w-3 text-center">
          {strong ? "✕" : "!"}
        </span>
        {term ? <Term k={term}>{FLAG_LABELS[group.code]}</Term> : FLAG_LABELS[group.code]}
      </span>
      <span>
        {group.analytes
          .map((a) => (showRecovery && recovery.has(a) ? `${a} ${formatWithUnit(recovery.get(a), "%")}` : a))
          .join(", ")}
      </span>
      {crit && <span className="text-sm text-ink-faint">({crit})</span>}
    </li>
  );
}

interface Props {
  metrics: ExperimentMetrics;
  criteria?: AcceptanceCriteria;
  /** Stored metrics of the baseline (parent) experiment, for "기준 실험 #018은 89.1%". */
  baseline?: { code: string; metrics: ExperimentMetrics | undefined } | null;
}

/**
 * The answer of the Analysis tab — "이 실험의 결과를 신뢰할 수 있는가" — as one verdict
 * line, the failed checks behind it, and three key numbers each with its meaning.
 * Every value is a stored backend value; this component only compares it with the
 * stored criterion to choose words and colors.
 */
export function VerdictSummary({ metrics: m, criteria, baseline }: Props) {
  const { search } = useLocation();
  const status = m.qc_status;
  const failed = groupChecks(m, "failed_checks");
  const warned = groupChecks(m, "warning_checks");
  const nFail = m.qc_verdicts.filter((v) => v.status === "fail").length;
  const nWarn = m.qc_verdicts.filter((v) => v.status === "warning").length;
  const total = m.qc_verdicts.length;
  const counts = [
    total ? `분석물 ${total}개 중` : null,
    nFail ? `${nFail}개 불합격` : null,
    nWarn ? `${nWarn}개 검토 필요` : null,
    total && !nFail && !nWarn ? "모두 합격" : null,
  ]
    .filter(Boolean)
    .join(" ");

  const mean = m.recovery_mean_pct ?? null;
  const meanTone =
    mean === null || !criteria
      ? "default"
      : mean < criteria.recovery_min_pct || mean > criteria.recovery_max_pct
        ? "crit"
        : "ok";
  const baseMean = baseline?.metrics?.recovery_mean_pct ?? null;
  const meanMeaning = [
    criteria && mean !== null
      ? `기준(${criteria.recovery_min_pct}–${criteria.recovery_max_pct}%) ${
          mean < criteria.recovery_min_pct ? "미달" : mean > criteria.recovery_max_pct ? "초과" : "충족"
        }`
      : null,
    baseline && baseMean !== null ? `기준 실험 ${josa(baseline.code, "은/는")} ${formatWithUnit(baseMean, "%")}` : null,
  ]
    .filter(Boolean)
    .join(" · ");

  const rsdFlags = m.flags.filter((f) => f.code === "recovery_rsd_high");
  const rsdMeaning = criteria
    ? rsdFlags.length
      ? `${rsdFlags.length}개 그룹이 기준(≤${criteria.rsd_max_pct}%) 초과`
      : `분석물·첨가 수준별 RSD는 모두 기준(≤${criteria.rsd_max_pct}%) 이내 · 전체 값은 분석물 간 차이 포함`
    : undefined;

  const isFlags = m.flags.filter((f) => f.code === "is_suppression" || f.code === "is_enhancement");
  const injections = isFlags.map((f) => (f.context as Record<string, unknown>)["injection_id"]).filter(Boolean);
  const isMeaning =
    m.is_injections_total && criteria
      ? m.is_injections_flagged
        ? `기준(${criteria.is_response_min_pct}–${criteria.is_response_max_pct}%) 밖: ${injections.map(String).join(" · ")}`
        : `모든 주입이 기준(${criteria.is_response_min_pct}–${criteria.is_response_max_pct}%) 이내`
      : undefined;

  const r2Ok = criteria && m.min_r_squared != null ? m.min_r_squared >= criteria.r_squared_min : null;

  return (
    <div className="space-y-3">
      <section
        aria-label="QC 판정"
        className={clsx("rounded-card border px-5 py-4", STATUS_FRAME[status])}
        data-testid="qc-verdict"
      >
        <p className="text-sm text-ink-muted">
          <Term k="qc">QC 판정</Term> — 허용 기준 대비 결정론적 판정
        </p>
        <p className={clsx("mt-1 flex flex-wrap items-baseline gap-x-3 text-2xl font-bold", STATUS_TEXT[status])}>
          <span>
            <span aria-hidden>{STATUS_ICON[status]} </span>
            {QC_STATUS[status].label}
          </span>
          {counts && <span className="text-base font-semibold text-ink">{counts}</span>}
        </p>
        <p className="mt-0.5 text-sm text-ink-muted">{STATUS_MEANING[status]}</p>
        {failed.length > 0 && (
          <ul className="mt-3 space-y-1" aria-label="불합격 항목">
            {failed.map((g) => (
              <CheckLine key={g.code} group={g} m={m} criteria={criteria} strong />
            ))}
          </ul>
        )}
        {warned.length > 0 && (
          <ul className="mt-2 space-y-1" aria-label="검토 필요 항목">
            {warned.map((g) => (
              <CheckLine key={g.code} group={g} m={m} criteria={criteria} strong={false} />
            ))}
          </ul>
        )}
        {status !== "pass" && (
          <p className="mt-3 text-sm">
            <Link to={{ pathname: "/research-ai", search, hash: "#critic" }} className="font-medium text-brand hover:underline">
              왜 이런 결과가 나왔는지 → Research AI의 비판적 검토
            </Link>
          </p>
        )}
      </section>

      <div className="grid gap-3 md:grid-cols-3">
        <StatTile
          label="평균 회수율"
          value={formatWithUnit(mean, "%")}
          tone={meanTone}
          meaning={meanMeaning ? <CodeText text={meanMeaning} /> : undefined}
          hint={m.recovery_n ? `n=${m.recovery_n}` : undefined}
          help={GLOSSARY.recovery}
        />
        <StatTile
          label="회수율 RSD (전체)"
          value={formatWithUnit(m.recovery_rsd_pct, "%")}
          tone={rsdFlags.length ? "warn" : "default"}
          meaning={rsdMeaning}
          help={GLOSSARY.rsd}
        />
        <StatTile
          label="IS 이탈 주입"
          value={m.is_injections_total ? `${m.is_injections_flagged ?? 0}/${m.is_injections_total}` : "—"}
          tone={m.is_injections_flagged ? "warn" : "default"}
          meaning={isMeaning}
          help={GLOSSARY.isSuppression}
        />
      </div>

      <p className="flex flex-wrap gap-x-5 gap-y-1.5 px-1 text-sm text-ink-muted">
        <span>
          <Term k="r2">검량선 최소 R²</Term> <b className="tabular-nums text-ink">{formatNumber(m.min_r_squared, 4)}</b>
          {r2Ok !== null && criteria && (
            <span className={r2Ok ? "text-ink-faint" : "text-crit"}>
              {" "}
              (기준 ≥{criteria.r_squared_min} {r2Ok ? "충족" : "미달"})
            </span>
          )}
          {m.calibration_weighting && <span className="text-ink-faint"> · <Term k="weighting">가중</Term> {m.calibration_weighting}</span>}
        </span>
        <span>
          <Term k="grubbs">이상치 의심 그룹</Term>{" "}
          <b className={clsx("tabular-nums", m.outlier_count ? "text-warn" : "text-ink")}>{m.outlier_count ?? "—"}</b>
        </span>
        {m.limits.length > 0 && (
          <span>
            <Term k="loq">LOD/LOQ</Term> {m.limits.length}개 분석물
          </span>
        )}
        <span className="text-ink-faint">
          판정 기준 {m.criteria_versions.join(", ") || "—"} · 근거 결과 #{m.source_result_ids.join(", #")}
        </span>
      </p>
    </div>
  );
}
