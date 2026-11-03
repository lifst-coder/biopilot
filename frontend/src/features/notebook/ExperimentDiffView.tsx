import clsx from "clsx";
import { useEffect, useState } from "react";
import { useDiff } from "@/api/queries";
import type { ExperimentSummary } from "@/api/types";
import { Badge, Card, DataTable, EmptyState, ExperimentPicker, QueryState } from "@/components";
import { formatConditionValue } from "@/lib/format";

const RELATION: Record<string, string> = {
  same: "동일 실험",
  a_is_ancestor: "기준이 조상",
  b_is_ancestor: "현재가 조상",
  siblings: "형제 실험",
  unrelated: "무관",
};

interface Props {
  experiments: ExperimentSummary[];
  current: number;
  defaultBaseline: number | null;
}

/** Memory diff between a baseline experiment and the current one. */
export function ExperimentDiffView({ experiments, current, defaultBaseline }: Props) {
  const [baseline, setBaseline] = useState<number | null>(defaultBaseline);
  useEffect(() => setBaseline(defaultBaseline), [defaultBaseline, current]);
  const diff = useDiff(baseline, current);

  return (
    <Card
      title="실험 비교 (Memory diff)"
      subtitle="원본 기록 간 구조적 차이 — 수치 비교는 Analysis 탭"
      actions={
        <ExperimentPicker
          label="기준"
          experiments={experiments}
          value={baseline}
          allowEmpty
          onChange={setBaseline}
        />
      }
    >
      {baseline === null ? (
        <EmptyState>비교할 기준 실험을 선택하세요.</EmptyState>
      ) : (
        <QueryState query={diff}>
          {(d) => (
            <div className="space-y-4">
              <div className="flex flex-wrap items-center gap-2 text-xs">
                <Badge tone="brand">{RELATION[d.relation] ?? d.relation}</Badge>
                <span>
                  {d.a.code} → {d.b.code}
                </span>
                <span className="text-ink-faint">동일 조건 {d.unchanged_keys.length}개</span>
              </div>
              <DataTable
                rows={d.condition_changes}
                rowKey={(c) => c.key}
                empty="조건 차이 없음"
                columns={[
                  { key: "label", header: "조건", render: (c) => c.label },
                  { key: "a", header: d.a.code, render: (c) => formatConditionValue(c.value_a) },
                  {
                    key: "b",
                    header: d.b.code,
                    render: (c) => <span className="font-medium text-warn">{formatConditionValue(c.value_b)}</span>,
                  },
                  { key: "change", header: "유형", render: (c) => c.change },
                ]}
              />
              <div>
                <h3 className="mb-1 text-xs font-semibold text-ink-muted">메모 차이</h3>
                <pre className="max-h-72 overflow-auto rounded-md bg-subtle p-2 font-mono text-[11px] leading-relaxed">
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
              </div>
            </div>
          )}
        </QueryState>
      )}
    </Card>
  );
}
