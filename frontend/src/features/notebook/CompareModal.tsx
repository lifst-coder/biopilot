import clsx from "clsx";
import { useState } from "react";
import { useCompare, useDiff, useRunAnalysis } from "@/api/queries";
import type { ExperimentSummary, MetricsComparison } from "@/api/types";
import { Badge, DataTable, EmptyState, ExperimentPicker, QueryState } from "@/components";
import { formatConditionValue, formatNumber, formatPValue, formatWithUnit } from "@/lib/format";
import { Modal } from "./Modal";

const RELATION: Record<string, string> = {
  same: "동일 실험",
  a_is_ancestor: "기준이 조상",
  b_is_ancestor: "현재가 조상",
  siblings: "형제 실험",
  unrelated: "무관",
};

const CHANGE: Record<string, { label: string; tone: "warn" | "ok" | "crit" }> = {
  changed: { label: "변경", tone: "warn" },
  added: { label: "추가", tone: "ok" },
  removed: { label: "삭제", tone: "crit" },
};

interface Props {
  experiments: ExperimentSummary[];
  current: number;
  defaultBaseline: number | null;
  onClose: () => void;
}

/**
 * "과거 실험과 비교": conditions/note/datasets from the Memory diff API and stored
 * analysis results (with backend-computed deltas) from the Analysis compare API.
 * The UI only formats values; no number is computed here.
 */
export function CompareModal({ experiments, current, defaultBaseline, onClose }: Props) {
  const others = experiments.filter((e) => e.id !== current);
  const [baseline, setBaseline] = useState<number | null>(defaultBaseline ?? others[others.length - 1]?.id ?? null);
  const diff = useDiff(baseline, current);
  const cmp = useCompare(baseline, current);
  const [showNote, setShowNote] = useState(false);
  const codeOf = (id: number) => experiments.find((e) => e.id === id)?.code ?? `#${id}`;

  return (
    <Modal title="과거 실험과 비교" onClose={onClose} wide>
      <div className="mb-3 flex flex-wrap items-center gap-3">
        <ExperimentPicker label="기준(과거) 실험" experiments={others} value={baseline} allowEmpty onChange={setBaseline} />
        <span className="text-xs text-ink-muted">
          현재: <b>{experiments.find((e) => e.id === current)?.code}</b>
        </span>
      </div>
      {baseline === null ? (
        <EmptyState>비교할 과거 실험을 선택하세요.</EmptyState>
      ) : (
        <div className="space-y-5">
          <QueryState query={diff}>
            {(d) => (
              <div className="space-y-4">
                <div className="flex flex-wrap items-center gap-2 text-xs">
                  <Badge tone="brand">{RELATION[d.relation] ?? d.relation}</Badge>
                  <span>
                    {d.a.code} → {d.b.code}
                  </span>
                  <span className="text-ink-faint">
                    조건 차이 {d.condition_changes.length}개 · 동일 조건 {d.unchanged_keys.length}개
                  </span>
                </div>
                <section>
                  <h3 className="mb-1 text-xs font-semibold text-ink-muted">조건 차이</h3>
                  <DataTable
                    rows={d.condition_changes}
                    rowKey={(c) => c.key}
                    empty="조건 차이 없음"
                    columns={[
                      { key: "label", header: "조건", render: (c) => c.label },
                      { key: "a", header: `기준 ${d.a.code}`, render: (c) => formatConditionValue(c.value_a) },
                      {
                        key: "b",
                        header: `현재 ${d.b.code}`,
                        render: (c) => <span className="font-medium text-warn">{formatConditionValue(c.value_b)}</span>,
                      },
                      {
                        key: "change",
                        header: "유형",
                        render: (c) => <Badge tone={CHANGE[c.change]?.tone ?? "warn"}>{CHANGE[c.change]?.label ?? c.change}</Badge>,
                      },
                    ]}
                  />
                </section>
                <section>
                  <h3 className="mb-1 text-xs font-semibold text-ink-muted">데이터셋</h3>
                  <DataTable
                    rows={[
                      { key: "both", label: "공통", kinds: d.datasets.both },
                      { key: "a", label: `기준에만 (${d.a.code})`, kinds: d.datasets.only_a },
                      { key: "b", label: `현재에만 (${d.b.code})`, kinds: d.datasets.only_b },
                    ]}
                    rowKey={(r) => r.key}
                    columns={[
                      { key: "l", header: "구분", render: (r) => r.label },
                      { key: "k", header: "종류", render: (r) => (r.kinds.length ? r.kinds.join(", ") : "—") },
                    ]}
                  />
                </section>
                <section>
                  <button type="button" className="text-xs text-brand underline" onClick={() => setShowNote(!showNote)}>
                    메모 차이 {showNote ? "접기" : "보기"} ({d.note_diff.filter((l) => l.op !== "equal").length}줄 변경)
                  </button>
                  {showNote && (
                    <pre className="mt-1 max-h-60 overflow-auto rounded-md bg-subtle p-2 font-mono text-[11px] leading-relaxed">
                      {d.note_diff.map((line, i) => (
                        <div
                          key={i}
                          className={clsx(
                            line.op === "insert" && "bg-ok-soft text-ok",
                            line.op === "delete" && "bg-crit-soft text-crit line-through",
                          )}
                        >
                          {line.op === "insert" ? "+ " : line.op === "delete" ? "- " : "  "}
                          {line.text}
                        </div>
                      ))}
                    </pre>
                  )}
                </section>
              </div>
            )}
          </QueryState>

          <section>
            <h3 className="mb-1 text-xs font-semibold text-ink-muted">결과 차이 (Analysis 저장 결과)</h3>
            <QueryState query={cmp}>
              {(c) => (
                <>
                  <AnalysisStatus
                    sides={[
                      { role: "기준", id: baseline, code: codeOf(baseline), analyzed: c.metrics_a.analyzed },
                      { role: "현재", id: current, code: codeOf(current), analyzed: c.metrics_b.analyzed },
                    ]}
                  />
                  <ResultDiff c={c} />
                </>
              )}
            </QueryState>
          </section>
        </div>
      )}
    </Modal>
  );
}

