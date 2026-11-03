import { cleanup, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";
import type { ExperimentMetrics } from "@/api/types";
import type { AcceptanceCriteria, QCFlag } from "./types";
import { flagSummary, flagTone, VerdictSummary } from "./VerdictSummary";

afterEach(cleanup);

const criteria = {
  source: "SANTE/11312/2021",
  recovery_min_pct: 70,
  recovery_max_pct: 120,
  rsd_max_pct: 20,
  r_squared_min: 0.99,
  is_response_min_pct: 50,
  is_response_max_pct: 150,
  expanded_uncertainty_max_pct: 50,
  grubbs_alpha: 0.05,
} as AcceptanceCriteria;

const flag = (code: QCFlag["code"], severity: QCFlag["severity"], context: Record<string, unknown> = {}): QCFlag => ({
  code,
  severity,
  analyte: null,
  value: 1,
  threshold_low: null,
  threshold_high: null,
  context,
  criteria_version: "default",
});

// Arbitrary fixture values (never displayed in-app).
const metrics = (overrides: Partial<ExperimentMetrics> = {}): ExperimentMetrics =>
  ({
    experiment_id: 7,
    analyzed: true,
    recovery_mean_pct: 55.5,
    recovery_rsd_pct: 21.5,
    recovery_n: 20,
    per_analyte_recovery: [
      { analyte: "alpha", mean_pct: 40.04, rsd_pct: 3, n: 10 },
      { analyte: "beta", mean_pct: 71, rsd_pct: 3, n: 10 },
    ],
    min_r_squared: 0.9995,
    calibration_weighting: "1/x",
    is_injections_total: 10,
    is_injections_flagged: 2,
    matrix_effect_pct: {},
    expanded_uncertainty_pct: {},
    limits: [],
    outlier_count: 0,
    criteria_versions: ["default"],
    source_result_ids: [1, 2],
    qc_status: "fail",
    qc_verdicts: [
      { analyte: "alpha", status: "fail", failed_checks: ["recovery_out_of_range"], warning_checks: [] },
      { analyte: "beta", status: "warning", failed_checks: [], warning_checks: ["uncertainty_high"] },
    ],
    flags: [
      flag("recovery_out_of_range", "critical"),
      flag("is_suppression", "warning", { injection_id: "S-03" }),
      flag("is_suppression", "warning", { injection_id: "S-07" }),
    ],
    ...overrides,
  }) as ExperimentMetrics;

function renderVerdict(m: ExperimentMetrics, baseline = { code: "#018", metrics: metrics({ recovery_mean_pct: 88.84 }) }) {
  return render(
    <MemoryRouter>
      <VerdictSummary metrics={m} criteria={criteria} baseline={baseline} />
    </MemoryRouter>,
  );
}

describe("VerdictSummary", () => {
  it("puts the QC verdict first, with failed analytes and their stored values", () => {
    renderVerdict(metrics());
    const verdict = screen.getByTestId("qc-verdict");
    expect(within(verdict).getByText("불합격")).toBeTruthy();
    expect(within(verdict).getByText("분석물 2개 중 1개 불합격 1개 검토 필요")).toBeTruthy();
    expect(within(verdict).getByText("회수율 범위 이탈")).toBeTruthy();
    expect(within(verdict).getByText("alpha 40.0%")).toBeTruthy();
    expect(within(verdict).getByText("(기준 70–120%)")).toBeTruthy();
    expect(within(verdict).getByRole("link", { name: /Research AI/ })).toBeTruthy();
  });

  it("gives each key number its meaning against the criterion and the baseline", () => {
    renderVerdict(metrics());
    expect(screen.getByText("기준(70–120%) 미달 · 기준 실험 #018은 88.8%")).toBeTruthy();
    expect(screen.getByText(/RSD는 모두 기준\(≤20%\) 이내/)).toBeTruthy();
    expect(screen.getByText("2/10")).toBeTruthy();
    expect(screen.getByText("기준(50–150%) 밖: S-03 · S-07")).toBeTruthy();
  });

  it("stays quiet when everything passes", () => {
    renderVerdict(
      metrics({
        qc_status: "pass",
        recovery_mean_pct: 90,
        is_injections_flagged: 0,
        flags: [],
        qc_verdicts: [{ analyte: "alpha", status: "pass", failed_checks: [], warning_checks: [] }],
      }),
    );
    expect(screen.getByText("합격")).toBeTruthy();
    expect(screen.getByText("분석물 1개 중 모두 합격")).toBeTruthy();
    expect(screen.queryByRole("list", { name: "불합격 항목" })).toBeNull();
    expect(screen.queryByRole("link", { name: /Research AI/ })).toBeNull();
    expect(screen.getByText(/기준\(70–120%\) 충족/)).toBeTruthy();
  });

  it("summarizes section flags by label and picks the marker tone", () => {
    const flags = [flag("is_suppression", "warning"), flag("is_suppression", "warning"), flag("outlier_suspected", "warning")];
    expect(flagSummary(flags)).toBe("IS 억제 2 · 이상치 의심 (Grubbs) 1");
    expect(flagSummary([])).toBeNull();
    expect(flagTone(flags)).toBe("warn");
    expect(flagTone([flag("recovery_out_of_range", "critical")])).toBe("crit");
    expect(flagTone([flag("loq_above_lowest_level", "info")])).toBe("default");
    expect(flagTone([])).toBe("ok");
  });
});
