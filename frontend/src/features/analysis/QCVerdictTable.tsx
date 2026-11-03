import { Badge, DataTable } from "@/components";
import { FLAG_LABELS, QC_STATUS } from "./labels";
import type { AnalyteVerdict } from "./types";

/** Per-analyte pass/fail derived by the backend from the flags. */
export function QCVerdictTable({ verdicts }: { verdicts: AnalyteVerdict[] }) {
  return (
    <DataTable
      rows={verdicts}
      rowKey={(v) => v.analyte}
      empty="판정할 분석물이 없습니다."
      columns={[
        { key: "a", header: "분석물", render: (v) => v.analyte },
        {
          key: "s",
          header: "판정",
          render: (v) => <Badge tone={QC_STATUS[v.status].tone}>{QC_STATUS[v.status].label}</Badge>,
        },
        {
          key: "f",
          header: "불합격 항목",
          render: (v) => v.failed_checks.map((c) => FLAG_LABELS[c]).join(", ") || "—",
        },
        {
          key: "w",
          header: "경고 항목",
          render: (v) => v.warning_checks.map((c) => FLAG_LABELS[c]).join(", ") || "—",
        },
      ]}
    />
  );
}
