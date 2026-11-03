import { useConditionFields } from "@/api/queries";
import type { ConditionBlock } from "@/api/types";
import { formatConditionValue } from "@/lib/format";

/** Key/value view of an immutable condition block using backend-provided labels. */
export function ConditionTable({ block }: { block: ConditionBlock }) {
  const { data: fields = [] } = useConditionFields();
  const labels = new Map(fields.map((f) => [f.key, f.label]));
  const entries = Object.entries(block).filter(([, v]) => v !== null && v !== undefined);
  return (
    <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1 text-xs">
      {entries.map(([key, value]) => (
        <div key={key} className="contents">
          <dt className="text-ink-muted">{labels.get(key) ?? key}</dt>
          <dd className="font-mono text-ink">{formatConditionValue(value)}</dd>
        </div>
      ))}
    </dl>
  );
}
