import { useState } from "react";
import { useStartProtocolRun } from "@/api/queries";
import { ErrorState } from "@/components";
import type { ProtocolsNav } from "./ProtocolsPage";

/** Operator name + "start" button; opens the run view of the new run. */
export function StartRun({ templateId, label, go }: { templateId: number; label: string; go: ProtocolsNav }) {
  const start = useStartProtocolRun();
  const [operator, setOperator] = useState("");
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-end gap-2">
        <label className="min-w-0 flex-1 text-sm text-ink-muted sm:max-w-[12rem]">
          작업자
          <input
            className="bp-input mt-0.5"
            value={operator}
            onChange={(e) => setOperator(e.target.value)}
            placeholder="이름 (선택)"
          />
        </label>
        <button
          type="button"
          className="bp-btn-primary min-h-[2.5rem]"
          disabled={start.isPending}
          onClick={() => start.mutate({ templateId, operator }, { onSuccess: (run) => go("run", run.id) })}
        >
          {label}
        </button>
      </div>
      {start.error && <ErrorState error={start.error} />}
    </div>
  );
}
