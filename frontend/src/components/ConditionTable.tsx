import clsx from "clsx";
import { useConditionFields } from "@/api/queries";
import type { ConditionBlock } from "@/api/types";
import { formatConditionValue } from "@/lib/format";

/**
 * Key/value view of an immutable condition block using backend-provided labels.
 * `highlight` marks keys that differ from a baseline (e.g. the parent experiment).
 */
export function ConditionTable({ block, highlight }: { block: ConditionBlock; highlight?: ReadonlySet<string> }) {
  const { data: fields = [] } = useConditionFields();
  const labels = new Map(fields.map((f) => [f.key, f.label]));
  const entries = Object.entries(block).filter(([, v]) => v !== null && v !== undefined);
  return (
    <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1 text-xs">
      {entries.map(([key, value]) => {
        const changed = highlight?.has(key) ?? false;
        return (
          <div key={key} className="contents">
            <dt className={clsx(changed ? "font-semibold text-warn" : "text-ink-muted")}>{labels.get(key) ?? key}</dt>
            <dd className={clsx("font-mono", changed ? "font-semibold text-warn" : "text-ink")}>
              {formatConditionValue(value)}
              {changed && <span className="ml-1 font-sans text-[10px]">· 기준과 다름</span>}
            </dd>
          </div>
        );
      })}
    </dl>
  );
}
