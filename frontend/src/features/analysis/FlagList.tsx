import { DataTable, SeverityBadge } from "@/components";
import { formatNumber } from "@/lib/format";
import { FLAG_LABELS } from "./labels";
import type { QCFlag } from "./types";

function range(f: QCFlag): string {
  const lo = f.threshold_low ?? null;
  const hi = f.threshold_high ?? null;
  if (lo !== null && hi !== null) return `${formatNumber(lo, 1)} – ${formatNumber(hi, 1)}`;
  if (lo !== null) return `≥ ${formatNumber(lo, 2)}`;
  if (hi !== null) return `≤ ${formatNumber(hi, 2)}`;
  return "—";
}

function target(f: QCFlag): string {
  const ctx = f.context as Record<string, unknown>;
  const injection = ctx["injection_id"];
  if (f.analyte && injection) return `${f.analyte} · ${String(injection)}`;
  return f.analyte ?? String(injection ?? "—");
}

/** Deterministic QC flags with the criteria version each was judged against. */
export function FlagList({ flags }: { flags: QCFlag[] }) {
  return (
    <DataTable
      rows={flags}
      rowKey={(f, i) => `${f.code}-${i}`}
      empty="플래그 없음 — 모든 기준 충족"
      columns={[
        { key: "s", header: "심각도", render: (f) => <SeverityBadge severity={f.severity} /> },
        { key: "c", header: "판정", render: (f) => FLAG_LABELS[f.code] },
        { key: "t", header: "대상", render: target },
        { key: "v", header: "값", align: "right", render: (f) => formatNumber(f.value, 2) },
        { key: "r", header: "기준", align: "right", render: range },
        { key: "cv", header: "기준 버전", render: (f) => f.criteria_version ?? "—" },
      ]}
    />
  );
}
