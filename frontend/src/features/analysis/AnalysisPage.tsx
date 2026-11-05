import { Link } from "react-router-dom";
import { useCompare, useCriteria, useMetrics, useResults, useRunAnalysis } from "@/api/queries";
import type { AnalysisResultOut, ExperimentSummary } from "@/api/types";
import { Card, CodeText, Disclosure, EmptyState, ErrorState, ExperimentPicker, PageHeader, QueryState, Term } from "@/components";
import { TABS } from "@/layout/tabs";
import { formatPValue, formatWithUnit } from "@/lib/format";
import { experimentSearch, useSelectedExperiment } from "@/lib/selection";
import { CalibrationPanel } from "./CalibrationPanel";
import { ComparePanel } from "./ComparePanel";
import { CriteriaPanel } from "./CriteriaPanel";
import { FlagList } from "./FlagList";
import { IonRatioPanel } from "./IonRatioPanel";
import { ISResponsePanel } from "./ISResponsePanel";
import { LimitsPanel } from "./LimitsPanel";
import { MatrixEffectPanel } from "./MatrixEffectPanel";
import { QCVerdictTable } from "./QCVerdictTable";
import { RecoveryPanel } from "./RecoveryPanel";
import { ReportExport } from "./ReportExport";
import { flagSummary, flagTone, VerdictSummary } from "./VerdictSummary";

const QUESTION = TABS.find((t) => t.path === "/analysis")?.question ?? "";

/** Latest stored result per kind (results are ordered by id ascending). */
export function latestByKind(results: AnalysisResultOut[]) {
  const map = new Map<AnalysisResultOut["kind"], AnalysisResultOut>();
  for (const r of results) map.set(r.kind, r);
  return map;
}

/**
 * No stored result for this experiment: say what is missing and how to fill it — run the
 * analysis on its stored CSVs, or upload CSVs in the Notebook first.
 */
function NotAnalyzed({ experiment }: { experiment: ExperimentSummary | null }) {
  const run = useRunAnalysis();
  if (!experiment) {
    return <EmptyState>이 프로젝트에 실험이 없습니다 — Notebook의 ‘+ 새 실험’으로 첫 기록을 남기세요.</EmptyState>;
  }
  const notebook = { pathname: "/notebook", search: experimentSearch(experiment.id, experiment.project_id) };
  return (
    <Card>
      <p className="bp-prose text-ink-muted">
        {experiment.code}에는 저장된 분석 결과가 없습니다.{" "}
        {experiment.dataset_kinds.length > 0
          ? `저장된 CSV(${experiment.dataset_kinds.join(" · ")})로 계산하면 결과가 불변 레코드로 남습니다.`
          : "검량선·회수율 CSV가 아직 없습니다 — Notebook의 ‘데이터셋 (CSV)’에서 올린 뒤 분석하세요."}
      </p>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        {experiment.dataset_kinds.length > 0 ? (
          <button
            type="button"
            className="bp-btn-primary"
            disabled={run.isPending}
            onClick={() => run.mutate(experiment.id)}
          >
            {run.isPending ? "분석 중…" : `${experiment.code} 분석 실행`}
          </button>
        ) : (
          <Link to={notebook} className="bp-btn-primary">
            CSV 올리러 Notebook으로 →
          </Link>
        )}
      </div>
      {run.isError && (
        <div className="mt-2">
          <ErrorState error={run.error} />
        </div>
      )}
    </Card>
  );
}

/**
 * Deterministic calculation results, ordered by the one question the tab answers —
 * "이 실험의 결과를 신뢰할 수 있는가": QC verdict → three key numbers → the evidence
 * (calibration, residuals, uncertainty, IS, comparison, criteria) collapsed below.
 * No interpretation on this tab: words are chosen only by comparing stored values with
 * the stored criteria.
 */
