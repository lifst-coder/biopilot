/** Test fixtures shaped like real API payloads (values are arbitrary, never displayed in-app). */
import type { AnalysisResultOut } from "@/api/types";
import type { CalibrationFitOut, CalibrationOutput, RecoveryOutput } from "./types";

const fit = (weighting: CalibrationFitOut["weighting"], slope: number): CalibrationFitOut => ({
  weighting,
  slope,
  intercept: 0.001,
  r_squared: 0.999,
  residual_sd: 0.002,
  se_slope: 0.0001,
  se_intercept: 0.0005,
  max_abs_back_calc_error_pct: 3,
  sum_abs_relative_error_pct: 10,
  back_calc: [{ level: 1, mean_back_calculated: 1.02, accuracy_pct: 102 }],
  fit_line: [{ level: 1, response_ratio: 0.011 }],
  residuals: [
    {
      injection_id: "CAL-01",
      level: 1,
      response_ratio: 0.0112,
      predicted: 0.011,
      residual: 0.0002,
      back_calculated: 1.02,
      relative_error_pct: 2,
      standardized_residual: 0.1,
    },
  ],
});

export const calibrationOutput: CalibrationOutput = {
  kind: "calibration",
  weighting: "1/x",
  calibration_type: "solvent",
  curve_used: "dataset",
  heteroscedastic_analytes: ["azoxystrobin"],
  method: {
    kind: "calibration",
    version: "calibration@3",
    title: "검량선",
    formulas: ["R = A_analyte / A_IS"],
    assumptions: ["x는 오차가 없다."],
    references: ["SANTE/11312/2021"],
  },
  weighting_comparison: [
    { weighting: "none", sum_abs_relative_error_pct: 292 },
    { weighting: "1/x", sum_abs_relative_error_pct: 66.9 },
    { weighting: "1/x2", sum_abs_relative_error_pct: 59.8 },
  ],
  analytes: [
    {
      analyte: "azoxystrobin",
      slope: 0.0151,
      intercept: 0.001,
      r_squared: 0.999,
      n: 1,
      weighting: "1/x",
      max_abs_back_calc_error_pct: 3,
      back_calc: [{ level: 1, mean_back_calculated: 1.02, accuracy_pct: 102 }],
      points: [{ level: 1, response_ratio: 0.0112 }],
      fit_line: [{ level: 1, response_ratio: 0.011 }],
      residual_sd: 0.002,
      se_slope: 0.0001,
      se_intercept: 0.0005,
      residuals: [],
      fits: [fit("none", 0.0177), fit("1/x", 0.0151), fit("1/x2", 0.0149)],
      heteroscedasticity: {
        level_low: 1,
        level_high: 200,
        n_low: 3,
        n_high: 3,
        var_low: 1e-7,
        var_high: 2.5e-4,
        f_statistic: 2574.4,
        f_critical: 99,
        p_value: 0.0004,
        alpha: 0.01,
        significant: true,
      },
    },
  ],
};

export const recoveryOutput: RecoveryOutput = {
  kind: "recovery",
  overall_mean_pct: 62,
  overall_rsd_pct: 20,
  n: 3,
  method: null,
  groups: [
    {
      analyte: "carbendazim",
      spike_ng_g: 10,
      n: 3,
      mean_pct: 46,
      sd_pct: 2,
      rsd_pct: 4.3,
      mean_no_is_pct: 30,
      grubbs: {
        n: 3,
        g_statistic: 1.15,
        g_critical: 1.155,
        alpha: 0.05,
        suspect_injection_id: "S-03",
        suspect_value: 49,
        is_outlier: false,
      },
    },
  ],
  uncertainty: [
    {
      analyte: "carbendazim",
      levels: 1,
      u_rw_pct: 4.3,
      rms_bias_pct: 54,
      u_cref_pct: 0,
      u_bias_pct: 54,
      u_combined_pct: 54.2,
      coverage_factor: 2,
      expanded_pct: 108.4,
    },
  ],
  rows: ["S-01", "S-02", "S-03"].map((id, i) => ({
    injection_id: id,
    sample_id: `R10-${i + 1}`,
    analyte: "carbendazim",
    spike_ng_g: 10,
    measured_ng_g: 4.6,
    recovery_pct: 46,
    recovery_no_is_pct: 30,
  })),
};

export function resultOf(output: AnalysisResultOut["output"], id = 20): AnalysisResultOut {
  return {
    id,
    experiment_id: 7,
    kind: output.kind,
    method_version: `${output.kind}@1`,
    input_dataset_ids: [13],
    input_fingerprint: "f".repeat(64),
    parameters: {},
    output,
    flags: [],
    created_at: "2026-11-03T00:00:00Z",
  };
}
