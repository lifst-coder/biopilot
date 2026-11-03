import { useState } from "react";
import type { AcceptanceCriteria, RecordExperiment, RecordGroup } from "@/api/types";
import { ExperimentChip } from "@/components";
import { formatNumber, formatRatio, formatWithUnit } from "@/lib/format";

/** `{project_id → short label}`; empty when only one project is in scope (no label needed). */
export type ProjectLabels = Record<number, string>;

/** Chips of evidence experiments, failing ones first; the rest behind a toggle. */
export function EvidenceExperiments({
  experiments,
  labels,
  initial = 6,
}: {
  experiments: RecordExperiment[];
  labels: ProjectLabels;
  initial?: number;
}) {
  const [all, setAll] = useState(false);
  const ordered = [
    ...experiments.filter((e) => e.qc_status === "fail"),
    ...experiments.filter((e) => e.qc_status !== "fail"),
  ];
  const shown = all ? ordered : ordered.slice(0, initial);
  return (
    <div className="flex flex-wrap items-center gap-1" aria-label="근거 실험">
      {shown.map((e) => (
        <ExperimentChip
          key={e.experiment_id}
          id={e.experiment_id}
          code={e.code}
          projectId={e.project_id}
          projectLabel={labels[e.project_id]}
          qc={e.qc_status}
          value={e.recovery_mean_pct != null ? formatWithUnit(e.recovery_mean_pct, "%") : null}
          title={`${e.title} · ${e.author} · ${e.performed_on}`}
        />
      ))}
      {ordered.length > initial && (
        <button type="button" className="px-1 text-xs font-medium text-brand hover:underline" onClick={() => setAll(!all)}>
          {all ? "접기" : `+${ordered.length - initial}건 더`}
        </button>
      )}
    </div>
  );
}

/**
 * Stored mean recovery of each member on a 0–150% axis with the acceptance band; failing
 * experiments are drawn as ✕, others as ●, so the shape (not only the color) carries QC.
 */
export function RecoveryStrip({ group, criteria }: { group: RecordGroup; criteria: AcceptanceCriteria | null }) {
  const max = 150;
  const pos = (v: number) => `${(Math.min(Math.max(v, 0), max) / max) * 100}%`;
  const points = group.experiments.filter((e) => e.recovery_mean_pct != null);
  if (points.length === 0) return null;
  return (
    <div className="relative h-5 w-full max-w-md" role="img" aria-label="실험별 평균 회수율 분포 (0–150%)">
      <div className="absolute inset-x-0 top-1/2 h-px bg-border" />
      {criteria && (
        <div
          className="absolute top-1 h-3 rounded-sm bg-ok-soft"
          style={{ left: pos(criteria.recovery_min_pct), width: `calc(${pos(criteria.recovery_max_pct)} - ${pos(criteria.recovery_min_pct)})` }}
          title={`허용 기준 ${criteria.recovery_min_pct}–${criteria.recovery_max_pct}%`}
        />
      )}
      {points.map((e) => (
        <span
          key={e.experiment_id}
          title={`${e.code} ${formatWithUnit(e.recovery_mean_pct, "%")}`}
          className={
            e.qc_status === "fail"
              ? "absolute top-0 -translate-x-1/2 text-sm font-bold leading-5 text-crit"
              : "absolute top-1/2 h-2 w-2 -translate-x-1/2 -translate-y-1/2 rounded-full bg-brand/70"
          }
          style={{ left: pos(e.recovery_mean_pct!) }}
        >
          {e.qc_status === "fail" ? "✕" : null}
        </span>
      ))}
    </div>
  );
}

/** Column header for {@link GroupRow} lists (≥ sm; on phones each value carries its label). */
export function GroupHeader({ first }: { first: string }) {
  return (
    <div className="hidden border-b border-border pb-1.5 text-xs font-semibold text-ink-muted sm:grid sm:grid-cols-[minmax(0,1fr)_4rem_10rem_7.5rem] sm:gap-x-4">
      <span>{first}</span>
      <span className="text-right">실험</span>
      <span className="text-right">평균 회수율 중앙값 (범위)</span>
      <span className="text-right">QC 불합격</span>
    </div>
  );
}

/** One group: label, count, stored-recovery median (min–max), fail ratio, strip, evidence. */
export function GroupRow({
  label,
  group,
  criteria,
  labels,
  highlight = false,
}: {
  label: React.ReactNode;
  group: RecordGroup;
  criteria: AcceptanceCriteria | null;
  labels: ProjectLabels;
  highlight?: boolean;
}) {
  const failed = group.fail_count > 0;
  return (
    <li className={highlight ? "-mx-2 rounded-md bg-warn-soft/40 px-2 py-2.5" : "py-2.5"}>
      <div className="grid gap-x-4 gap-y-0.5 sm:grid-cols-[minmax(0,1fr)_4rem_10rem_7.5rem] sm:items-baseline">
        <div className="min-w-0 break-words text-sm font-medium text-ink">{label}</div>
        <div className="text-sm tabular-nums text-ink-muted sm:text-right">
          <span className="sm:hidden">실험 </span>
          {group.experiment_count}
        </div>
        <div className="text-sm tabular-nums sm:text-right">
          <span className="text-ink-muted sm:hidden">회수율 중앙값 </span>
          {formatWithUnit(group.recovery_median_pct, "%")}
          {group.recovery_n > 1 && (
            <span className="ml-1 text-xs text-ink-faint">
              ({formatNumber(group.recovery_min_pct)}–{formatNumber(group.recovery_max_pct)})
            </span>
          )}
        </div>
        <div className={failed ? "text-sm font-medium tabular-nums text-crit sm:text-right" : "text-sm tabular-nums text-ink-muted sm:text-right"}>
          <span className="font-normal text-ink-muted sm:hidden">QC 불합격 </span>
          {failed && <span aria-hidden>✕ </span>}
          {group.fail_count}/{group.analyzed_count}
          <span className="ml-1 text-xs">{group.analyzed_count ? formatRatio(group.fail_ratio) : ""}</span>
        </div>
      </div>
      <div className="mt-1.5 space-y-1.5">
        <RecoveryStrip group={group} criteria={criteria} />
        <EvidenceExperiments experiments={group.experiments} labels={labels} />
      </div>
    </li>
  );
}

/** Segmented two-option control with an accessible pressed state. */
export function Segmented<T extends string>({
  value,
  options,
  onChange,
  label,
}: {
  value: T;
  options: { value: T; label: string }[];
  onChange: (v: T) => void;
  label: string;
}) {
  return (
    <div role="group" aria-label={label} className="inline-flex rounded-md border border-border bg-surface p-0.5">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          aria-pressed={value === o.value}
          onClick={() => onChange(o.value)}
          className={
            value === o.value
              ? "rounded px-3 py-1 text-sm font-medium text-brand-strong bg-brand-soft"
              : "rounded px-3 py-1 text-sm text-ink-muted hover:bg-subtle"
          }
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}
