/** Display helpers for protocol values — formatting only, no arithmetic on values. */
import { formatConditionValue } from "@/lib/format";

/** `10` + `min` → `10 min`; text values as stored; missing → em dash. */
export function conditionText(value: unknown, unit?: string | null): string {
  const text = formatConditionValue(value);
  return unit && text !== "—" && typeof value === "number" ? `${text} ${unit}` : text;
}

/** One "프로토콜과 다른 점" line (values copied from the API). */
export function deviationText(d: {
  kind: string;
  step_index: number;
  step_title: string;
  label?: string | null;
  unit?: string | null;
  planned?: unknown;
  actual?: unknown;
  note?: string;
}): string {
  const where = `${d.step_index + 1}단계 ${d.step_title.replace(/[.。]\s*$/, "")}`;
  if (d.kind === "value") {
    const base = `${where}: ${d.label ?? ""} ${conditionText(d.planned, d.unit)} → ${conditionText(d.actual, d.unit)}`;
    return d.note ? `${base} (${d.note})` : base;
  }
  if (d.kind === "note") return `${where}: ${d.note ?? ""}`;
  return `${where}: 완료 표시 없음`;
}
