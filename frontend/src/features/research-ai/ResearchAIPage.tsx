import {
  useCritiques,
  useDecisionHistory,
  useHypotheses,
  useMetrics,
  usePrecedents,
  usePrioritizedProposals,
  useProjectCritiques,
  useRunCritique,
  useRunProjectCritique,
} from "@/api/queries";
import { useEffect } from "react";
import { useLocation } from "react-router-dom";
import type { ExperimentSummary } from "@/api/types";
import { Badge, Card, Disclosure, EmptyState, ErrorState, ExperimentLink, ExperimentPicker, PageHeader, QueryState } from "@/components";
import { TABS } from "@/layout/tabs";
import { useActiveProject, useSelectedExperiment } from "@/lib/selection";
import { CriticAssessmentView } from "./CriticAssessmentView";
import { CritiqueView } from "./CritiqueView";
import { DecisionHistoryCard } from "./DecisionHistoryCard";
import { HypothesisItem } from "./HypothesisItem";
import { PrecedentCard } from "./PrecedentCard";
import { ProposalCard } from "./ProposalCard";

const QUESTION = TABS.find((t) => t.path === "/research-ai")?.question ?? "";

/** Pending proposals first (already priority-ranked by the backend), decided ones after. */
function pendingFirst<T extends { status: string }>(list: T[]): T[] {
  return [...list.filter((p) => p.status === "pending"), ...list.filter((p) => p.status !== "pending")];
}

/** Scroll to `#critic` / `#proposals` (guide-bar links) once the target has rendered. */
function useHashScroll(ready: boolean) {
  const { hash } = useLocation();
  useEffect(() => {
    if (!ready || !hash) return;
    document.getElementById(hash.slice(1))?.scrollIntoView({ block: "start", behavior: "smooth" });
  }, [hash, ready]);
}

/**
 * No stored critique for this experiment: say how to get one, and (since most experiments
 * have none) which experiments of this project already have one to look at.
 */
function NoCritique({
  experiment,
  analyzed,
  critiqued,
}: {
  experiment: ExperimentSummary | null;
  analyzed: boolean | null;
  critiqued: ExperimentSummary[];
}) {
  return (
    <Card title="Research Critic">
      <p className="bp-prose text-ink-muted">
        {experiment ? `${experiment.code}에 저장된 비판이 아직 없습니다` : "선택된 실험이 없습니다"} —{" "}
        {analyzed === false && experiment ? (
          <>
            비판은 저장된 분석 결과를 근거로 하므로 먼저{" "}
            <ExperimentLink id={experiment.id} projectId={experiment.project_id} tab="/analysis">
              Analysis에서 분석
            </ExperimentLink>
            하세요.
          </>
        ) : (
          "위 ‘비판적 검토 실행’을 누르면 저장된 결과를 근거로 만듭니다."
        )}
      </p>
      {critiqued.length > 0 && (
        <p className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
          <span className="text-ink-muted">비판이 저장된 실험</span>
          {critiqued.map((e) => (
            <ExperimentLink key={e.id} id={e.id} projectId={e.project_id} tab="/research-ai" title={e.title}>
              {e.code}
            </ExperimentLink>
          ))}
        </p>
      )}
    </Card>
  );
}

/**
 * Partner layer UI, ordered by practical value: precedents from the records ("과거에 같은
 * 증상이 있었고 그때 이렇게 결론 내렸다", only when there are any) → Research Critic
 * (verdict → why it cannot be settled → missing controls) → Next Experiment Designer (decide with a reason) →
 * findings, decision history, hypotheses and the project review collapsed below.
 */
