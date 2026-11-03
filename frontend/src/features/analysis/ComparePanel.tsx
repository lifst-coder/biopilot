import { useEffect, useState } from "react";
import { useCompare } from "@/api/queries";
import type { ExperimentSummary } from "@/api/types";
import { Card, DataTable, EmptyState, ExperimentPicker, QueryState } from "@/components";
import { formatPValue, formatWithUnit } from "@/lib/format";

interface Props {
  experiments: ExperimentSummary[];
  current: number | null;
  defaultBaseline: number | null;
}

/** Numerical comparison (deltas + Welch t-test) computed by the backend. */
export function ComparePanel({ experiments, current, defaultBaseline }: Props) {
  const [baseline, setBaseline] = useState<number | null>(defaultBaseline);
  useEffect(() => setBaseline(defaultBaseline), [defaultBaseline, current]);
  const cmp = useCompare(baseline, current);
  return (
    <Card
      title="수치 비교"
      subtitle="현재 실험 − 기준 실험"
      actions={<ExperimentPicker label="기준" experiments={experiments} value={baseline} allowEmpty onChange={setBaseline} />}
    >
      {baseline === null || current === null ? (
        <EmptyState>기준 실험을 선택하세요.</EmptyState>
      ) : (
        <QueryState query={cmp}>
          {(c) => (
            <div className="space-y-3">
              <p className="text-xs">
                평균 회수율 변화 <b>{formatWithUnit(c.recovery_delta_pct_points, "%p")}</b>
                {c.recovery_t_test && (
                  <span className="text-ink-muted">
                    {" "}· Welch t-test {formatPValue(c.recovery_t_test.p_value)} (n={c.recovery_t_test.n_a} vs {c.recovery_t_test.n_b})
                  </span>
                )}
              </p>
              <DataTable
                rows={c.per_analyte}
                rowKey={(d) => d.analyte}
                empty="두 실험 모두에 회수율 결과가 있어야 비교할 수 있습니다."
                columns={[
                  { key: "a", header: "분석물", render: (d) => d.analyte },
                  { key: "ma", header: "기준", align: "right", render: (d) => formatWithUnit(d.mean_a_pct, "%") },
                  { key: "mb", header: "현재", align: "right", render: (d) => formatWithUnit(d.mean_b_pct, "%") },
                  { key: "d", header: "변화", align: "right", render: (d) => formatWithUnit(d.delta_pct_points, "%p") },
                ]}
              />
            </div>
          )}
        </QueryState>
      )}
    </Card>
  );
}
