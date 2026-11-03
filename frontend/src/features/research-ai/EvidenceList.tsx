import { useState } from "react";
import { EvidenceChip } from "@/components";
import type { Evidence } from "./types";

/**
 * Evidence chips for a list of keys; numbers come from stored `Evidence.value` only.
 * With `max`, only the first chips are shown and the rest sit behind "+N".
 */
export function EvidenceList({
  keys,
  evidence,
  max,
}: {
  keys: string[];
  evidence: Map<string, Evidence>;
  max?: number;
}) {
  const [expanded, setExpanded] = useState(false);
  const items = keys.map((k) => evidence.get(k)).filter((e): e is Evidence => e !== undefined);
  if (items.length === 0) return null;
  const limit = max !== undefined && !expanded ? max : items.length;
  const hidden = items.length - limit;
  return (
    <div className="mt-1 flex flex-wrap gap-1">
      {items.slice(0, limit).map((e) => (
        <EvidenceChip key={e.key} evidence={e} />
      ))}
      {hidden > 0 && (
        <button
          type="button"
          className="rounded border border-dashed border-border px-1.5 py-0.5 text-xs text-ink-muted hover:bg-subtle"
          onClick={() => setExpanded(true)}
        >
          근거 +{hidden}
        </button>
      )}
    </div>
  );
}
