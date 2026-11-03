import type { Evidence } from "@/api/types";
import { formatEvidenceValue } from "@/lib/format";

/** Shows one evidence item; its number is the stored `value`, never parsed from prose. */
export function EvidenceChip({ evidence }: { evidence: Evidence }) {
  return (
    <span
      title={`${evidence.ref_type} #${evidence.ref_id}${evidence.text ? ` · ${evidence.text}` : ""}`}
      className="inline-flex items-center gap-1 rounded border border-border bg-subtle px-1.5 py-0.5 text-xs"
    >
      <span className="font-mono text-ink-faint">{evidence.key}</span>
      <span className="text-ink-muted">{evidence.label}</span>
      {evidence.value !== null && evidence.value !== undefined && (
        <span className="font-medium tabular-nums text-ink">
          {formatEvidenceValue(evidence.value, evidence.unit)}
        </span>
      )}
    </span>
  );
}
