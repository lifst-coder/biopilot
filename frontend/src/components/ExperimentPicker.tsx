import type { ExperimentSummary } from "@/api/types";

interface ExperimentPickerProps {
  experiments: ExperimentSummary[];
  value: number | null;
  onChange: (id: number) => void;
  label?: string;
  allowEmpty?: boolean;
}

export function ExperimentPicker({
  experiments,
  value,
  onChange,
  label = "실험",
  allowEmpty = false,
}: ExperimentPickerProps) {
  return (
    <label className="flex w-full min-w-0 items-center gap-2 whitespace-nowrap text-sm text-ink-muted sm:w-auto">
      {label}
      <select
        className="bp-input min-w-0 flex-1 truncate py-1 sm:w-auto sm:flex-none"
        value={value ?? ""}
        onChange={(e) => onChange(Number(e.target.value))}
      >
        {allowEmpty && <option value="">선택</option>}
        {experiments.map((e) => (
          <option key={e.id} value={e.id}>
            {e.code} · {e.title}
          </option>
        ))}
      </select>
    </label>
  );
}
