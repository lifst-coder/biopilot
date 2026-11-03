import type { AnalysisResultOut } from "@/api/types";
import { Card, DataTable, FlagMark } from "@/components";
import { formatNumber, formatWithUnit } from "@/lib/format";
import { MethodNotes } from "./MethodNotes";
import { resultSubtitle } from "./ResultMeta";
import type { IonRatioOutput } from "./types";

interface Props {
  result: AnalysisResultOut;
  output: IonRatioOutput;
}

/** Qualifier/quantifier ion ratios vs the standards' reference (±tolerance). */
export function IonRatioPanel({ result, output }: Props) {
  return (
    <Card
      title={`이온비 — 허용 ±${formatNumber(output.tolerance_pct, 0)}% · 이탈 ${output.flagged_count}/${output.rows.length}`}
      subtitle={resultSubtitle(result)}
    >
      <DataTable
        rows={output.rows}
        rowKey={(r) => `${r.injection_id}-${r.analyte}`}
        rowClassName={(r) => (r.flagged ? "bg-crit-soft/60" : undefined)}
        columns={[
          { key: "i", header: "주입", render: (r) => r.injection_id },
          { key: "a", header: "분석물", render: (r) => r.analyte },
          { key: "r", header: "이온비", align: "right", render: (r) => formatNumber(r.ion_ratio, 4) },
          { key: "ref", header: "기준", align: "right", render: (r) => formatNumber(r.reference_ratio, 4) },
          {
            key: "d",
            header: "편차",
            align: "right",
            render: (r) => (
              <>
                {r.flagged && <FlagMark tone="crit" label="허용 범위 밖" />}
                {formatWithUnit(r.deviation_pct, "%")}
              </>
            ),
          },
        ]}
      />
      <MethodNotes method={output.method} />
    </Card>
  );
}
