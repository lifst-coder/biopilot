import clsx from "clsx";
import { Link } from "react-router-dom";
import { experimentSearch } from "@/lib/selection";

export type QcStatus = "pass" | "warning" | "fail" | "not_analyzed";

const QC: Record<QcStatus, { glyph: string; label: string; className: string }> = {
  fail: { glyph: "✕", label: "QC 불합격", className: "text-crit" },
  warning: { glyph: "!", label: "QC 주의", className: "text-warn" },
  pass: { glyph: "✓", label: "QC 통과", className: "text-ok" },
  not_analyzed: { glyph: "–", label: "분석 결과 없음", className: "text-ink-faint" },
};

/** Stored QC status as a glyph *and* a spoken label (never color alone). */
export function QcMark({ status, withLabel = false }: { status: string; withLabel?: boolean }) {
  const q = QC[(status in QC ? status : "not_analyzed") as QcStatus];
  return (
    <span title={q.label} className={clsx("inline-flex items-center gap-0.5 font-bold", q.className)}>
      <span aria-hidden>{q.glyph}</span>
      {withLabel ? <span className="font-medium">{q.label.replace("QC ", "")}</span> : <span className="sr-only">{q.label}</span>}
    </span>
  );
}

interface ExperimentChipProps {
  id: number;
  code: string;
  projectId?: number | null;
  /** Short project name — shown when the chip may point into another project. */
  projectLabel?: string | null;
  qc?: string | null;
  /** Pre-formatted stored value shown after the code (e.g. "82.0%"). */
  value?: string | null;
  title?: string;
}

/**
 * Evidence experiment: code (+ project, QC mark, stored value). Opens the experiment in the
 * Notebook of its own project (`?project=&exp=`).
 */
export function ExperimentChip({ id, code, projectId, projectLabel, qc, value, title }: ExperimentChipProps) {
  return (
    <Link
      to={{ pathname: "/notebook", search: experimentSearch(id, projectId) }}
      title={title}
      className="inline-flex items-center gap-1 whitespace-nowrap rounded border border-border bg-surface px-1.5 py-0.5 text-xs hover:border-brand/50 hover:bg-brand-soft"
    >
      {qc && <QcMark status={qc} />}
      <span className="font-medium text-brand">{code}</span>
      {projectLabel && <span className="text-ink-faint">{projectLabel}</span>}
      {value && <span className="tabular-nums text-ink">{value}</span>}
    </Link>
  );
}
