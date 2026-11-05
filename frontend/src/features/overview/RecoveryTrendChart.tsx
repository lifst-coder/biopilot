import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceArea,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { AcceptanceCriteria, TrendPoint } from "@/api/types";
import { EmptyState } from "@/components";
import { CHART_FONT_SIZE, TOKEN_HEX } from "@/lib/chartColors";
import { formatWithUnit } from "@/lib/format";

interface Props {
  points: TrendPoint[];
  criteria: AcceptanceCriteria | null;
}

/** Line of stored mean recoveries with the acceptance band from the criteria API. */
export function RecoveryTrendChart({ points, criteria, onSelect }: Props & { onSelect?: (experimentId: number) => void }) {
  const data = points.filter((p) => p.recovery_mean_pct !== null);
  if (data.length === 0) return <EmptyState>아직 회수율 결과가 있는 실험이 없습니다 — 회수율 CSV를 올리고 분석하면 실험별 평균이 여기에 쌓입니다.</EmptyState>;
  return (
    <div className="h-64">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart
          data={data}
          margin={{ top: 8, right: 16, bottom: 0, left: -8 }}
          className={onSelect ? "cursor-pointer" : undefined}
          onClick={(state) => {
            const point = state?.activePayload?.[0]?.payload as TrendPoint | undefined;
            if (point && onSelect) onSelect(point.experiment_id);
          }}
        >
          <CartesianGrid strokeDasharray="3 3" stroke="#e0e4ea" />
          <XAxis dataKey="code" tick={{ fontSize: CHART_FONT_SIZE }} />
          <YAxis tick={{ fontSize: CHART_FONT_SIZE }} domain={["auto", "auto"]} unit="%" />
          {criteria && (
            <ReferenceArea
              y1={criteria.recovery_min_pct}
              y2={criteria.recovery_max_pct}
              fill={TOKEN_HEX.ok}
              fillOpacity={0.06}
              ifOverflow="extendDomain"
            />
          )}
          <Tooltip formatter={(v: number) => formatWithUnit(v, "%")} />
          <Line
            type="linear"
            dataKey="recovery_mean_pct"
            name="평균 회수율"
            stroke={TOKEN_HEX.brand}
            strokeWidth={2}
            dot={{ r: 4 }}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
