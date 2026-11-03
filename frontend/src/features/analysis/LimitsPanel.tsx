import type { AnalysisResultOut } from "@/api/types";
import { Card, DataTable } from "@/components";
import { formatNumber } from "@/lib/format";
import { LIMIT_METHOD_LABELS } from "./labels";
import { MethodNotes } from "./MethodNotes";
import { resultSubtitle } from "./ResultMeta";
import type { LimitsOutput } from "./types";

interface Props {
  result: AnalysisResultOut;
  output: LimitsOutput;
}

/** LOD/LOQ per analyte (reported estimate + every σ estimate the data supports). */
export function LimitsPanel({ result, output }: Props) {
  const estimates = output.analytes.flatMap((a) =>
    a.estimates.map((e) => ({ analyte: a.analyte, primary: e.method === a.primary_method, ...e })),
  );
  return (
    <Card
      title={`검출·정량한계 (LOD = ${output.k_lod}·σ/b, LOQ = ${output.k_loq}·σ/b)`}
      subtitle={resultSubtitle(result)}
    >
      <DataTable
        rows={output.analytes}
        rowKey={(a) => a.analyte}
        columns={[
          { key: "a", header: "분석물", render: (a) => a.analyte },
          { key: "m", header: "대표 방법", render: (a) => LIMIT_METHOD_LABELS[a.primary_method] ?? a.primary_method },
          { key: "lod", header: `LOD (${output.unit})`, align: "right", render: (a) => formatNumber(a.lod, 3) },
          { key: "loq", header: `LOQ (${output.unit})`, align: "right", render: (a) => formatNumber(a.loq, 3) },
          { key: "lodg", header: "LOD (ng/g)", align: "right", render: (a) => formatNumber(a.lod_ng_g, 3) },
          { key: "loqg", header: "LOQ (ng/g)", align: "right", render: (a) => formatNumber(a.loq_ng_g, 3) },
          { key: "low", header: "최저 검량 수준", align: "right", render: (a) => formatNumber(a.lowest_level, 1) },
        ]}
      />
      <details className="mt-3 text-xs">
        <summary className="cursor-pointer text-ink-muted">σ 추정 방법별 값</summary>
        <DataTable
          rows={estimates}
          rowKey={(e) => `${e.analyte}-${e.method}`}
          rowClassName={(e) => (e.primary ? "font-medium" : undefined)}
          columns={[
            { key: "a", header: "분석물", render: (e) => e.analyte },
            { key: "m", header: "방법", render: (e) => LIMIT_METHOD_LABELS[e.method] ?? e.method },
            { key: "s", header: "σ", align: "right", render: (e) => e.sigma.toExponential(3) },
            { key: "b", header: "b", align: "right", render: (e) => e.slope.toExponential(4) },
            { key: "n", header: "n", align: "right", render: (e) => e.n },
            { key: "x", header: "사용 최고 수준", align: "right", render: (e) => formatNumber(e.max_level, 1) },
            { key: "lod", header: "LOD", align: "right", render: (e) => formatNumber(e.lod, 3) },
            { key: "loq", header: "LOQ", align: "right", render: (e) => formatNumber(e.loq, 3) },
          ]}
        />
      </details>
      <MethodNotes method={output.method} />
    </Card>
  );
}
