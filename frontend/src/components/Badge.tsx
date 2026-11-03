import clsx from "clsx";
import type { ReactNode } from "react";
import type { Severity } from "@/api/types";

export type BadgeTone = "neutral" | "brand" | "ok" | "warn" | "crit" | "ai";

const TONES: Record<BadgeTone, string> = {
  neutral: "bg-subtle text-ink-muted",
  brand: "bg-brand-soft text-brand-strong",
  ok: "bg-ok-soft text-ok",
  warn: "bg-warn-soft text-warn",
  crit: "bg-crit-soft text-crit",
  ai: "bg-ai-soft text-ai",
};

export function Badge({ tone = "neutral", children }: { tone?: BadgeTone; children: ReactNode }) {
  return (
    <span
      className={clsx(
        "inline-flex items-center whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium",
        TONES[tone],
      )}
    >
      {children}
    </span>
  );
}

const SEVERITY: Record<Severity, { tone: BadgeTone; label: string }> = {
  critical: { tone: "crit", label: "치명" },
  warning: { tone: "warn", label: "경고" },
  info: { tone: "brand", label: "정보" },
};

export function SeverityBadge({ severity }: { severity: Severity }) {
  const s = SEVERITY[severity];
  return <Badge tone={s.tone}>{s.label}</Badge>;
}

/** Marks AI-generated content and which engine produced it. */
export function EngineBadge({ engine, model }: { engine: "rules" | "claude"; model?: string | null }) {
  return (
    <Badge tone="ai">
      {engine === "claude" ? `AI · Claude${model ? ` (${model})` : ""}` : "AI · 규칙 모드"}
    </Badge>
  );
}

/** Marks immutable original records. */
export function OriginalBadge() {
  return <Badge tone="neutral">원본 · 불변</Badge>;
}
