import clsx from "clsx";
import { useState, type ReactNode } from "react";

export type DisclosureTone = "default" | "ok" | "warn" | "crit";

interface DisclosureProps {
  /** Section name, always visible. */
  title: ReactNode;
  /** One-line meaning shown next to the title while collapsed (e.g. "3/10 주입 기준 이탈"). */
  summary?: ReactNode;
  /** Status color of the marker: problems stand out, normal sections stay quiet. */
  tone?: DisclosureTone;
  defaultOpen?: boolean;
  /**
   * Render children only after the first open (heavy charts/tables). Default false so the
   * content stays in the DOM (searchable, testable) even while collapsed.
   */
  lazy?: boolean;
  id?: string;
  className?: string;
  children: ReactNode;
}

/** Marker per tone: a distinct glyph *and* color, plus a spoken label, so status never
 *  depends on color alone (red/orange are hard to tell apart for color-blind readers). */
const MARKER: Record<DisclosureTone, { glyph: string; label: string; className: string }> = {
  default: { glyph: "–", label: "정보", className: "border-border text-ink-faint" },
  ok: { glyph: "✓", label: "정상", className: "border-ok/40 bg-ok-soft text-ok" },
  warn: { glyph: "!", label: "주의", className: "border-warn/40 bg-warn-soft text-warn" },
  crit: { glyph: "✕", label: "심각", className: "border-crit/40 bg-crit-soft text-crit" },
};

/**
 * Collapsible "자세히" section. Used to push evidence, raw tables, settings and logs
 * below the one answer each screen gives. Nested `Card`s lose their own frame.
 */
export function Disclosure({
  title,
  summary,
  tone = "default",
  defaultOpen = false,
  lazy = false,
  id,
  className,
  children,
}: DisclosureProps) {
  const [open, setOpen] = useState(defaultOpen);
  const [opened, setOpened] = useState(defaultOpen);
  return (
    <details
      id={id}
      open={open}
      onToggle={(e) => {
        const next = e.currentTarget.open;
        setOpen(next);
        if (next) setOpened(true);
      }}
      className={clsx("group rounded-card border border-border bg-surface", className)}
    >
      <summary className="flex select-none items-center gap-2 rounded-card px-4 py-3 hover:bg-subtle/70">
        <span
          className={clsx(
            "grid h-5 w-5 shrink-0 place-items-center rounded-full border text-xs font-bold leading-none",
            MARKER[tone].className,
          )}
          title={MARKER[tone].label}
        >
          <span aria-hidden>{MARKER[tone].glyph}</span>
          <span className="sr-only">{MARKER[tone].label}</span>
        </span>
        <span className="flex min-w-0 flex-1 flex-wrap items-baseline gap-x-2 gap-y-0.5">
          <span className="text-sm font-medium text-ink">{title}</span>
          {summary && (
            <span
              className={clsx(
                "min-w-0 text-sm",
                tone === "crit" ? "text-crit" : tone === "warn" ? "text-warn" : "text-ink-muted",
              )}
            >
              {summary}
            </span>
          )}
        </span>
        <span aria-hidden className="shrink-0 text-xs font-medium text-brand group-open:hidden">
          펼치기
        </span>
        <span aria-hidden className="hidden shrink-0 text-xs font-medium text-brand group-open:inline">
          접기
        </span>
      </summary>
      <div className="border-t border-border px-4 pb-4 pt-4 [&>section]:border-0 [&>section]:p-0">
        {!lazy || opened ? children : null}
      </div>
    </details>
  );
}
