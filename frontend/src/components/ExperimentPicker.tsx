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
    <label className="flex items-center gap-2 text-xs text-ink-muted">
      {label}
      <select
        className="bp-input w-auto py-1"
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
