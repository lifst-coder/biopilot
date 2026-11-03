import { useState } from "react";
import {
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Scatter,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { AnalysisResultOut, CalibrationOutput } from "@/api/types";
import { Card, DataTable } from "@/components";
import { TOKEN_HEX } from "@/lib/chartColors";
import { formatNumber, formatWithUnit } from "@/lib/format";
import { resultSubtitle } from "./ResultMeta";

interface Props {
  result: AnalysisResultOut;
  output: CalibrationOutput;
}

/** Calibration points + backend-computed fit line, back-calculation and weighting comparison. */
export function CalibrationPanel({ result, output }: Props) {
  const [analyte, setAnalyte] = useState(output.analytes[0]?.analyte ?? "");
  const current = output.analytes.find((a) => a.analyte === analyte) ?? output.analytes[0];
  if (!current) return null;
  return (
    <Card
      title={`검량선 (가중 ${output.weighting})`}
      subtitle={resultSubtitle(result)}
      actions={
        <select className="bp-input w-auto py-1 text-xs" value={current.analyte} onChange={(e) => setAnalyte(e.target.value)}>
          {output.analytes.map((a) => (
            <option key={a.analyte}>{a.analyte}</option>
          ))}
        </select>
      }
    >
      <div className="grid gap-4 xl:grid-cols-2">
        <div className="h-64">
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e0e4ea" />
              <XAxis dataKey="level" type="number" name="농도" unit=" ng/mL" tick={{ fontSize: 11 }} />
              <YAxis dataKey="response_ratio" type="number" name="면적비" tick={{ fontSize: 11 }} />
              <Tooltip />
              <Scatter data={current.points} fill={TOKEN_HEX.brand} name="측정" />
              <Line data={current.fit_line} dataKey="response_ratio" stroke={TOKEN_HEX.warn} dot={false} name="적합선" />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
        <div className="space-y-3">
          <dl className="grid grid-cols-3 gap-2 text-xs">
            <div><dt className="text-ink-muted">기울기</dt><dd className="font-mono">{current.slope.toExponential(4)}</dd></div>
            <div><dt className="text-ink-muted">절편</dt><dd className="font-mono">{current.intercept.toExponential(3)}</dd></div>
            <div><dt className="text-ink-muted">R²</dt><dd className="font-mono">{formatNumber(current.r_squared, 5)}</dd></div>
          </dl>
          <DataTable
            rows={current.back_calc}
            rowKey={(b) => b.level}
            columns={[
              { key: "lv", header: "수준 (ng/mL)", align: "right", render: (b) => formatNumber(b.level, 1) },
              { key: "bc", header: "역산 평균", align: "right", render: (b) => formatNumber(b.mean_back_calculated, 2) },
              { key: "acc", header: "정확도", align: "right", render: (b) => formatWithUnit(b.accuracy_pct, "%") },
            ]}
          />
          <DataTable
            rows={output.weighting_comparison}
            rowKey={(w) => w.weighting}
            columns={[
              { key: "w", header: "가중", render: (w) => (w.weighting === output.weighting ? <b>{w.weighting}</b> : w.weighting) },
              { key: "e", header: "Σ|%RE| (전 분석물)", align: "right", render: (w) => formatWithUnit(w.sum_abs_relative_error_pct, "%") },
            ]}
          />
        </div>
      </div>
    </Card>
  );
}
