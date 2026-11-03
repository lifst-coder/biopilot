import clsx from "clsx";
import { useState } from "react";
import { useExperimentAudit, useExperimentHistory } from "@/api/queries";
import { Badge, Card, DataTable, QueryState } from "@/components";
import { formatDateTime } from "@/lib/format";
import type { AuditEventOut, HistoryEntry } from "./types";

const KIND_LABEL: Record<HistoryEntry["kind"], string> = {
  created: "생성",
  metadata: "메타데이터",
  addendum: "보충 기록",
  dataset: "데이터셋",
  attachment: "첨부",
};

const MODULES = ["전체", "eln", "memory", "analysis", "partner"] as const;

/** Version history (revisions + additions) and the experiment-scoped audit log viewer. */
export function HistoryPanel({ experimentId }: { experimentId: number }) {
  const [tab, setTab] = useState<"history" | "audit">("history");
  return (
    <Card
      title="버전 이력 · 감사 로그"
      subtitle="원본은 바뀌지 않습니다 — 모든 변경은 새 레코드와 감사 이벤트로 남습니다"
      actions={
        <div role="tablist" className="flex gap-1">
          {(["history", "audit"] as const).map((t) => (
            <button
              key={t}
              type="button"
              role="tab"
              aria-selected={tab === t}
              className={tab === t ? "bp-btn-primary px-2 py-1 text-xs" : "bp-btn-ghost px-2 py-1 text-xs"}
              onClick={() => setTab(t)}
            >
              {t === "history" ? "버전 이력" : "감사 로그"}
            </button>
          ))}
        </div>
      }
    >
      {tab === "history" ? <VersionHistory experimentId={experimentId} /> : <AuditLogViewer experimentId={experimentId} />}
    </Card>
  );
}

function VersionHistory({ experimentId }: { experimentId: number }) {
  const history = useExperimentHistory(experimentId);
  return (
    <QueryState query={history}>
      {(h) => (
        <ol className="relative space-y-3 border-l border-border pl-4" aria-label="버전 이력">
          {h.entries.map((e) => (
            <li key={`${e.ref_type}-${e.ref_id}`} className="text-sm">
              <span
                className={clsx(
                  "absolute -left-[5px] mt-1 h-2.5 w-2.5 rounded-full",
                  e.kind === "metadata" ? "bg-warn" : e.kind === "created" ? "bg-brand" : "bg-ink-faint",
                )}
              />
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone={e.kind === "metadata" ? "warn" : "neutral"}>{KIND_LABEL[e.kind]}</Badge>
                <span className="font-medium">v{e.revision}</span>
                <span className="text-ink-faint">{formatDateTime(e.occurred_at)}</span>
              </div>
              <p className="mt-0.5">{e.summary}</p>
              {e.kind === "metadata" &&
                Object.entries(e.changes ?? {}).map(([field, change]) => (
                  <p key={field} className="text-ink-muted">
                    {field}: <span className="line-through">{String(change.before ?? "")}</span> →{" "}
                    <span className="font-medium text-ink">{String(change.after ?? "")}</span>
                  </p>
                ))}
              {e.kind === "created" && (
                <p className="text-ink-muted">
                  제목 “{e.title}” · 작성자 {e.author || "미기재"}
                </p>
              )}
            </li>
          ))}
          <li className="text-xs text-ink-faint">현재 메타데이터 버전 v{h.current_revision}</li>
        </ol>
      )}
    </QueryState>
  );
}

/** Audit events of this experiment and everything derived from it (all modules). */
export function AuditLogViewer({ experimentId }: { experimentId: number }) {
  const audit = useExperimentAudit(experimentId);
  const [module, setModule] = useState<(typeof MODULES)[number]>("전체");
  const [open, setOpen] = useState<number | null>(null);
  return (
    <QueryState query={audit}>
      {(events) => {
        const rows = module === "전체" ? events : events.filter((e) => e.entity_type.startsWith(`${module}.`));
        return (
          <div className="space-y-2">
            <label className="flex items-center gap-2 text-xs text-ink-muted">
              모듈
              <select
                aria-label="감사 로그 모듈 필터"
                className="bp-input w-auto py-1 text-xs"
                value={module}
                onChange={(e) => setModule(e.target.value as (typeof MODULES)[number])}
              >
                {MODULES.map((m) => (
                  <option key={m} value={m}>
                    {m}
                  </option>
                ))}
              </select>
              <span className="text-ink-faint">{rows.length}건</span>
            </label>
            <DataTable<AuditEventOut>
              rows={rows}
              rowKey={(e) => e.id}
              empty="감사 이벤트 없음"
              onRowClick={(e) => setOpen(open === e.id ? null : e.id)}
              columns={[
                { key: "t", header: "시각", render: (e) => formatDateTime(e.occurred_at) },
                { key: "actor", header: "주체", render: (e) => <Badge tone={e.actor.startsWith("ai:") ? "ai" : "neutral"}>{e.actor}</Badge> },
                { key: "action", header: "동작", render: (e) => <span className="font-mono">{e.action}</span> },
                { key: "entity", header: "대상", render: (e) => <span className="font-mono">{e.entity_type} #{e.entity_id}</span> },
                {
                  key: "payload",
                  header: "내용",
                  render: (e) =>
                    open === e.id ? (
                      <pre className="max-w-md whitespace-pre-wrap break-all font-mono text-xs">{JSON.stringify(e.payload, null, 2)}</pre>
                    ) : (
                      <span className="text-ink-faint">{Object.keys(e.payload).slice(0, 4).join(", ")} ▸</span>
                    ),
                },
              ]}
            />
          </div>
        );
      }}
    </QueryState>
  );
}
