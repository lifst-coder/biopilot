import { Bar, BarChart, CartesianGrid, Cell, ReferenceArea, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useCriteria } from "@/api/queries";
import type { AnalysisResultOut, MatrixEffectOutput } from "@/api/types";
import { Card } from "@/components";
import { TOKEN_HEX } from "@/lib/chartColors";
import { formatWithUnit } from "@/lib/format";
import { resultSubtitle } from "./ResultMeta";

interface Props {
  result: AnalysisResultOut;
  output: MatrixEffectOutput;
}

/** Slope-ratio matrix effect per analyte. */
export function MatrixEffectPanel({ result, output }: Props) {
  const { data: criteria } = useCriteria();
  const limit = criteria?.matrix_effect_abs_max_pct ?? null;
  return (
    <Card title="매트릭스 효과 (기울기 비)" subtitle={resultSubtitle(result)}>
      <div className="h-56">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={output.analytes} margin={{ top: 8, right: 16, bottom: 0, left: -8 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e0e4ea" />
            <XAxis dataKey="analyte" tick={{ fontSize: 11 }} />
            <YAxis unit="%" tick={{ fontSize: 11 }} />
            {limit !== null && <ReferenceArea y1={-limit} y2={limit} fill={TOKEN_HEX.ok} fillOpacity={0.08} ifOverflow="extendDomain" />}
            <Tooltip formatter={(v: number) => formatWithUnit(v, "%")} />
            <Bar dataKey="matrix_effect_pct" name="ME">
              {output.analytes.map((a) => (
                <Cell
                  key={a.analyte}
                  fill={limit !== null && Math.abs(a.matrix_effect_pct) > limit ? TOKEN_HEX.crit : TOKEN_HEX.brand}
                />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </Card>
  );
}
