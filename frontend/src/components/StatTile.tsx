import clsx from "clsx";
import type { ReactNode } from "react";

interface StatTileProps {
  label: string;
  /** Pre-formatted value — always derived from API data. */
  value: ReactNode;
  hint?: ReactNode;
  tone?: "default" | "ok" | "warn" | "crit";
}

const TONE: Record<NonNullable<StatTileProps["tone"]>, string> = {
  default: "text-ink",
  ok: "text-ok",
  warn: "text-warn",
  crit: "text-crit",
};

export function StatTile({ label, value, hint, tone = "default" }: StatTileProps) {
  return (
    <div className="rounded-card border border-border bg-surface px-4 py-3">
      <div className="text-xs text-ink-muted">{label}</div>
      <div className={clsx("mt-1 text-2xl font-semibold tabular-nums", TONE[tone])}>{value}</div>
      {hint && <div className="mt-0.5 text-xs text-ink-faint">{hint}</div>}
    </div>
  );
}
