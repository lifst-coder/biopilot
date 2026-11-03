import {
  useCritiques,
  useDecisionHistory,
  useHypotheses,
  useMetrics,
  usePrioritizedProposals,
  useProjectCritiques,
  useRunCritique,
  useRunProjectCritique,
} from "@/api/queries";
import { Card, EmptyState, ExperimentPicker, QueryState } from "@/components";
import { useActiveProject, useSelectedExperiment } from "@/lib/selection";
import { CriticAssessmentView } from "./CriticAssessmentView";
import { CritiqueView } from "./CritiqueView";
import { DecisionHistoryCard } from "./DecisionHistoryCard";
import { HypothesisItem } from "./HypothesisItem";
import { ProposalCard } from "./ProposalCard";

/** Pending proposals first (already priority-ranked by the backend), decided ones after. */
function pendingFirst<T extends { status: string }>(list: T[]): T[] {
  return [...list.filter((p) => p.status === "pending"), ...list.filter((p) => p.status !== "pending")];
}

/** Partner layer UI: Research Critic → Next Experiment Designer → Decision History. */
export function ResearchAIPage() {
  const { project } = useActiveProject();
  const projectId = project?.id ?? null;
  const { experiments, selected, selectedId, select } = useSelectedExperiment();
  const critiques = useCritiques(selectedId);
  const hypotheses = useHypotheses(projectId, selectedId);
  const proposals = usePrioritizedProposals(projectId, selectedId);
  const history = useDecisionHistory(projectId);
  const projectCritiques = useProjectCritiques(projectId, "project");
  const metrics = useMetrics(selectedId);
  const run = useRunCritique();
  const runProject = useRunProjectCritique();
  const codeOf = (id: number) => experiments.find((e) => e.id === id)?.code ?? `#${id}`;
  const resultIds = metrics.data?.source_result_ids ?? [];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-lg font-semibold">
          Research AI {selected && <span className="text-ink-muted">· {selected.code}</span>}
        </h1>
        <div className="flex flex-wrap items-center gap-2">
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
        </div>
      </div>
      {run.isError && <p className="text-xs text-crit">{run.error.message}</p>}

      <QueryState query={critiques}>
        {(list) => {
          const latest = list[0];
          if (!latest)
            return (
              <Card title="Research Critic">
                <EmptyState>이 실험에 대한 비판이 아직 없습니다. 실행 버튼을 누르세요.</EmptyState>
              </Card>
            );
          return (
            <>
              {latest.assessments.map((a) => (
                <CriticAssessmentView
                  key={a.id}
                  assessment={a}
                  evidence={latest.evidence}
                  feedback={latest.decision_feedback}
                />
              ))}
              <CritiqueView critique={latest} historyCount={list.length} />
            </>
          );
        }}
      </QueryState>

      <Card
        title="Next Experiment Designer"
        subtitle="우선순위 순 · 채택/수정/기각은 사유와 함께 Decision으로 기록되고 이후 제안에 반영됩니다"
      >
        <QueryState query={proposals}>
          {(list) =>
            list.length === 0 ? (
              <EmptyState>제안 없음</EmptyState>
            ) : (
              <div className="grid gap-3 xl:grid-cols-2">
                {pendingFirst(list).map((p) => (
                  <ProposalCard key={p.id} proposal={p} codeOf={codeOf} />
                ))}
              </div>
            )
          }
        </QueryState>
      </Card>

      <QueryState query={history}>{(h) => <DecisionHistoryCard entries={h.entries} />}</QueryState>

      <Card title="가설" subtitle="제안됨 → 검증 중 → 지지/반박 (전이는 사유·분석 결과와 함께 감사 기록)">
        <QueryState query={hypotheses}>
          {(list) =>
            list.length === 0 ? (
              <EmptyState>가설 없음</EmptyState>
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

      <QueryState query={projectCritiques}>
        {(list) =>
          list[0] ? <CritiqueView critique={list[0]} historyCount={list.length} title="프로젝트 수준 검토" /> : null
        }
      </QueryState>
    </div>
  );
}
