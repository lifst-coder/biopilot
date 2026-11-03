import { useEffect, useState } from "react";
import { useCompare } from "@/api/queries";
import type { ExperimentSummary } from "@/api/types";
import { Badge, Card, DataTable, EmptyState, ExperimentPicker, QueryState, Term } from "@/components";
import { formatNumber, formatPValue, formatWithUnit } from "@/lib/format";
import { MethodNotes } from "./MethodNotes";

interface Props {
  experiments: ExperimentSummary[];
  current: number | null;
  defaultBaseline: number | null;
}

function ci(low: number | null | undefined, high: number | null | undefined): string {
  if (low == null || high == null) return "—";
  return `[${formatNumber(low, 1)}, ${formatNumber(high, 1)}]`;
}

/** Mean differences, Welch t-tests, effect sizes and Holm-adjusted p (all backend values). */
export function ComparePanel({ experiments, current, defaultBaseline }: Props) {
  const [baseline, setBaseline] = useState<number | null>(defaultBaseline);
  useEffect(() => setBaseline(defaultBaseline), [defaultBaseline, current]);
  const cmp = useCompare(baseline, current);
  return (
    <Card
      title="실험 간 비교 통계"
      subtitle="현재 실험(b) − 기준 실험(a) · Welch t-검정 · Hedges g · Holm 보정"
      actions={<ExperimentPicker label="기준" experiments={experiments} value={baseline} allowEmpty onChange={setBaseline} />}
    >
      {baseline === null || current === null ? (
        <EmptyState>기준 실험을 선택하세요.</EmptyState>
      ) : (
        <QueryState query={cmp}>
          {(c) => {
            const t = c.recovery_t_test;
            const level = t?.confidence != null ? `CI ${formatNumber(t.confidence, 2)}` : "CI";
            return (
              <div className="space-y-3">
                <dl className="grid grid-cols-2 gap-3 text-xs md:grid-cols-4">
                  <div><dt className="text-ink-muted">평균 회수율 차이 Δ (<Term k="percentPoint">%p</Term>)</dt><dd className="text-base font-semibold">{formatWithUnit(c.recovery_delta_pct_points, "%p")}</dd></div>
                  <div><dt className="text-ink-muted">Δ의 {level} (Welch)</dt><dd className="font-mono">{ci(t?.ci_low, t?.ci_high)}</dd></div>
                  <div><dt className="text-ink-muted"><Term k="welch">t (df)</Term> · <Term k="pValue">p</Term></dt><dd className="font-mono">{t ? `${formatNumber(t.t_statistic, 2)} (${formatNumber(t.df, 1)})` : "—"} · {formatPValue(t?.p_value)}</dd></div>
                  <div><dt className="text-ink-muted"><Term k="hedgesG">효과 크기 Hedges g</Term></dt><dd className="font-mono">{formatNumber(t?.hedges_g, 2)} <span className="text-ink-faint">(d {formatNumber(t?.cohens_d, 2)})</span></dd></div>
                </dl>
                <DataTable
                  rows={c.per_analyte}
                  rowKey={(d) => d.analyte}
                  rowClassName={(d) => (d.significant ? "bg-warn-soft/50" : undefined)}
                  empty="두 실험 모두에 회수율 결과가 있어야 비교할 수 있습니다."
                  columns={[
                    { key: "a", header: "분석물", render: (d) => d.analyte },
                    { key: "ma", header: "기준", align: "right", render: (d) => formatWithUnit(d.mean_a_pct, "%") },
                    { key: "mb", header: "현재", align: "right", render: (d) => formatWithUnit(d.mean_b_pct, "%") },
                    { key: "d", header: "Δ", align: "right", render: (d) => formatWithUnit(d.delta_pct_points, "%p") },
                    { key: "ci", header: level, align: "right", render: (d) => ci(d.ci_low, d.ci_high) },
                    { key: "g", header: <Term k="hedgesG">g</Term>, align: "right", render: (d) => formatNumber(d.hedges_g, 2) },
                    { key: "p", header: <Term k="pValue">p</Term>, align: "right", render: (d) => formatPValue(d.p_value) },
                    { key: "ph", header: <Term k="holm">p (Holm)</Term>, align: "right", render: (d) => formatPValue(d.p_holm) },
                    {
                      key: "s",
                      header: `α=${c.alpha}`,
                      render: (d) => (d.significant == null ? "—" : d.significant ? <Badge tone="warn">유의</Badge> : <Badge>n.s.</Badge>),
                    },
                  ]}
                />
                <MethodNotes method={c.method} />
              </div>
            );
          }}
        </QueryState>
      )}
    </Card>
  );
}
