import clsx from "clsx";

/**
 * Inline status mark for a flagged table value: a glyph (✕ critical, ! warning) in the
 * status color with a spoken label, so a flagged row is not signalled by its background
 * tint alone (red vs. orange is ambiguous for color-blind readers).
 */
export function FlagMark({ tone, label }: { tone: "crit" | "warn"; label: string }) {
  return (
    <span
      title={label}
      className={clsx("mr-1 inline-block w-3 text-center font-bold", tone === "crit" ? "text-crit" : "text-warn")}
    >
      <span aria-hidden>{tone === "crit" ? "✕" : "!"}</span>
      <span className="sr-only">{label}</span>
    </span>
  );
}
