/** Chart series colors read from design tokens (falls back for jsdom/tests). */
const FALLBACK = ["#0d7490", "#6b46c1", "#b56e08", "#16804a", "#c02633"];

export function seriesColor(index: number): string {
  const name = `--bp-chart-${(index % FALLBACK.length) + 1}`;
  if (typeof window !== "undefined") {
    const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    if (value) return value;
  }
  return FALLBACK[index % FALLBACK.length] ?? "#0d7490";
}

export const TOKEN_HEX = {
  ok: "#16804a",
  warn: "#b56e08",
  crit: "#c02633",
  brand: "#0d7490",
  faint: "#8c97a8",
} as const;
