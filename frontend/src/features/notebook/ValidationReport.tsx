import { Badge, DataTable } from "@/components";
import { IssueList } from "./IssueList";
import type { DatasetValidation } from "./types";

/** Parsed preview + issues of a CSV dry-run validation (values shown exactly as parsed). */
export function ValidationReport({ report }: { report: DatasetValidation }) {
  return (
    <div className="space-y-2 rounded-md border border-border p-2">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <Badge tone={report.ok ? "ok" : "crit"}>{report.ok ? "검증 통과" : "검증 실패"}</Badge>
        <span className="font-mono">{report.filename}</span>
        <span className="text-ink-faint">
          {report.schema_ref} · {report.encoding} · {report.row_count}행 · 컬럼 {report.columns.length}개
        </span>
      </div>
      <IssueList issues={report.issues} empty="문제 없음" />
      {report.preview_rows.length > 0 && (
        <div className="max-h-56 overflow-auto">
          <DataTable
            rows={report.preview_rows}
            rowKey={(_r, i) => i}
            columns={report.columns.map((c) => ({
              key: c,
              header: c,
              render: (r: Record<string, unknown>) => (r[c] === null || r[c] === undefined ? "" : String(r[c])),
            }))}
          />
          {report.row_count > report.preview_rows.length && (
            <p className="mt-1 text-xs text-ink-faint">
              미리보기 {report.preview_rows.length}행 / 전체 {report.row_count}행
            </p>
          )}
        </div>
      )}
    </div>
  );
}
