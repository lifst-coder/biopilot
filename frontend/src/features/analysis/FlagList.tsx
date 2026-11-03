import type { QCFlag } from "@/api/types";
import { DataTable, SeverityBadge } from "@/components";
import { formatNumber } from "@/lib/format";

const LABELS: Record<QCFlag["code"], string> = {
  recovery_out_of_range: "회수율 범위 이탈",
  recovery_rsd_high: "회수율 RSD 초과",
  calibration_r2_low: "R² 미달",
  calibration_back_calc_error: "역산 정확도 초과",
  is_suppression: "IS 억제",
  is_enhancement: "IS 증강",
  matrix_effect_significant: "유의한 매트릭스 효과",
  outlier_suspected: "이상치 의심 (Grubbs)",
  uncertainty_high: "확장 불확도 초과",
  ion_ratio_out_of_range: "이온비 허용범위 이탈",
  loq_above_lowest_level: "LOQ > 최저 검량 수준",
};

function range(f: QCFlag): string {
  const lo = f.threshold_low ?? null;
  const hi = f.threshold_high ?? null;
  if (lo !== null && hi !== null) return `${formatNumber(lo, 1)} – ${formatNumber(hi, 1)}`;
  if (lo !== null) return `≥ ${formatNumber(lo, 2)}`;
  if (hi !== null) return `≤ ${formatNumber(hi, 1)}`;
  return "—";
}

export function FlagList({ flags }: { flags: QCFlag[] }) {
  return (
    <DataTable
      rows={flags}
      rowKey={(f, i) => `${f.code}-${i}`}
      empty="플래그 없음 — 모든 기준 충족"
      columns={[
        { key: "s", header: "심각도", render: (f) => <SeverityBadge severity={f.severity} /> },
        { key: "c", header: "판정", render: (f) => LABELS[f.code] },
        {
          key: "t",
          header: "대상",
          render: (f) => f.analyte ?? String((f.context as Record<string, unknown>)["injection_id"] ?? "—"),
        },
        { key: "v", header: "값", align: "right", render: (f) => formatNumber(f.value, 1) },
        { key: "r", header: "기준", align: "right", render: range },
      ]}
    />
  );
}
