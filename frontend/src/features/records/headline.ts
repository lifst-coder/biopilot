/**
 * Which finding to show first on the Records tab — a fixed order over API data, never a
 * computed number:
 *
 * 1. Cross view: the significant same-protocol operator pair with the largest |Δ| (a
 *    difference the condition block cannot show), else the condition value with the
 *    highest QC fail ratio among values failed at least twice, else the longest gap.
 * 2. Failure view: the largest repeat pattern (the backend sorts patterns by size), else
 *    the most frequent failure type.
 */
import type {
  ConditionRecords,
  FailureArchive,
  FailurePattern,
  OperatorPair,
  OperatorRecords,
  PeriodRecords,
  RecordGap,
  RecordGroup,
} from "@/api/types";

export type RecordsHeadline =
  | { kind: "operator"; pair: OperatorPair }
  | { kind: "condition"; key: string; group: RecordGroup }
  | { kind: "gap"; gap: RecordGap };

export function pickRecordsHeadline(
  operators: OperatorRecords | undefined,
  conditions: ConditionRecords | undefined,
  periods: PeriodRecords | undefined,
): RecordsHeadline | null {
  // pairs arrive largest |Δ| first
  const pair = operators?.pairs.find((p) => p.significant === true);
  if (pair) return { kind: "operator", pair };
  const worst = (conditions?.groups ?? [])
    .filter((g) => g.fail_count >= 2 && g.fail_ratio != null)
    .sort((a, b) => (b.fail_ratio ?? 0) - (a.fail_ratio ?? 0) || b.fail_count - a.fail_count)[0];
  if (worst && conditions) return { kind: "condition", key: conditions.key, group: worst };
  const gap = [...(periods?.gaps ?? [])].sort((a, b) => b.days - a.days)[0];
  if (gap) return { kind: "gap", gap };
  return null;
}

export type FailureHeadline =
  | { kind: "pattern"; pattern: FailurePattern }
  | { kind: "type"; label: string; count: number; experimentIds: number[] };

export function pickFailureHeadline(archive: FailureArchive | undefined): FailureHeadline | null {
  if (!archive) return null;
  const pattern = archive.patterns[0];
  if (pattern) return { kind: "pattern", pattern };
  const type = archive.types[0];
  if (type) return { kind: "type", label: type.label, count: type.count, experimentIds: type.experiment_ids };
  return null;
}
