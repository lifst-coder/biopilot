/** Partner schema aliases used by the Research AI tab (shared `api/types.ts` is not ours). */
import type { Schemas } from "@/api/client";

export type CriticAssessment = Schemas["CriticAssessment"];
export type CriticArgument = Schemas["CriticArgument"];
export type MissingControl = Schemas["MissingControl"];
export type AlternativeExplanation = Schemas["AlternativeExplanation"];
export type DecisionFeedback = Schemas["DecisionFeedback"];
export type ExperimentDesign = Schemas["ExperimentDesign"];
export type DecisionHistoryEntry = Schemas["DecisionHistoryEntry"];
export type HypothesisStatusChange = Schemas["HypothesisStatusChange"];
export type Evidence = Schemas["Evidence"];

export const VERDICT_LABEL: Record<CriticAssessment["verdict"], string> = {
  indeterminate: "현재 데이터로 확정 불가",
  supported: "지지됨",
  refuted: "반박됨",
  no_issue: "문제 없음",
};

export const BASIS_LABEL: Record<CriticArgument["basis"], string> = {
  data: "데이터",
  domain_rule: "도메인 지식",
  decision: "연구자 결정",
};

export const STATUS_LABEL: Record<AlternativeExplanation["status"], string> = {
  plausible: "가능성 있음",
  weakened: "약화됨",
  untested: "미검증",
};

export const POWER_LABEL: Record<ExperimentDesign["discriminating_power"], string> = {
  high: "높음",
  medium: "중간",
  low: "낮음",
};
