import { useCritiques, useHypotheses, useProposals, useRunCritique } from "@/api/queries";
import { useSelectedExperiment, useActiveProject } from "@/lib/selection";
import { Badge, Card, EmptyState, ExperimentPicker, QueryState } from "@/components";
import { CritiqueView } from "./CritiqueView";
import { ProposalCard } from "./ProposalCard";

/** Partner layer UI: critique → hypotheses → proposals → researcher decisions. */
export function ResearchAIPage() {
  const { project } = useActiveProject();
  const { experiments, selected, selectedId, select } = useSelectedExperiment();
  const critiques = useCritiques(selectedId);
  const hypotheses = useHypotheses(project?.id ?? null, selectedId);
  const proposals = useProposals(project?.id ?? null, selectedId);
  const run = useRunCritique();

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-lg font-semibold">Research AI {selected && <span className="text-ink-muted">· {selected.code}</span>}</h1>
        <div className="flex items-center gap-2">
          <ExperimentPicker experiments={experiments} value={selectedId} onChange={select} />
          <button
            type="button"
            className="bp-btn-primary"
            disabled={selectedId === null || run.isPending}
            onClick={() => selectedId !== null && run.mutate(selectedId)}
          >
            {run.isPending ? "비판 중…" : "비판적 검토 실행"}
          </button>
        </div>
      </div>
      {run.isError && <p className="text-xs text-crit">{run.error.message}</p>}

      <QueryState query={critiques}>
        {(list) =>
          list[0] ? (
            <CritiqueView critique={list[0]} historyCount={list.length} />
          ) : (
            <Card title="비판적 검토">
              <EmptyState>이 실험에 대한 비판이 아직 없습니다. 실행 버튼을 누르세요.</EmptyState>
            </Card>
          )
        }
      </QueryState>

      <Card title="가설" subtitle="AI 제안(검토 전) 또는 연구자 작성">
        <QueryState query={hypotheses}>
          {(list) =>
            list.length === 0 ? (
              <EmptyState>가설 없음</EmptyState>
            ) : (
              <ul className="space-y-2">
                {list.map((h) => (
                  <li key={h.id} className="rounded-md border border-border p-3 text-xs">
                    <div className="mb-1 flex items-center gap-2">
                      <Badge tone={h.origin === "user" ? "neutral" : "ai"}>{h.origin}</Badge>
                      <Badge>{h.status}</Badge>
                      <span className="text-ink-faint">H{h.id}</span>
                    </div>
                    <p className="font-medium">{h.statement}</p>
                    {h.rationale && <p className="mt-0.5 text-ink-muted">{h.rationale}</p>}
                  </li>
                ))}
              </ul>
            )
          }
        </QueryState>
      </Card>

      <Card title="후속 실험 제안" subtitle="수락 · 수정 · 거절은 근거와 함께 Decision으로 기록됩니다">
        <QueryState query={proposals}>
          {(list) =>
            list.length === 0 ? (
              <EmptyState>제안 없음</EmptyState>
            ) : (
              <div className="grid gap-3 xl:grid-cols-2">
                {list.map((p) => (
                  <ProposalCard key={p.id} proposal={p} />
                ))}
              </div>
            )
          }
        </QueryState>
      </Card>
    </div>
  );
}
