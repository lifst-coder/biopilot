import clsx from "clsx";
import { useState } from "react";
import { useCreateDigest, useDatasets, useDigests, useExperiment } from "@/api/queries";
import {
  Badge,
  Card,
  ConditionTable,
  EngineBadge,
  EmptyState,
  OriginalBadge,
  QueryState,
} from "@/components";
import { formatDate, formatDateTime } from "@/lib/format";
import { useSelectedExperiment } from "@/lib/selection";
import { DatasetPreviewTable } from "./DatasetPreviewTable";
import { ExperimentDiffView } from "./ExperimentDiffView";

/** ELN view: immutable originals, AI digests (separate records) and experiment diff. */
export function NotebookPage() {
  const { experiments, selected, selectedId, select } = useSelectedExperiment();
  const experiment = useExperiment(selectedId);
  const datasets = useDatasets(selectedId);
  const digests = useDigests(selectedId);
  const createDigest = useCreateDigest();
  const [datasetId, setDatasetId] = useState<number | null>(null);

  return (
    <div className="grid gap-4 lg:grid-cols-[16rem_1fr]">
      <Card title="실험 목록" className="h-fit">
        <ul className="space-y-1">
          {experiments.map((e) => (
            <li key={e.id}>
              <button
                type="button"
                onClick={() => {
                  select(e.id);
                  setDatasetId(null);
                }}
                className={clsx(
                  "w-full rounded-md px-2 py-1.5 text-left text-xs",
                  e.id === selected?.id ? "bg-brand-soft text-brand-strong" : "hover:bg-subtle",
                )}
              >
                <div className="font-medium">{e.code}</div>
                <div className="truncate text-ink-muted">{e.title}</div>
              </button>
            </li>
          ))}
        </ul>
      </Card>

      <div className="min-w-0 space-y-4">
        <QueryState query={experiment}>
          {(exp) => (
            <>
              <Card
                title={`${exp.code} · ${exp.title}`}
                subtitle={`${formatDate(exp.performed_on)} · ${exp.author || "작성자 미기재"}${
                  exp.parent_experiment_id
                    ? ` · 부모 ${experiments.find((e) => e.id === exp.parent_experiment_id)?.code ?? ""}`
                    : ""
                }`}
                actions={<OriginalBadge />}
              >
                <div className="grid gap-4 xl:grid-cols-[1fr_20rem]">
                  <div>
                    <h3 className="mb-1 text-xs font-semibold text-ink-muted">원본 메모</h3>
                    <pre className="whitespace-pre-wrap rounded-md bg-subtle p-3 font-sans text-xs leading-relaxed">
                      {exp.raw_note}
                    </pre>
                  </div>
                  <div>
                    <h3 className="mb-1 text-xs font-semibold text-ink-muted">조건 블록</h3>
                    <ConditionTable block={exp.condition_block} />
                    {exp.attachments.length > 0 && (
                      <>
                        <h3 className="mb-1 mt-3 text-xs font-semibold text-ink-muted">첨부</h3>
                        <ul className="space-y-0.5 text-xs">
                          {exp.attachments.map((a) => (
                            <li key={a.name}>
                              <span className="font-mono">{a.name}</span>{" "}
                              <span className="text-ink-faint">{a.description}</span>
                            </li>
                          ))}
                        </ul>
                      </>
                    )}
                  </div>
                </div>
              </Card>

              <Card title="데이터셋 (CSV)" subtitle="업로드 원본 · sha256으로 식별" actions={<OriginalBadge />}>
                <QueryState query={datasets}>
                  {(list) =>
                    list.length === 0 ? (
                      <EmptyState>데이터셋 없음</EmptyState>
                    ) : (
                      <div className="space-y-3">
                        <div className="flex flex-wrap gap-2">
                          {list.map((d) => (
                            <button
                              key={d.id}
                              type="button"
                              onClick={() => setDatasetId(d.id)}
                              className={clsx(
                                "rounded-md border px-2 py-1 text-xs",
                                datasetId === d.id ? "border-brand bg-brand-soft" : "border-border",
                              )}
                            >
                              <Badge tone="brand">{d.kind}</Badge> <span className="font-mono">{d.filename}</span>{" "}
                              <span className="text-ink-faint">{d.row_count}행</span>
                            </button>
                          ))}
                        </div>
                        {datasetId !== null && <DatasetPreviewTable datasetId={datasetId} />}
                      </div>
                    )
                  }
                </QueryState>
              </Card>

              <Card
                title="AI 정리본"
                subtitle="원본과 분리된 별도 레코드"
                actions={
                  <button
                    type="button"
                    className="bp-btn-ghost"
                    disabled={createDigest.isPending}
                    onClick={() => createDigest.mutate(exp.id)}
                  >
                    새 정리본 생성
                  </button>
                }
              >
                <QueryState query={digests}>
                  {(list) =>
                    list.length === 0 ? (
                      <EmptyState>정리본 없음</EmptyState>
                    ) : (
                      <ul className="space-y-3">
                        {list.map((d) => (
                          <li key={d.id} className="rounded-md border border-ai/20 bg-ai-soft/40 p-3">
                            <div className="mb-1 flex items-center gap-2">
                              <EngineBadge engine={d.engine} model={d.model} />
                              <span className="text-[11px] text-ink-faint">{formatDateTime(d.created_at)}</span>
                            </div>
                            <p className="text-xs">{d.summary}</p>
                            {d.key_points.length > 0 && (
                              <ul className="mt-1 list-disc pl-4 text-xs text-ink-muted">
                                {d.key_points.map((k) => (
                                  <li key={k}>{k}</li>
                                ))}
                              </ul>
                            )}
                          </li>
                        ))}
                      </ul>
                    )
                  }
                </QueryState>
              </Card>

              <ExperimentDiffView
                experiments={experiments}
                current={exp.id}
                defaultBaseline={exp.parent_experiment_id ?? null}
              />
            </>
          )}
        </QueryState>
      </div>
    </div>
  );
}
