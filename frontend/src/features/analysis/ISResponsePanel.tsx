import { Bar, BarChart, CartesianGrid, Cell, ReferenceArea, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useCriteria } from "@/api/queries";
import type { AnalysisResultOut, ISResponseOutput } from "@/api/types";
import { Card } from "@/components";
import { TOKEN_HEX } from "@/lib/chartColors";
import { formatNumber, formatWithUnit } from "@/lib/format";
import { resultSubtitle } from "./ResultMeta";

interface Props {
  result: AnalysisResultOut;
  output: ISResponseOutput;
}

/** IS area per injection as % of the calibration mean (computed in the backend). */
export function ISResponsePanel({ result, output }: Props) {
  const { data: criteria } = useCriteria();
  return (
    <Card
      title={`내부표준 응답 — 이탈 ${output.flagged_count}/${output.injections.length}`}
      subtitle={`${resultSubtitle(result)} · 기준 IS 면적 ${formatNumber(output.reference_is_area, 0)}`}
    >
      <div className="h-56">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={output.injections} margin={{ top: 8, right: 16, bottom: 0, left: -8 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e0e4ea" />
            <XAxis dataKey="injection_id" tick={{ fontSize: 11 }} />
            <YAxis unit="%" tick={{ fontSize: 11 }} />
            {criteria && (
              <ReferenceArea y1={criteria.is_response_min_pct} y2={criteria.is_response_max_pct} fill={TOKEN_HEX.ok} fillOpacity={0.08} ifOverflow="extendDomain" />
            )}
            <Tooltip formatter={(v: number) => formatWithUnit(v, "%")} />
            <Bar dataKey="response_pct" name="IS 응답">
              {output.injections.map((inj) => (
                <Cell key={inj.injection_id} fill={inj.flagged ? TOKEN_HEX.crit : TOKEN_HEX.brand} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </Card>
  );
}
