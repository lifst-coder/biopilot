import clsx from "clsx";
import { useState } from "react";
import { useDatasets } from "@/api/queries";
import { Badge, Card, EmptyState, OriginalBadge, QueryState } from "@/components";
import { formatDateTime } from "@/lib/format";
import { DatasetPreviewTable } from "./DatasetPreviewTable";
import { DatasetUploadPanel } from "./DatasetUploadPanel";
import { Modal } from "./Modal";
import type { DatasetOut } from "./types";

/** Stored CSV datasets: preview, upload, instrument import and re-upload (supersede). */
export function DatasetsPanel({ experimentId }: { experimentId: number }) {
  const datasets = useDatasets(experimentId);
  const [selected, setSelected] = useState<number | null>(null);
  const [uploading, setUploading] = useState<{ supersedes: DatasetOut | null } | null>(null);

  return (
    <Card
      title="데이터셋 (CSV)"
      subtitle="업로드 원본 · sha256으로 식별 · 재업로드는 새 버전으로 기록"
      actions={
        <>
          <OriginalBadge />
          <button type="button" className="bp-btn-ghost px-2 py-1 text-xs" onClick={() => setUploading({ supersedes: null })}>
            CSV 업로드
          </button>
        </>
      }
    >
      <QueryState query={datasets}>
        {(list) =>
          list.length === 0 ? (
            <EmptyState>데이터셋 없음</EmptyState>
          ) : (
            <div className="space-y-3">
              <ul className="space-y-1">
                {list.map((d) => (
                  <li
                    key={d.id}
                    className={clsx(
                      "flex flex-wrap items-center gap-2 rounded-md border px-2 py-1 text-xs",
                      selected === d.id ? "border-brand bg-brand-soft" : "border-border",
                      d.superseded_by_dataset_id && "opacity-60",
                    )}
                  >
                    <button type="button" className="flex flex-1 flex-wrap items-center gap-2 text-left" onClick={() => setSelected(d.id)}>
                      <Badge tone="brand">{d.schema_ref || d.kind}</Badge>
                      <span className="font-mono">{d.filename}</span>
                      <span className="text-ink-faint">
                        {d.row_count}행 · {d.source_encoding} · {formatDateTime(d.created_at)}
                      </span>
                      {d.supersedes_dataset_id && <Badge tone="warn">#{d.supersedes_dataset_id} 대체</Badge>}
                      {d.superseded_by_dataset_id && <Badge tone="neutral">#{d.superseded_by_dataset_id}로 대체됨</Badge>}
                      {d.source_attachment_id && <Badge tone="neutral">장비 원본 보관</Badge>}
                    </button>
                    {!d.superseded_by_dataset_id && (
                      <button
                        type="button"
                        className="bp-btn-ghost px-2 py-0.5 text-xs"
                        onClick={() => setUploading({ supersedes: d })}
                      >
                        재업로드
                      </button>
                    )}
                  </li>
                ))}
              </ul>
              {selected !== null && <DatasetPreviewTable datasetId={selected} />}
            </div>
          )
        }
      </QueryState>
      {uploading && (
        <Modal
          title={uploading.supersedes ? "데이터셋 재업로드" : "데이터셋 업로드"}
          onClose={() => setUploading(null)}
          wide
        >
          <DatasetUploadPanel
            experimentId={experimentId}
            supersedes={uploading.supersedes}
            onDone={(d) => {
              setUploading(null);
              setSelected(d.id);
            }}
          />
        </Modal>
      )}
    </Card>
  );
}
