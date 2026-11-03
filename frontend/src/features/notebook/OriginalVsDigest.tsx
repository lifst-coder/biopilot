import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useCreateDigest, useDigests, useSystemInfo } from "@/api/queries";
import { Badge, ConditionTable, EmptyState, EngineBadge, ErrorState, OriginalBadge, QueryState } from "@/components";
import { formatDateTime } from "@/lib/format";
import { AddendumSection } from "./AddendumSection";
import type { ExperimentOut } from "./types";

/**
 * Original record (left, immutable) next to the AI digest (right, separate record).
 * Regeneration creates a new digest: offline rules template by default, Claude when
 * the server has an API key (mode shown from `/api/system/info`).
 */
export function OriginalVsDigest({ exp }: { exp: ExperimentOut }) {
  const digests = useDigests(exp.id);
  const create = useCreateDigest();
  const { data: info } = useSystemInfo();
  const qc = useQueryClient();
  const [selected, setSelected] = useState<number | null>(null);

  const regenerate = () =>
    create.mutate(exp.id, {
      onSuccess: (d) => {
        setSelected(d.id);
        void qc.invalidateQueries({ queryKey: ["eln", "audit", exp.id] });
        void qc.invalidateQueries({ queryKey: ["system", "audit"] });
      },
    });

  return (
    <div className="grid gap-4 xl:grid-cols-2">
      <section className="min-w-0 rounded-card border border-border bg-surface p-4" aria-label="원본 기록">
        <header className="mb-2 flex items-center justify-between">
          <h2 className="text-sm font-semibold">원본</h2>
          <OriginalBadge />
        </header>
        <pre className="whitespace-pre-wrap rounded-md bg-subtle p-3 font-sans text-xs leading-relaxed">{exp.raw_note}</pre>
        <h3 className="mb-1 mt-3 text-xs font-semibold text-ink-muted">조건 블록</h3>
        <ConditionTable block={exp.condition_block} />
        <AddendumSection exp={exp} />
      </section>

      <section className="min-w-0 rounded-card border border-ai/30 bg-surface p-4" aria-label="AI 정리본">
        <header className="mb-2 flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-sm font-semibold">AI 정리본</h2>
          <div className="flex items-center gap-2">
            {info && <Badge tone="ai">{info.ai_mode === "claude" ? `Claude 모드 (${info.claude_model ?? ""})` : "오프라인 템플릿 모드"}</Badge>}
            <button type="button" className="bp-btn-ghost px-2 py-1 text-xs" disabled={create.isPending} onClick={regenerate}>
              {create.isPending ? "생성 중…" : "정리본 재생성"}
            </button>
          </div>
        </header>
        {create.error && <ErrorState error={create.error} />}
        <QueryState query={digests}>
          {(list) => {
            if (list.length === 0) return <EmptyState>정리본 없음 — “정리본 재생성”으로 만드세요.</EmptyState>;
            const current = list.find((d) => d.id === selected) ?? list[0]!;
            return (
              <div className="space-y-2">
                <div className="flex flex-wrap items-center gap-2">
                  <EngineBadge engine={current.engine} model={current.model} />
                  <span className="text-[11px] text-ink-faint">{formatDateTime(current.created_at)}</span>
                  {list.length > 1 && (
                    <select
                      aria-label="정리본 버전"
                      className="bp-input ml-auto w-auto py-0.5 text-xs"
                      value={current.id}
                      onChange={(e) => setSelected(Number(e.target.value))}
                    >
                      {list.map((d, i) => (
                        <option key={d.id} value={d.id}>
                          {i === 0 ? "최신" : `이전 ${i}`} · {d.engine} · {formatDateTime(d.created_at)}
                        </option>
                      ))}
                    </select>
                  )}
                </div>
                <p className="rounded-md bg-ai-soft/40 p-3 text-xs leading-relaxed">{current.summary}</p>
                {current.key_points.length > 0 && (
                  <ul className="list-disc space-y-0.5 pl-4 text-xs text-ink-muted">
                    {current.key_points.map((k) => (
                      <li key={k}>{k}</li>
                    ))}
                  </ul>
                )}
                <p className="text-[11px] text-ink-faint">정리본은 원본과 분리된 불변 레코드입니다. 재생성해도 이전 정리본은 남습니다.</p>
              </div>
            );
          }}
        </QueryState>
      </section>
    </div>
  );
}
