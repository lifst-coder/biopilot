/** Chart series colors read from design tokens (falls back for jsdom/tests). */
const FALLBACK = ["#0d7490", "#6b46c1", "#965800", "#127644", "#c02633"];

export function seriesColor(index: number): string {
  const name = `--bp-chart-${(index % FALLBACK.length) + 1}`;
  if (typeof window !== "undefined") {
    const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    if (value) return value;
  }
  return FALLBACK[index % FALLBACK.length] ?? "#0d7490";
}

/** Axis tick / label size for every chart (same as Tailwind `text-xs`). */
export const CHART_FONT_SIZE = 12;

export const TOKEN_HEX = {
  ok: "#127644",
  warn: "#965800",
  crit: "#c02633",
  brand: "#0d7490",
  faint: "#5c6778",
} as const;