export function ResearchAIPage() {
  const { project } = useActiveProject();
  const projectId = project?.id ?? null;
  const { experiments, selected, selectedId, select } = useSelectedExperiment();
  const critiques = useCritiques(selectedId);
  const hypotheses = useHypotheses(projectId, selectedId);
  const proposals = usePrioritizedProposals(projectId, selectedId);
  const history = useDecisionHistory(projectId);
  const projectCritiques = useProjectCritiques(projectId, "project");
  const experimentCritiques = useProjectCritiques(projectId, "experiment");
  const metrics = useMetrics(selectedId);
  const precedents = usePrecedents(selectedId);
  const run = useRunCritique();
  const runProject = useRunProjectCritique();
  const codeOf = (id: number) => experiments.find((e) => e.id === id)?.code ?? `#${id}`;
  const resultIds = metrics.data?.source_result_ids ?? [];
  useHashScroll(critiques.isSuccess && proposals.isSuccess);

  const latest = critiques.data?.[0];
  const pending = (proposals.data ?? []).filter((p) => p.status === "pending").length;
  const openHypotheses = (hypotheses.data ?? []).filter((h) => h.status === "proposed" || h.status === "open").length;
  const critical = latest?.findings.filter((f) => f.severity === "critical").length ?? 0;

  return (
    <div className="space-y-4">
      <PageHeader
        title={
          <>
            Research AI {selected && <span className="text-ink-muted">· {selected.code}</span>}
          </>
        }
        question={QUESTION}
        actions={
          <>
            <ExperimentPicker experiments={experiments} value={selectedId} onChange={select} />
            <button
              type="button"
              className="bp-btn-primary"
              disabled={selectedId === null || run.isPending}
              onClick={() => selectedId !== null && run.mutate(selectedId)}
            >
              {run.isPending ? "비판 중…" : "비판적 검토 실행"}
            </button>
            <button
              type="button"
              className="bp-btn-ghost"
              disabled={projectId === null || runProject.isPending}
              onClick={() => projectId !== null && runProject.mutate(projectId)}
            >
              프로젝트 수준 검토
            </button>
          </>
        }
      />
      {run.isError && <ErrorState error={run.error} />}
      {runProject.isError && <ErrorState error={runProject.error} />}

      <div id="critic" className="scroll-mt-4 space-y-4">
        {precedents.data && <PrecedentCard data={precedents.data} currentProjectId={projectId} />}
        {precedents.data &&
          precedents.data.cases.length === 0 &&
          precedents.data.condition_usage.length === 0 &&
          metrics.data?.qc_status === "fail" && (
            <p className="px-1 text-sm text-ink-muted">
              과거 사례 없음 — 모든 프로젝트에서 이 실험보다 먼저 같은 증상으로 실패한 기록을 찾지 못했습니다. 이번 판단과 사유를
              결정으로 남기면 다음 실패 때 여기에 나옵니다.
            </p>
          )}
        <QueryState query={critiques}>
          {(list) => {
            const head = list[0];
            if (!head)
              return (
                <NoCritique
                  experiment={selected}
                  analyzed={metrics.data?.analyzed ?? null}
                  critiqued={[...new Set((experimentCritiques.data ?? []).map((c) => c.experiment_id))]
                    .map((id) => experiments.find((e) => e.id === id))
                    .filter((e): e is ExperimentSummary => !!e)}
                />
              );
            return (
              <>
                {head.assessments.map((a) => (
                  <CriticAssessmentView
                    key={a.id}
                    assessment={a}
                    evidence={head.evidence}
                    feedback={head.decision_feedback}
                    proposals={proposals.data ?? []}
                  />
                ))}
              </>
            );
          }}
        </QueryState>
      </div>

      <div id="proposals" className="scroll-mt-4">
        <Card
          title="Next Experiment Designer"
          subtitle="우선순위 순 · 채택/수정/기각은 사유와 함께 Decision으로 기록되고 이후 제안에 반영됩니다"
          actions={pending > 0 ? <Badge tone="warn">결정 대기 {pending}</Badge> : undefined}
        >
          <QueryState query={proposals}>
            {(list) =>
              list.length === 0 ? (
                <EmptyState>
                  아직 제안이 없습니다 — 비판적 검토를 실행하면 누락 대조군을 채우는 다음 실험이 우선순위와 함께 제안됩니다.
                </EmptyState>
              ) : (
                <div className="grid gap-4 xl:grid-cols-2">
                  {pendingFirst(list).map((p) => (
                    <ProposalCard key={p.id} proposal={p} codeOf={codeOf} />
                  ))}
                </div>
              )
            }
          </QueryState>
        </Card>
      </div>

      <div className="space-y-2">
        <h2 className="px-1 pt-4 text-sm font-semibold text-ink-muted">자세히</h2>
        {latest && (
          <Disclosure
            title="비판적 검토 — 세부 지적"
            summary={`지적 ${latest.findings.length}건${critical ? ` · 치명 ${critical}` : ""}`}
            tone={critical ? "crit" : latest.findings.length ? "warn" : "ok"}
          >
            <CritiqueView critique={latest} historyCount={critiques.data?.length ?? 0} />
          </Disclosure>
        )}
        <QueryState query={history}>
          {(h) => (
            <Disclosure title="결정 이력" summary={`기록된 결정 ${h.entries.length}건`}>
              <DecisionHistoryCard entries={h.entries} />
            </Disclosure>
          )}
        </QueryState>
        <Disclosure
          title="가설"
          summary={hypotheses.data ? `${hypotheses.data.length}건 · 미해결 ${openHypotheses}` : undefined}
          tone={openHypotheses ? "warn" : "default"}
        >
          <Card title="가설" subtitle="제안됨 → 검증 중 → 지지/반박 (전이는 사유·분석 결과와 함께 감사 기록)">
            <QueryState query={hypotheses}>
              {(list) =>
                list.length === 0 ? (
                  <EmptyState>가설이 없습니다 — 비판적 검토가 원인 후보를 가설로 남깁니다.</EmptyState>
                ) : (
                  <ul className="space-y-2">
                    {list.map((h) => (
                      <HypothesisItem key={h.id} hypothesis={h} resultIds={resultIds} />
                    ))}
                  </ul>
                )
              }
            </QueryState>
          </Card>
        </Disclosure>
        <QueryState query={projectCritiques}>
          {(list) =>
            list[0] ? (
              <Disclosure title="프로젝트 수준 검토" summary={`지적 ${list[0].findings.length}건`}>
                <CritiqueView critique={list[0]} historyCount={list.length} title="프로젝트 수준 검토" />
              </Disclosure>
            ) : null
          }
        </QueryState>
      </div>
    </div>
  );
}
