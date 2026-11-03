import clsx from "clsx";
import type { ReactNode } from "react";

interface StatTileProps {
  label: string;
  /** Pre-formatted value — always derived from API data. */
  value: ReactNode;
  /** Secondary detail (sample size, source). */
  hint?: ReactNode;
  /**
   * What the number means against its criterion / baseline, e.g. "기준(70%) 미달 · #018은 89.1%".
   * Shown in the tone color so a problem reads at a glance.
   */
  meaning?: ReactNode;
  /** One-line explanation of the term (tooltip on the label + small text). */
  help?: string;
  tone?: "default" | "ok" | "warn" | "crit";
}

const TONE: Record<NonNullable<StatTileProps["tone"]>, string> = {
  default: "text-ink",
  ok: "text-ok",
  warn: "text-warn",
  crit: "text-crit",
};

const FRAME: Record<NonNullable<StatTileProps["tone"]>, string> = {
  default: "border-border",
  ok: "border-border",
  warn: "border-warn/40",
  crit: "border-crit/40",
};

/** A number with its meaning. Problems get a colored frame; normal values stay quiet. */
export function StatTile({ label, value, hint, meaning, help, tone = "default" }: StatTileProps) {
  return (
    <div className={clsx("rounded-card border bg-surface px-4 py-3", FRAME[tone])}>
      <div
        className={clsx("text-xs text-ink-muted", help && "cursor-help underline decoration-ink-faint decoration-dotted underline-offset-2")}
        title={help}
      >
        {label}
      </div>
      <div className={clsx("mt-1 text-2xl font-semibold tabular-nums", TONE[tone])}>{value}</div>
      {meaning && (
        <div className={clsx("mt-0.5 text-xs", tone === "default" || tone === "ok" ? "text-ink-muted" : TONE[tone])}>
          {meaning}
        </div>
      )}
      {hint && <div className="mt-0.5 text-xs text-ink-faint">{hint}</div>}
      {help && <div className="mt-1.5 text-[11px] leading-snug text-ink-faint">{help}</div>}
    </div>
  );
}
