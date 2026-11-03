/** Display labels for analysis enums (presentation only). */
import type { BadgeTone } from "@/components";
import type { QCFlag, QCStatus, Weighting } from "./types";

export const FLAG_LABELS: Record<QCFlag["code"], string> = {
  recovery_out_of_range: "회수율 범위 이탈",
  recovery_rsd_high: "회수율 RSD 초과",
  calibration_r2_low: "R² 미달",
  calibration_back_calc_error: "역산 정확도 초과",
  is_suppression: "IS 억제",
  is_enhancement: "IS 증강",
  matrix_effect_significant: "유의한 매트릭스 효과",
  outlier_suspected: "이상치 의심 (Grubbs)",
  uncertainty_high: "확장 불확도 초과",
  ion_ratio_out_of_range: "이온비 허용범위 이탈",
  loq_above_lowest_level: "LOQ > 최저 검량 수준",
};

export const WEIGHTING_LABELS: Record<Weighting, string> = {
  none: "비가중",
  "1/x": "1/x",
  "1/x2": "1/x²",
};

export const LIMIT_METHOD_LABELS: Record<string, string> = {
  residual_sd: "잔차 SD (s_y/x)",
  intercept_sd: "절편 SD",
  low_level_replicates: "최저 수준 반복",
};

export const QC_STATUS: Record<QCStatus, { label: string; tone: BadgeTone }> = {
  pass: { label: "합격", tone: "ok" },
  warning: { label: "검토 필요", tone: "warn" },
  fail: { label: "불합격", tone: "crit" },
  not_analyzed: { label: "미분석", tone: "neutral" },
};
