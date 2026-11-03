import { Bar, BarChart, CartesianGrid, Cell, ReferenceArea, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { AnalysisResultOut } from "@/api/types";
import { Card, DataTable, FlagMark, Term } from "@/components";
import { CHART_FONT_SIZE, TOKEN_HEX } from "@/lib/chartColors";
import { formatNumber, formatWithUnit } from "@/lib/format";
import { MethodNotes } from "./MethodNotes";
import { resultSubtitle } from "./ResultMeta";
import type { AcceptanceCriteria, MatrixEffectOutput } from "./types";

interface Props {
  result: AnalysisResultOut;
  output: MatrixEffectOutput;
  criteria?: AcceptanceCriteria;
}

/** Slope-ratio matrix effect per analyte; flagged bars come from the stored flags. */
export function MatrixEffectPanel({ result, output, criteria }: Props) {
  const limit = criteria?.matrix_effect_abs_max_pct ?? null;
  const flagged = new Set(result.flags.map((f) => f.analyte));
  return (
    <Card title="매트릭스 효과 (기울기 비)" subtitle={resultSubtitle(result)}>
      <div className="grid gap-4 xl:grid-cols-2">
        <div className="h-56">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={output.analytes} margin={{ top: 8, right: 16, bottom: 0, left: -8 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e0e4ea" />
              <XAxis dataKey="analyte" tick={{ fontSize: CHART_FONT_SIZE }} />
              <YAxis unit="%" tick={{ fontSize: CHART_FONT_SIZE }} />
              {limit !== null && <ReferenceArea y1={-limit} y2={limit} fill={TOKEN_HEX.ok} fillOpacity={0.08} ifOverflow="extendDomain" />}
              <Tooltip formatter={(v: number) => formatWithUnit(v, "%")} />
              <Bar dataKey="matrix_effect_pct" name="ME">
                {output.analytes.map((a) => (
                  <Cell key={a.analyte} fill={flagged.has(a.analyte) ? TOKEN_HEX.crit : TOKEN_HEX.brand} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
        <DataTable
          rows={output.analytes}
          rowKey={(a) => a.analyte}
          rowClassName={(a) => (flagged.has(a.analyte) ? "bg-crit-soft/60" : undefined)}
          columns={[
            { key: "a", header: "분석물", render: (a) => a.analyte },
            { key: "s", header: "기울기 (용매)", align: "right", render: (a) => formatNumber(a.slope_solvent, 0) },
            { key: "m", header: "기울기 (매트릭스)", align: "right", render: (a) => formatNumber(a.slope_matrix, 0) },
            { key: "me", header: <Term k="matrixEffect">%ME</Term>, align: "right", render: (a) => (
                <>
                  {flagged.has(a.analyte) && <FlagMark tone="crit" label="기준 초과" />}
                  {formatWithUnit(a.matrix_effect_pct, "%")}
                </>
              ),
            },
          ]}
        />
      </div>
      <MethodNotes method={output.method} />
    </Card>
  );
}
