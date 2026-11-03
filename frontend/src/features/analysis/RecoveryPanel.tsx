import { Bar, BarChart, CartesianGrid, ReferenceArea, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useCriteria } from "@/api/queries";
import type { AnalysisResultOut, RecoveryOutput } from "@/api/types";
import { Card, DataTable } from "@/components";
import { TOKEN_HEX } from "@/lib/chartColors";
import { formatNumber, formatWithUnit } from "@/lib/format";
import { resultSubtitle } from "./ResultMeta";

interface Props {
  result: AnalysisResultOut;
  output: RecoveryOutput;
}

/** Recovery by analyte × spike level, with the acceptance band from the criteria API. */
export function RecoveryPanel({ result, output }: Props) {
  const { data: criteria } = useCriteria();
  const chartData = output.groups.map((g) => ({
    name: `${g.analyte} @${formatNumber(g.spike_ng_g, 0)}`,
    mean: g.mean_pct,
  }));
  return (
    <Card title="회수율" subtitle={resultSubtitle(result)}>
      <div className="grid gap-4 xl:grid-cols-2">
        <div className="h-72">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={chartData} margin={{ top: 8, right: 16, bottom: 40, left: -8 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e0e4ea" />
              <XAxis dataKey="name" angle={-35} textAnchor="end" interval={0} tick={{ fontSize: 10 }} />
              <YAxis unit="%" tick={{ fontSize: 11 }} />
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
          rowClassName={(g) =>
            criteria && (g.mean_pct < criteria.recovery_min_pct || g.mean_pct > criteria.recovery_max_pct)
              ? "bg-crit-soft/60"
              : undefined
          }
          columns={[
            { key: "a", header: "분석물", render: (g) => g.analyte },
            { key: "s", header: "첨가 (ng/g)", align: "right", render: (g) => formatNumber(g.spike_ng_g, 0) },
            { key: "n", header: "n", align: "right", render: (g) => g.n },
            { key: "m", header: "평균", align: "right", render: (g) => formatWithUnit(g.mean_pct, "%") },
            { key: "r", header: "RSD", align: "right", render: (g) => formatWithUnit(g.rsd_pct, "%") },
          ]}
        />
      </div>
    </Card>
  );
}
