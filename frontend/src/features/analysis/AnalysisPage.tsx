import { useCriteria, useMetrics, useResults } from "@/api/queries";
import type { AnalysisResultOut } from "@/api/types";
import { Badge, Card, EmptyState, ExperimentPicker, QueryState, StatTile } from "@/components";
import { formatNumber, formatWithUnit } from "@/lib/format";
import { useSelectedExperiment } from "@/lib/selection";
import { CalibrationPanel } from "./CalibrationPanel";
import { ComparePanel } from "./ComparePanel";
import { CriteriaPanel } from "./CriteriaPanel";
import { FlagList } from "./FlagList";
import { IonRatioPanel } from "./IonRatioPanel";
import { ISResponsePanel } from "./ISResponsePanel";
import { QC_STATUS } from "./labels";
import { LimitsPanel } from "./LimitsPanel";
import { MatrixEffectPanel } from "./MatrixEffectPanel";
import { QCVerdictTable } from "./QCVerdictTable";
import { RecoveryPanel } from "./RecoveryPanel";
import { ReportExport } from "./ReportExport";

/** Latest stored result per kind (results are ordered by id ascending). */
export function latestByKind(results: AnalysisResultOut[]) {
  const map = new Map<AnalysisResultOut["kind"], AnalysisResultOut>();
  for (const r of results) map.set(r.kind, r);
  return map;
}

/** Deterministic calculation results. No interpretation on this tab. */
export function AnalysisPage() {
  const { experiments, selected, selectedId, select } = useSelectedExperiment();
  const metrics = useMetrics(selectedId);
  const results = useResults(selectedId);
  const projectId = selected?.project_id ?? null;
  const { data: criteria } = useCriteria(projectId);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-lg font-semibold">Analysis {selected && <span className="text-ink-muted">· {selected.code}</span>}</h1>
        <div className="flex flex-wrap items-center gap-3">
          <ReportExport experimentId={selectedId} />
          <ExperimentPicker experiments={experiments} value={selectedId} onChange={select} />
        </div>
      </div>

      <QueryState query={metrics}>
        {(m) =>
          !m.analyzed ? (
            <EmptyState>저장된 분석 결과가 없습니다.</EmptyState>
          ) : (
            <div className="grid grid-cols-2 gap-3 xl:grid-cols-6">
              <StatTile
                label="QC 판정"
                value={<Badge tone={QC_STATUS[m.qc_status].tone}>{QC_STATUS[m.qc_status].label}</Badge>}
                hint={`기준 ${m.criteria_versions.join(", ") || "—"}`}
                tone={m.qc_status === "fail" ? "crit" : m.qc_status === "warning" ? "warn" : "ok"}
              />
              <StatTile label="평균 회수율" value={formatWithUnit(m.recovery_mean_pct, "%")} hint={m.recovery_n ? `n=${m.recovery_n}` : undefined} />
              <StatTile label="회수율 RSD (전체)" value={formatWithUnit(m.recovery_rsd_pct, "%")} />
              <StatTile
                label="검량선 최소 R²"
                value={formatNumber(m.min_r_squared, 4)}
                hint={m.calibration_weighting ? `가중 ${m.calibration_weighting}` : undefined}
              />
              <StatTile
                label="이상치 의심 그룹"
                value={m.outlier_count ?? "—"}
                tone={m.outlier_count ? "warn" : "default"}
                hint={m.limits.length ? `LOD/LOQ ${m.limits.length}개 분석물` : undefined}
              />
              <StatTile
                label="IS 이탈 주입"
                value={m.is_injections_total ? `${m.is_injections_flagged ?? 0}/${m.is_injections_total}` : "—"}
                tone={m.is_injections_flagged ? "warn" : "default"}
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
          const lim = latest.get("limits");
          const rec = latest.get("recovery");
          const isr = latest.get("is_response");
          const me = latest.get("matrix_effect");
          const ion = latest.get("ion_ratio");
          return (
            <div className="space-y-4">
              {cal?.output.kind === "calibration" && <CalibrationPanel result={cal} output={cal.output} />}
              {lim?.output.kind === "limits" && <LimitsPanel result={lim} output={lim.output} />}
              {rec?.output.kind === "recovery" && <RecoveryPanel result={rec} output={rec.output} criteria={criteria} />}
              {isr?.output.kind === "is_response" && <ISResponsePanel result={isr} output={isr.output} criteria={criteria} />}
              {me?.output.kind === "matrix_effect" && <MatrixEffectPanel result={me} output={me.output} criteria={criteria} />}
              {ion?.output.kind === "ion_ratio" && <IonRatioPanel result={ion} output={ion.output} />}
              <Card title="QC 판정 · 플래그" subtitle="허용 기준 대비 결정론적 판정 (critical → 불합격, warning → 검토 필요)">
                <div className="space-y-4">
                  {metrics.data && <QCVerdictTable verdicts={metrics.data.qc_verdicts} />}
                  <FlagList flags={list.flatMap((r) => (latest.get(r.kind) === r ? r.flags : []))} />
                </div>
              </Card>
            </div>
          );
        }}
      </QueryState>

      <ComparePanel experiments={experiments} current={selectedId} defaultBaseline={selected?.parent_experiment_id ?? null} />
      <CriteriaPanel projectId={projectId} experimentId={selectedId} />
    </div>
  );
}
