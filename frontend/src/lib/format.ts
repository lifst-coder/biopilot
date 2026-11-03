/**
 * Number/date formatting. Formatting only — never arithmetic on measurements
 * (CLAUDE.md §2: calculations happen in the backend).
 */

const EMPTY = "—";

/** Format a stored number; `null`/`undefined`/NaN render as an em dash. */
export function formatNumber(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return EMPTY;
  return value.toLocaleString("ko-KR", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

/** Number followed by a unit (`89.1%`, `-27.1%p`). */
export function formatWithUnit(
  value: number | null | undefined,
  unit: string | null | undefined,
  digits = 1,
): string {
  const text = formatNumber(value, digits);
  return text === EMPTY || !unit ? text : `${text}${unit}`;
}

/** Evidence values: integers without decimals, tiny values in scientific notation. */
export function formatEvidenceValue(value: number, unit: string | null | undefined): string {
  if (Number.isInteger(value)) return formatWithUnit(value, unit, 0);
  if (value !== 0 && Math.abs(value) < 0.001) return `${value.toExponential(1)}${unit ?? ""}`;
  return formatWithUnit(value, unit, Math.abs(value) < 1 ? 4 : 1);
}

/** p-values: fixed thresholds below 0.001, otherwise three decimals. */
export function formatPValue(p: number | null | undefined): string {
  if (p === null || p === undefined) return EMPTY;
  return p < 0.001 ? "p < 0.001" : `p = ${p.toFixed(3)}`;
}

/** Render a condition-block value (numbers keep their stored precision). */
export function formatConditionValue(value: unknown): string {
  if (value === null || value === undefined) return EMPTY;
  if (typeof value === "number") return String(value);
  if (typeof value === "string") return value;
  return JSON.stringify(value);
}

/** `2026-10-20` → `2026. 10. 20.` */
export function formatDate(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString("ko-KR");
}

export function formatDateTime(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString("ko-KR");
}
