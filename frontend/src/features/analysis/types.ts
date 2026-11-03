/** Analysis-tab aliases of generated API types (kept local to the feature). */
import type { Schemas } from "@/api/client";

export type CalibrationOutput = Schemas["CalibrationOutput"];
export type AnalyteCalibrationOut = Schemas["AnalyteCalibrationOut"];
export type CalibrationFitOut = Schemas["CalibrationFitOut"];
export type ResidualOut = Schemas["ResidualOut"];
export type RecoveryOutput = Schemas["RecoveryOutput"];
export type RecoveryRowOut = Schemas["RecoveryRowOut"];
export type ISResponseOutput = Schemas["ISResponseOutput"];
export type ISInjectionOut = Schemas["ISInjectionOut"];
export type MatrixEffectOutput = Schemas["MatrixEffectOutput"];
export type LimitsOutput = Schemas["LimitsOutput"];
export type IonRatioOutput = Schemas["IonRatioOutput"];
export type MethodDoc = Schemas["MethodDoc"];
export type AcceptanceCriteria = Schemas["AcceptanceCriteria"];
export type CriteriaVersionOut = Schemas["CriteriaVersionOut"];
export type AnalyteVerdict = Schemas["AnalyteVerdict"];
export type QCFlag = Schemas["QCFlag"];
export type Weighting = CalibrationFitOut["weighting"];
export type QCStatus = Schemas["ExperimentMetrics"]["qc_status"];