export function AnalysisPage() {
  const { experiments, selected, selectedId, select } = useSelectedExperiment();
  const metrics = useMetrics(selectedId);
  const results = useResults(selectedId);
  const projectId = selected?.project_id ?? null;
  const { data: criteria } = useCriteria(projectId);
  const baselineId = selected?.parent_experiment_id ?? null;
  const baselineCode = experiments.find((e) => e.id === baselineId)?.code ?? null;
  const { data: baselineMetrics } = useMetrics(baselineId);
  const { data: cmp } = useCompare(baselineId, selectedId);

  return (
    <div className="space-y-4">
      <PageHeader
        title={
          <>
            Analysis {selected && <span className="text-ink-muted">· {selected.code}</span>}
          </>
        }
        question={QUESTION}
        actions={
          <>
            <ReportExport experimentId={selectedId} />
            <ExperimentPicker experiments={experiments} value={selectedId} onChange={select} />
          </>
        }
      />

      <QueryState query={metrics}>
        {(m) =>
          !m.analyzed ? (
            <NotAnalyzed experiment={selected} />
          ) : (
            <VerdictSummary
              metrics={m}
              criteria={criteria}
              baseline={baselineCode ? { code: baselineCode, metrics: baselineMetrics } : null}
            />
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
          const allFlags = list.flatMap((r) => (latest.get(r.kind) === r ? r.flags : []));
          const quiet = (flags: AnalysisResultOut["flags"]) => flagSummary(flags) ?? "모든 기준 충족";
          const t = cmp?.recovery_t_test;
          return (
            <div className="space-y-2">
              <h2 className="px-1 pt-4 text-sm font-semibold text-ink-muted">
                판정의 근거{" "}
                <span className="font-normal text-ink-faint">— 제목을 눌러 펼치기 · 표시: ✕ 불합격 / ! 검토 필요 / ✓ 정상</span>
              </h2>
              {rec?.output.kind === "recovery" && (
                <Disclosure
                  lazy
                  title={<>회수율 · <Term k="rsd">RSD</Term> · <Term k="uncertainty">불확도</Term></>}
                  summary={quiet(rec.flags)}
                  tone={flagTone(rec.flags)}
                >
                  <RecoveryPanel result={rec} output={rec.output} criteria={criteria} />
                </Disclosure>
              )}
              {isr?.output.kind === "is_response" && (
                <Disclosure
                  lazy
                  title={<Term k="is">내부표준(IS) 응답</Term>}
                  summary={quiet(isr.flags)}
                  tone={flagTone(isr.flags)}
                >
                  <ISResponsePanel result={isr} output={isr.output} criteria={criteria} />
                </Disclosure>
              )}
              {
                <Disclosure
                  lazy
                  title={baselineCode ? <CodeText text={`기준 실험 ${baselineCode} 대비 비교`} /> : "다른 실험과 비교"}
                  summary={
                    cmp
                      ? `평균 회수율 ${formatWithUnit(cmp.recovery_delta_pct_points, "%p")}${t ? ` · Welch ${formatPValue(t.p_value)}` : ""}`
                      : undefined
                  }
                  tone={cmp?.per_analyte.some((d) => d.significant) ? "warn" : "default"}
                >
                  <ComparePanel experiments={experiments} current={selectedId} defaultBaseline={baselineId} />
                </Disclosure>
              }
              {cal?.output.kind === "calibration" && (
                <Disclosure
                  lazy
                  title={<><Term k="calibration">검량선</Term> · <Term k="residual">잔차</Term> · <Term k="weighting">가중치</Term></>}
                  summary={quiet(cal.flags)}
                  tone={flagTone(cal.flags)}
                >
                  <CalibrationPanel result={cal} output={cal.output} />
                </Disclosure>
              )}
              {lim?.output.kind === "limits" && (
                <Disclosure
                  lazy
                  title={<>검출·정량 한계 (<Term k="lod">LOD</Term>/<Term k="loq">LOQ</Term>)</>}
                  summary={quiet(lim.flags)}
                  tone={flagTone(lim.flags)}
                >
                  <LimitsPanel result={lim} output={lim.output} />
                </Disclosure>
              )}
              {me?.output.kind === "matrix_effect" && (
                <Disclosure
                  lazy
                  title={<Term k="matrixEffect">매트릭스 효과 (%ME)</Term>}
                  summary={quiet(me.flags)}
                  tone={flagTone(me.flags)}
                >
                  <MatrixEffectPanel result={me} output={me.output} criteria={criteria} />
                </Disclosure>
              )}
              {ion?.output.kind === "ion_ratio" && (
                <Disclosure lazy title={<Term k="ionRatio">이온비</Term>} summary={quiet(ion.flags)} tone={flagTone(ion.flags)}>
                  <IonRatioPanel result={ion} output={ion.output} />
                </Disclosure>
              )}
              <Disclosure title="QC 판정 상세 · 플래그 전체" summary={`플래그 ${allFlags.length}건`}>
                <Card title="QC 판정 · 플래그" subtitle="허용 기준 대비 결정론적 판정 (critical → 불합격, warning → 검토 필요)">
                  <div className="space-y-4">
                    {metrics.data && <QCVerdictTable verdicts={metrics.data.qc_verdicts} />}
                    <FlagList flags={allFlags} />
                  </div>
                </Card>
              </Disclosure>
            </div>
          );
        }}
      </QueryState>

      <Disclosure title="QC 허용 기준 · 편집 · 버전 이력" summary={criteria ? `활성 기준 ${criteria.source}` : undefined}>
        <CriteriaPanel projectId={projectId} experimentId={selectedId} />
      </Disclosure>
    </div>
  );
}
