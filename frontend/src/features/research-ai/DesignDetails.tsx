import { formatConditionValue } from "@/lib/format";
import { POWER_LABEL, type ExperimentDesign } from "./types";

/** Next Experiment Designer output: variables, controls, replicates, measurements, power. */
export function DesignDetails({ design, codeOf }: { design: ExperimentDesign; codeOf: (id: number) => string }) {
  const varied = design.variables.filter((v) => v.role === "varied");
  const fixed = design.variables.filter((v) => v.role === "fixed");
  return (
    <dl className="grid grid-cols-[6rem_1fr] gap-x-2 gap-y-1 rounded-md bg-subtle p-2 text-[11px]">
      <dt className="text-ink-muted">목적</dt>
      <dd>{design.objective}</dd>
      <dt className="text-ink-muted">변수</dt>
      <dd>
        {varied.map((v) => (
          <div key={v.key}>
            <b>{v.label}</b>: {v.levels.map((l) => formatConditionValue(l)).join(" / ")}
          </div>
        ))}
        {fixed.length > 0 && <div className="text-ink-faint">고정: {fixed.map((v) => v.label).join(", ")}</div>}
      </dd>
      <dt className="text-ink-muted">대조군</dt>
      <dd>
        {design.controls.map((c) => (
          <div key={c.name}>
            {c.name} <span className="text-ink-faint">— {c.purpose}</span>
          </div>
        ))}
      </dd>
      <dt className="text-ink-muted">반복 수</dt>
      <dd>
        {design.replicates ?? "—"}
        {design.replicates_basis && <span className="text-ink-faint"> ({design.replicates_basis})</span>}
      </dd>
      <dt className="text-ink-muted">측정 항목</dt>
      <dd>{design.measurements.join(" · ")}</dd>
      <dt className="text-ink-muted">예상 판별력</dt>
      <dd>
        <b>{POWER_LABEL[design.discriminating_power]}</b> — {design.power_rationale}
      </dd>
      <dt className="text-ink-muted">결과 해석</dt>
      <dd>
        {design.expected_outcomes.map((o) => (
          <div key={o.observation}>
            {o.observation} → {o.interpretation}
          </div>
        ))}
      </dd>
      <dt className="text-ink-muted">근거 실험</dt>
      <dd>{design.basis_experiment_ids.map(codeOf).join(", ")}</dd>
    </dl>
  );
}
