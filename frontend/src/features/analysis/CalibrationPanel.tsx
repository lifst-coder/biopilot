import { useState } from "react";
import {
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { AnalysisResultOut } from "@/api/types";
import { Badge, Card, DataTable } from "@/components";
import { CHART_FONT_SIZE, seriesColor, TOKEN_HEX } from "@/lib/chartColors";
import { formatNumber, formatPValue, formatWithUnit } from "@/lib/format";
import { WEIGHTING_LABELS } from "./labels";
import { MethodNotes } from "./MethodNotes";
import { resultSubtitle } from "./ResultMeta";
import type { AnalyteCalibrationOut, CalibrationFitOut, CalibrationOutput, Weighting } from "./types";

interface Props {
  result: AnalysisResultOut;
  output: CalibrationOutput;
}

type ResidualMode = "re" | "std";

const WEIGHTINGS: Weighting[] = ["none", "1/x", "1/x2"];

/** The stored fit for a weighting; old results without `fits` fall back to the reported one. */
function fitFor(analyte: AnalyteCalibrationOut, weighting: Weighting): CalibrationFitOut | null {
  const found = analyte.fits.find((f) => f.weighting === weighting);
  if (found) return found;
  if (weighting !== analyte.weighting) return null;
  return {
    weighting: analyte.weighting,
    slope: analyte.slope,
    intercept: analyte.intercept,
    r_squared: analyte.r_squared,
    residual_sd: analyte.residual_sd ?? null,
    se_slope: analyte.se_slope ?? null,
    se_intercept: analyte.se_intercept ?? null,
    max_abs_back_calc_error_pct: analyte.max_abs_back_calc_error_pct,
    sum_abs_relative_error_pct: Number.NaN, // not stored by older method versions
    back_calc: analyte.back_calc,
    fit_line: analyte.fit_line,
    residuals: analyte.residuals,
  };
}

function exp(value: number | null | undefined, digits = 3): string {
  return value === null || value === undefined ? "—" : value.toExponential(digits);
}

/** Calibration points, backend fit line per weighting, residual plot and fit statistics. */
export function CalibrationPanel({ result, output }: Props) {
  const [analyteName, setAnalyte] = useState(output.analytes[0]?.analyte ?? "");
  const [weighting, setWeighting] = useState<Weighting>(output.weighting);
  const [mode, setMode] = useState<ResidualMode>("re");
  const current = output.analytes.find((a) => a.analyte === analyteName) ?? output.analytes[0];
  if (!current) return null;
  const fit = fitFor(current, weighting);
  const available = WEIGHTINGS.filter((w) => fitFor(current, w) !== null);
  const residualKey = mode === "re" ? "relative_error_pct" : "standardized_residual";
  const ftest = current.heteroscedasticity;

  return (
    <Card
      title={`검량선 · 보고 가중 ${WEIGHTING_LABELS[output.weighting]}`}
      subtitle={`${resultSubtitle(result)} · 곡선 ${output.curve_used} (${output.calibration_type})`}
      actions={
        <select
          aria-label="분석물"
          className="bp-input w-auto py-1 text-xs"
          value={current.analyte}
          onChange={(e) => setAnalyte(e.target.value)}
        >
          {output.analytes.map((a) => (
            <option key={a.analyte}>{a.analyte}</option>
          ))}
        </select>
      }
    >
      <div className="mb-3 flex flex-wrap items-center gap-2 text-xs" role="group" aria-label="가중치">
        <span className="text-ink-muted">가중치</span>
        {available.map((w) => (
          <button
            key={w}
            type="button"
            aria-pressed={w === weighting}
            className={w === weighting ? "bp-btn-primary px-2 py-0.5 text-xs" : "bp-btn-ghost px-2 py-0.5 text-xs"}
            onClick={() => setWeighting(w)}
          >
            {WEIGHTING_LABELS[w]}
            {w === output.weighting && " (보고)"}
          </button>
        ))}
        {ftest && (
          <span className="ml-auto">
            <Badge tone={ftest.significant ? "warn" : "ok"}>
              F-검정 {ftest.significant ? "이분산 → 가중 필요" : "등분산"} · F = {formatNumber(ftest.f_statistic, 1)}
              {" "}(임계 {formatNumber(ftest.f_critical, 1)}, α = {ftest.alpha}) · {formatPValue(ftest.p_value)}
            </Badge>
          </span>
        )}
      </div>

      {fit && (
        <div className="grid gap-4 xl:grid-cols-2">
          <div>
            <h3 className="mb-2 text-sm font-medium text-ink-muted">면적비 vs 농도</h3>
            <div className="h-60">
              <ResponsiveContainer width="100%" height="100%">
                <ComposedChart margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e0e4ea" />
                  <XAxis dataKey="level" type="number" name="농도" unit=" ng/mL" tick={{ fontSize: CHART_FONT_SIZE }} />
                  <YAxis dataKey="response_ratio" type="number" name="면적비" tick={{ fontSize: CHART_FONT_SIZE }} />
                  <Tooltip />
                  <Scatter data={current.points} fill={TOKEN_HEX.brand} name="측정" />
                  <Line data={fit.fit_line} dataKey="response_ratio" stroke={TOKEN_HEX.warn} dot={false} name="적합선" />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
          </div>
          <div>
            <div className="mb-1 flex items-center justify-between">
              <h3 className="text-sm font-medium text-ink-muted">
                잔차 플롯 · {mode === "re" ? "%RE = (x̂ − x)/x × 100" : "표준화 잔차 √w·(y − ŷ)/s"}
              </h3>
              <select
                aria-label="잔차 종류"
                className="bp-input w-auto py-0.5 text-xs"
                value={mode}
                onChange={(e) => setMode(e.target.value as ResidualMode)}
              >
                <option value="re">%RE</option>
                <option value="std">표준화 잔차</option>
              </select>
            </div>
            <div className="h-60">
              <ResponsiveContainer width="100%" height="100%">
                <ScatterChart margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e0e4ea" />
                  <XAxis dataKey="level" type="number" name="농도" unit=" ng/mL" scale="log" domain={["dataMin", "dataMax"]} ticks={fit.back_calc.map((b) => b.level)} tick={{ fontSize: CHART_FONT_SIZE }} />
                  <YAxis dataKey={residualKey} type="number" name={mode === "re" ? "%RE" : "표준화 잔차"} tick={{ fontSize: CHART_FONT_SIZE }} />
                  <ReferenceLine y={0} stroke={TOKEN_HEX.faint} />
                  <Tooltip formatter={(v: number) => formatNumber(v, 2)} />
                  <Scatter data={fit.residuals} fill={seriesColor(1)} name="잔차" />
                </ScatterChart>
              </ResponsiveContainer>
            </div>
          </div>
        </div>
      )}

      {fit && (
        <div className="mt-3 grid gap-4 xl:grid-cols-2">
          <div className="space-y-3">
            <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-3 [&_dd]:tabular-nums">
              <div><dt className="text-ink-muted">기울기 b</dt><dd className="font-mono">{exp(fit.slope, 4)}</dd></div>
              <div><dt className="text-ink-muted">절편 a</dt><dd className="font-mono">{exp(fit.intercept)}</dd></div>
              <div><dt className="text-ink-muted">R² (가중)</dt><dd className="font-mono">{formatNumber(fit.r_squared, 5)}</dd></div>
              <div><dt className="text-ink-muted">SE(b)</dt><dd className="font-mono">{exp(fit.se_slope, 2)}</dd></div>
              <div><dt className="text-ink-muted">SE(a)</dt><dd className="font-mono">{exp(fit.se_intercept, 2)}</dd></div>
              <div><dt className="text-ink-muted">잔차 SD s</dt><dd className="font-mono">{exp(fit.residual_sd, 2)}</dd></div>
            </dl>
            <DataTable
              rows={fit.back_calc}
              rowKey={(b) => b.level}
              columns={[
                { key: "lv", header: "수준 (ng/mL)", align: "right", render: (b) => formatNumber(b.level, 1) },
                { key: "bc", header: "역산 평균", align: "right", render: (b) => formatNumber(b.mean_back_calculated, 3) },
                { key: "acc", header: "정확도", align: "right", render: (b) => formatWithUnit(b.accuracy_pct, "%") },
              ]}
            />
          </div>
          <DataTable
            rows={output.weighting_comparison}
            rowKey={(w) => w.weighting}
            rowClassName={(w) => (w.weighting === weighting ? "bg-brand-soft/50" : undefined)}
            columns={[
              { key: "w", header: "가중", render: (w) => (w.weighting === output.weighting ? <b>{WEIGHTING_LABELS[w.weighting]} (보고)</b> : WEIGHTING_LABELS[w.weighting]) },
              { key: "e", header: "Σ|%RE| (전 분석물)", align: "right", render: (w) => formatWithUnit(w.sum_abs_relative_error_pct, "%") },
            ]}
          />
        </div>
      )}
      <MethodNotes method={output.method} />
    </Card>
  );
}
