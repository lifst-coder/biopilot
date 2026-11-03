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

const MARKER: Record<DisclosureTone, string> = {
  default: "bg-ink-faint/50",
  ok: "bg-ok",
  warn: "bg-warn",
  crit: "bg-crit",
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
      <summary className="flex cursor-pointer select-none list-none items-center gap-2 px-4 py-2.5 hover:bg-subtle/60 [&::-webkit-details-marker]:hidden">
        <span aria-hidden className="text-[10px] text-ink-faint transition-transform group-open:rotate-90">
          ▶
        </span>
        <span aria-hidden className={clsx("h-2 w-2 shrink-0 rounded-full", MARKER[tone])} />
        <span className="text-sm font-medium text-ink">{title}</span>
        {summary && (
          <span
            className={clsx(
              "min-w-0 truncate text-xs",
              tone === "crit" ? "text-crit" : tone === "warn" ? "text-warn" : "text-ink-muted",
            )}
          >
            {summary}
          </span>
        )}
      </summary>
      <div className="border-t border-border px-4 pb-4 pt-3 [&>section]:border-0 [&>section]:p-0">
        {!lazy || opened ? children : null}
      </div>
    </details>
  );
}