interface Side {
  role: "기준" | "현재";
  id: number;
  code: string;
  analyzed: boolean;
}

/**
 * Analysis compare reads *stored* results only, so a freshly recorded experiment shows
 * empty deltas until it is analysed. Show which side is unanalysed and offer to run the
 * (idempotent) analysis; the compare query refreshes when the run invalidates `analysis`.
 */
function AnalysisStatus({ sides }: { sides: Side[] }) {
  const run = useRunAnalysis();
  const missing = sides.filter((s) => !s.analyzed);
  if (missing.length === 0) return null;
  return (
    <div className="mb-2 space-y-1" data-testid="analysis-status">
      {missing.map((s) => (
        <div key={s.id} className="flex flex-wrap items-center gap-2 text-xs">
          <Badge tone="warn">{s.role} 실험 미분석</Badge>
          <span className="text-ink-muted">{s.code}에 저장된 분석 결과가 없습니다.</span>
          <button
            type="button"
            className="bp-btn-primary px-2 py-1 text-xs"
            disabled={run.isPending}
            onClick={() => run.mutate(s.id)}
          >
            {run.isPending && run.variables === s.id ? "분석 중…" : `${s.code} 분석 실행`}
          </button>
        </div>
      ))}
      {run.data && run.data.skipped.length > 0 && (
        <p className="text-xs text-ink-muted">건너뜀: {run.data.skipped.join(" · ")}</p>
      )}
      {run.error && <p className="text-xs text-crit">분석 실행 실패: {String((run.error as Error).message ?? run.error)}</p>}
    </div>
  );
}

function ResultDiff({ c }: { c: MetricsComparison }) {
  const a = c.metrics_a;
  const b = c.metrics_b;
  if (!a.analyzed && !b.analyzed) return <EmptyState>두 실험 모두 분석 결과가 없습니다.</EmptyState>;
  if (!b.analyzed) return <EmptyState>현재 실험이 아직 분석되지 않아 결과 차이를 표시할 수 없습니다.</EmptyState>;
  const rows = [
    {
      key: "rec",
      label: "평균 회수율",
      a: formatWithUnit(a.recovery_mean_pct, "%"),
      b: formatWithUnit(b.recovery_mean_pct, "%"),
      d: formatWithUnit(c.recovery_delta_pct_points, "%p"),
    },
    { key: "rsd", label: "회수율 RSD", a: formatWithUnit(a.recovery_rsd_pct, "%"), b: formatWithUnit(b.recovery_rsd_pct, "%"), d: "—" },
    { key: "n", label: "회수율 n", a: a.recovery_n ?? "—", b: b.recovery_n ?? "—", d: "—" },
    { key: "r2", label: "최소 R²", a: formatNumber(a.min_r_squared, 4), b: formatNumber(b.min_r_squared, 4), d: "—" },
    {
      key: "re",
      label: "최대 |역산 오차|",
      a: formatWithUnit(a.max_abs_back_calc_error_pct, "%"),
      b: formatWithUnit(b.max_abs_back_calc_error_pct, "%"),
      d: "—",
    },
    {
      key: "is",
      label: "IS 이상 주입",
      a: a.is_injections_total != null ? `${a.is_injections_flagged ?? 0}/${a.is_injections_total}` : "—",
      b: b.is_injections_total != null ? `${b.is_injections_flagged ?? 0}/${b.is_injections_total}` : "—",
      d: "—",
    },
    { key: "flags", label: "QC 플래그", a: a.flags.length, b: b.flags.length, d: "—" },
  ];
  return (
    <div className="space-y-3">
      <DataTable
        rows={rows}
        rowKey={(r) => r.key}
        columns={[
          { key: "l", header: "지표", render: (r) => r.label },
          { key: "a", header: "기준", align: "right", render: (r) => r.a },
          { key: "b", header: "현재", align: "right", render: (r) => r.b },
          { key: "d", header: "변화", align: "right", render: (r) => r.d },
        ]}
      />
      {c.recovery_t_test && (
        <p className="text-xs text-ink-muted">
          회수율 Welch t-test {formatPValue(c.recovery_t_test.p_value)} (n={c.recovery_t_test.n_a} vs {c.recovery_t_test.n_b})
        </p>
      )}
      {c.per_analyte.length > 0 && (
        <DataTable
          rows={c.per_analyte}
          rowKey={(d) => d.analyte}
          columns={[
            { key: "a", header: "분석물", render: (d) => d.analyte },
            { key: "ma", header: "기준 회수율", align: "right", render: (d) => formatWithUnit(d.mean_a_pct, "%") },
            { key: "mb", header: "현재 회수율", align: "right", render: (d) => formatWithUnit(d.mean_b_pct, "%") },
            { key: "d", header: "변화", align: "right", render: (d) => formatWithUnit(d.delta_pct_points, "%p") },
          ]}
        />
      )}
    </div>
  );
}
