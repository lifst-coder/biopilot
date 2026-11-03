import { useMetrics, useResults } from "@/api/queries";
import type { AnalysisResultOut } from "@/api/types";
import { Card, EmptyState, ExperimentPicker, QueryState, StatTile } from "@/components";
import { formatNumber, formatWithUnit } from "@/lib/format";
import { useSelectedExperiment } from "@/lib/selection";
import { CalibrationPanel } from "./CalibrationPanel";
import { ComparePanel } from "./ComparePanel";
import { FlagList } from "./FlagList";
import { ISResponsePanel } from "./ISResponsePanel";
import { MatrixEffectPanel } from "./MatrixEffectPanel";
import { RecoveryPanel } from "./RecoveryPanel";

/** Latest stored result per kind (results are ordered by id ascending). */
function latestByKind(results: AnalysisResultOut[]) {
  const map = new Map<AnalysisResultOut["kind"], AnalysisResultOut>();
  for (const r of results) map.set(r.kind, r);
  return map;
}

/** Deterministic calculation results. No interpretation on this tab. */
export function AnalysisPage() {
  const { experiments, selected, selectedId, select } = useSelectedExperiment();
  const metrics = useMetrics(selectedId);
  const results = useResults(selectedId);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-lg font-semibold">Analysis {selected && <span className="text-ink-muted">· {selected.code}</span>}</h1>
        <ExperimentPicker experiments={experiments} value={selectedId} onChange={select} />
      </div>

      <QueryState query={metrics}>
        {(m) =>
          !m.analyzed ? (
            <EmptyState>저장된 분석 결과가 없습니다.</EmptyState>
          ) : (
            <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
              <StatTile label="평균 회수율" value={formatWithUnit(m.recovery_mean_pct, "%")} hint={m.recovery_n ? `n=${m.recovery_n}` : undefined} />
              <StatTile label="회수율 RSD (전체)" value={formatWithUnit(m.recovery_rsd_pct, "%")} />
              <StatTile
                label="검량선 최소 R²"
                value={formatNumber(m.min_r_squared, 4)}
                hint={m.calibration_weighting ? `가중 ${m.calibration_weighting}` : undefined}
              />
              <StatTile
                label="QC 플래그"
                value={m.flags.length}
                tone={m.flags.some((f) => f.severity === "critical") ? "crit" : m.flags.length ? "warn" : "ok"}
                hint={`근거 결과 #${m.source_result_ids.join(", #")}`}
              />
            </div>
          )
        }
      </QueryState>

      <QueryState query={results}>
        {(list) => {
          const latest = latestByKind(list);
          const cal = latest.get("calibration");
          const rec = latest.get("recovery");
          const isr = latest.get("is_response");
          const me = latest.get("matrix_effect");
          return (
            <div className="space-y-4">
              {cal?.output.kind === "calibration" && <CalibrationPanel result={cal} output={cal.output} />}
              {rec?.output.kind === "recovery" && <RecoveryPanel result={rec} output={rec.output} />}
              {isr?.output.kind === "is_response" && <ISResponsePanel result={isr} output={isr.output} />}
              {me?.output.kind === "matrix_effect" && <MatrixEffectPanel result={me} output={me.output} />}
              <Card title="QC 플래그" subtitle="허용 기준 대비 결정론적 판정">
                <FlagList flags={list.flatMap((r) => (latest.get(r.kind) === r ? r.flags : []))} />
              </Card>
            </div>
          );
        }}
      </QueryState>

      <ComparePanel experiments={experiments} current={selectedId} defaultBaseline={selected?.parent_experiment_id ?? null} />
    </div>
  );
}
