import { useDatasetPreview } from "@/api/queries";
import { DataTable, QueryState } from "@/components";

/** Raw CSV rows exactly as stored (first N rows). */
export function DatasetPreviewTable({ datasetId }: { datasetId: number }) {
  const preview = useDatasetPreview(datasetId, 20);
  return (
    <QueryState query={preview}>
      {(p) => (
        <>
          <DataTable
            rows={p.rows}
            rowKey={(_r, i) => i}
            columns={p.dataset.columns.map((c) => ({
              key: c,
              header: c,
              render: (r: Record<string, unknown>) => String(r[c] ?? ""),
            }))}
          />
          {p.truncated && (
            <p className="mt-1 text-xs text-ink-faint">
              전체 {p.dataset.row_count}행 중 {p.rows.length}행 표시 · sha256 {p.dataset.sha256.slice(0, 12)}…
            </p>
          )}
        </>
      )}
    </QueryState>
  );
}
