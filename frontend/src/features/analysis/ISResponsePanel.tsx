import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { AnalysisResultOut } from "@/api/types";
import { Card, DataTable } from "@/components";
import { CHART_FONT_SIZE, TOKEN_HEX } from "@/lib/chartColors";
import { formatNumber, formatWithUnit } from "@/lib/format";
import { MethodNotes } from "./MethodNotes";
import { resultSubtitle } from "./ResultMeta";
import type { AcceptanceCriteria, ISInjectionOut, ISResponseOutput } from "./types";

interface Props {
  result: AnalysisResultOut;
  output: ISResponseOutput;
  criteria?: AcceptanceCriteria;
}

interface DotProps {
  cx?: number;
  cy?: number;
  payload?: ISInjectionOut;
}

function InjectionDot({ cx, cy, payload }: DotProps) {
  if (cx === undefined || cy === undefined || !payload) return null;
  const color = payload.flagged ? TOKEN_HEX.crit : payload.role === "calibration" ? TOKEN_HEX.faint : TOKEN_HEX.brand;
  return <circle cx={cx} cy={cy} r={payload.flagged ? 5 : 3.5} fill={color} stroke="white" strokeWidth={1} />;
}

/** IS response trend over the run order (standards then samples) with the acceptance band. */
export function ISResponsePanel({ result, output, criteria }: Props) {
  const sequence = [...output.calibration_injections, ...output.injections];
  const flagged = output.injections.filter((i) => i.flagged);
  const firstSample = output.injections[0]?.injection_id;
  return (
    <Card
      title={`내부표준 응답 추세 — 이탈 ${output.flagged_count}/${output.injections.length} 시료 주입`}
      subtitle={`${resultSubtitle(result)} · 기준 IS 면적 ${formatNumber(output.reference_is_area, 0)} (RSD ${formatWithUnit(output.reference_is_rsd_pct, "%")})`}
    >
      <div className="h-60">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={sequence} margin={{ top: 8, right: 16, bottom: 0, left: -8 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e0e4ea" />
            <XAxis dataKey="injection_id" tick={{ fontSize: CHART_FONT_SIZE }} interval="preserveStartEnd" />
            <YAxis unit="%" tick={{ fontSize: CHART_FONT_SIZE }} />
            {criteria && (
              <ReferenceArea y1={criteria.is_response_min_pct} y2={criteria.is_response_max_pct} fill={TOKEN_HEX.ok} fillOpacity={0.08} ifOverflow="extendDomain" />
            )}
            <ReferenceLine y={100} stroke={TOKEN_HEX.faint} strokeDasharray="4 4" />
            {firstSample && output.calibration_injections.length > 0 && (
              <ReferenceLine x={firstSample} stroke={TOKEN_HEX.faint} label={{ value: "시료", fontSize: CHART_FONT_SIZE, position: "insideTopLeft" }} />
            )}
            <Tooltip
              formatter={(v: number) => formatWithUnit(v, "%")}
              labelFormatter={(id: string) => {
                const inj = sequence.find((s) => s.injection_id === id);
                return inj ? `${id} · ${inj.sample_id}` : id;
              }}
            />
            <Line dataKey="response_pct" name="IS 응답" stroke={TOKEN_HEX.brand} strokeWidth={1.5} dot={<InjectionDot />} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
      {flagged.length > 0 && (
        <div className="mt-3">
          <h3 className="mb-2 text-sm font-medium text-crit">✕ 기준 이탈 주입</h3>
          <DataTable
            rows={flagged}
            rowKey={(i) => i.injection_id}
            columns={[
              { key: "i", header: "주입", render: (i) => i.injection_id },
              { key: "s", header: "시료", render: (i) => i.sample_id },
              { key: "a", header: "IS 면적", align: "right", render: (i) => formatNumber(i.is_area, 0) },
              { key: "r", header: "응답", align: "right", render: (i) => formatWithUnit(i.response_pct, "%") },
            ]}
          />
        </div>
      )}
      <MethodNotes method={output.method} />
    </Card>
  );
}
