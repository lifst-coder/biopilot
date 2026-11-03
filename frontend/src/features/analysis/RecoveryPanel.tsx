import { useMemo, useState } from "react";
import { Bar, BarChart, CartesianGrid, ReferenceArea, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { AnalysisResultOut } from "@/api/types";
import { Badge, Card, DataTable, FlagMark, Term } from "@/components";
import { CHART_FONT_SIZE, TOKEN_HEX } from "@/lib/chartColors";
import { formatNumber, formatWithUnit } from "@/lib/format";
import { MethodNotes } from "./MethodNotes";
import { resultSubtitle } from "./ResultMeta";
import type { AcceptanceCriteria, RecoveryOutput } from "./types";

interface Props {
  result: AnalysisResultOut;
  output: RecoveryOutput;
  criteria?: AcceptanceCriteria;
}

const outOfRange = (value: number, c?: AcceptanceCriteria) =>
  c !== undefined && (value < c.recovery_min_pct || value > c.recovery_max_pct);

/** Recovery/RSD by analyte × spike level, uncertainty, and the raw per-injection rows. */
export function RecoveryPanel({ result, output, criteria }: Props) {
  const [filter, setFilter] = useState("");
  const chartData = output.groups.map((g) => ({
    name: `${g.analyte} @${formatNumber(g.spike_ng_g, 0)}`,
    mean: g.mean_pct,
  }));
  const rows = useMemo(() => {
    const q = filter.trim().toLowerCase();
    if (!q) return output.rows;
    return output.rows.filter(
      (r) => r.injection_id.toLowerCase().includes(q) || r.sample_id.toLowerCase().includes(q),
    );
  }, [filter, output.rows]);

  return (
    <Card
      title={`회수율 · 평균 ${formatWithUnit(output.overall_mean_pct, "%")} · RSD ${formatWithUnit(output.overall_rsd_pct, "%")}`}
      subtitle={resultSubtitle(result)}
    >
      <div className="grid gap-4 2xl:grid-cols-2">
        <div className="h-72">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={chartData} margin={{ top: 8, right: 16, bottom: 40, left: -8 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e0e4ea" />
              <XAxis dataKey="name" angle={-35} textAnchor="end" interval={0} tick={{ fontSize: CHART_FONT_SIZE }} />
              <YAxis unit="%" tick={{ fontSize: CHART_FONT_SIZE }} />
              {criteria && (
                <ReferenceArea y1={criteria.recovery_min_pct} y2={criteria.recovery_max_pct} fill={TOKEN_HEX.ok} fillOpacity={0.08} ifOverflow="extendDomain" />
              )}
              <Tooltip formatter={(v: number) => formatWithUnit(v, "%")} />
              <Bar dataKey="mean" name="평균 회수율" fill={TOKEN_HEX.brand} />
            </BarChart>
          </ResponsiveContainer>
        </div>
        <DataTable
          rows={output.groups}
          rowKey={(g) => `${g.analyte}-${g.spike_ng_g}`}
          rowClassName={(g) => (outOfRange(g.mean_pct, criteria) ? "bg-crit-soft/60" : undefined)}
          columns={[
            { key: "a", header: "분석물", render: (g) => g.analyte },
            { key: "s", header: "첨가 (ng/g)", align: "right", render: (g) => formatNumber(g.spike_ng_g, 0) },
            { key: "n", header: "n", align: "right", render: (g) => g.n },
            {
              key: "m",
              header: "평균",
              align: "right",
              render: (g) => (
                <>
                  {outOfRange(g.mean_pct, criteria) && <FlagMark tone="crit" label="허용 범위 밖" />}
                  {formatWithUnit(g.mean_pct, "%")}
                </>
              ),
            },
            { key: "sd", header: "SD", align: "right", render: (g) => formatNumber(g.sd_pct, 2) },
            { key: "r", header: <Term k="rsd">RSD</Term>, align: "right", render: (g) => formatWithUnit(g.rsd_pct, "%") },
            { key: "ni", header: <Term k="isUncorrected">IS 미보정</Term>, align: "right", render: (g) => formatWithUnit(g.mean_no_is_pct, "%") },
            {
              key: "g",
              header: <Term k="grubbs">Grubbs G</Term>,
              align: "right",
              render: (g) =>
                g.grubbs ? (
                  <span title={`G_crit ${formatNumber(g.grubbs.g_critical, 3)} (α=${g.grubbs.alpha})`}>
                    {formatNumber(g.grubbs.g_statistic, 2)}
                    {g.grubbs.is_outlier && <> <Badge tone="warn">{g.grubbs.suspect_injection_id}</Badge></>}
                  </span>
                ) : (
                  "—"
                ),
            },
          ]}
        />
      </div>

      {output.uncertainty.length > 0 && (
        <div className="mt-4">
          <h3 className="mb-2 text-sm font-medium text-ink-muted"><Term k="uncertainty">측정 불확도</Term> (상대, %)</h3>
          <DataTable
            rows={output.uncertainty}
            rowKey={(u) => u.analyte}
            rowClassName={(u) =>
              criteria && u.expanded_pct > criteria.expanded_uncertainty_max_pct ? "bg-warn-soft/60" : undefined
            }
            columns={[
              { key: "a", header: "분석물", render: (u) => u.analyte },
              { key: "rw", header: "u(Rw)", align: "right", render: (u) => formatNumber(u.u_rw_pct, 1) },
              { key: "b", header: "RMS bias", align: "right", render: (u) => formatNumber(u.rms_bias_pct, 1) },
              { key: "ub", header: "u(bias)", align: "right", render: (u) => formatNumber(u.u_bias_pct, 1) },
              { key: "uc", header: "u_c", align: "right", render: (u) => formatNumber(u.u_combined_pct, 1) },
              { key: "k", header: "k", align: "right", render: (u) => formatNumber(u.coverage_factor, 0) },
              {
                key: "U",
                header: <Term k="uncertainty">U</Term>,
                align: "right",
                render: (u) => (
                  <>
                    {criteria && u.expanded_pct > criteria.expanded_uncertainty_max_pct && <FlagMark tone="warn" label="기준 초과" />}
                    <b>{formatNumber(u.expanded_pct, 1)}</b>
                  </>
                ),
              },
            ]}
          />
        </div>
      )}

      <details className="mt-4 text-sm" open={filter !== ""}>
        <summary className="px-1 py-1 text-ink-muted">주입별 원시 행 ({output.rows.length})</summary>
        <input
          className="bp-input my-2 max-w-xs py-1 text-xs"
          placeholder="주입 ID / 시료 ID 필터 (예: S-03)"
          aria-label="주입 ID 필터"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        />
        <DataTable
          rows={rows}
          rowKey={(r) => `${r.injection_id}-${r.analyte}`}
          empty="일치하는 주입이 없습니다."
          columns={[
            { key: "i", header: "주입", render: (r) => r.injection_id },
            { key: "s", header: "시료", render: (r) => r.sample_id },
            { key: "a", header: "분석물", render: (r) => r.analyte },
            { key: "sp", header: "첨가 (ng/g)", align: "right", render: (r) => formatNumber(r.spike_ng_g, 0) },
            { key: "m", header: "측정 (ng/g)", align: "right", render: (r) => formatNumber(r.measured_ng_g, 2) },
            { key: "r", header: "회수율", align: "right", render: (r) => formatWithUnit(r.recovery_pct, "%") },
            { key: "n", header: "IS 미보정", align: "right", render: (r) => formatWithUnit(r.recovery_no_is_pct, "%") },
          ]}
        />
      </details>
      <MethodNotes method={output.method} />
    </Card>
  );
}
