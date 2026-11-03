/** Notebook-local aliases of generated API types (shared `api/types.ts` is not ours to edit). */
import type { Schemas } from "@/api/client";

export type DatasetKind = Schemas["DatasetCreate"]["kind"];
export type DatasetValidation = Schemas["DatasetValidation"];
export type CsvIssue = Schemas["CsvIssue"];
export type ConditionIssue = Schemas["ConditionIssue"];
export type ConditionField = Schemas["ConditionField"];
export type ConditionBlockValue = Schemas["ConditionBlock"];
export type ExperimentCreate = Schemas["ExperimentCreate"];
export type ExperimentOut = Schemas["ExperimentOut"];
export type HistoryEntry = Schemas["HistoryEntry"];
export type AuditEventOut = Schemas["AuditEventOut"];
export type ImportPreview = Schemas["ImportPreview"];
export type ProtocolTemplateOut = Schemas["ProtocolTemplateOut"];
export type AttachmentFileOut = Schemas["AttachmentFileOut"];
export type DatasetOut = Schemas["DatasetOut"];

/** Dataset kinds offered in upload forms, in display order. */
export const DATASET_KINDS: { value: DatasetKind; label: string }[] = [
  { value: "calibration", label: "검량선 (calibration)" },
  { value: "recovery", label: "회수율 (recovery)" },
  { value: "matrix_effect", label: "매트릭스 효과 (matrix_effect)" },
  { value: "ion_ratio", label: "이온비 (ion_ratio)" },
  { value: "other", label: "기타 (other)" },
];

/** Byte counts as KB/MB text (file metadata, not a measurement). */
export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/** Message of an API error (backend `{code, message}` envelope) or any thrown value. */
export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
