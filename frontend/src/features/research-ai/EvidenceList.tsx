import { EvidenceChip } from "@/components";
import type { Evidence } from "./types";

/** Evidence chips for a list of keys; numbers come from stored `Evidence.value` only. */
export function EvidenceList({ keys, evidence }: { keys: string[]; evidence: Map<string, Evidence> }) {
  const items = keys.map((k) => evidence.get(k)).filter((e): e is Evidence => e !== undefined);
  if (items.length === 0) return null;
  return (
    <div className="mt-1 flex flex-wrap gap-1">
      {items.map((e) => (
        <EvidenceChip key={e.key} evidence={e} />
      ))}
    </div>
  );
}
