import { describe, expect, it } from "vitest";
import type { ConditionRecords, FailureArchive, OperatorRecords, PeriodRecords, RecordExperiment, RecordGroup } from "@/api/types";
import { pickFailureHeadline, pickRecordsHeadline } from "./headline";

const exp = (id: number, author: string): RecordExperiment => ({
  experiment_id: id,
  project_id: 1,
  code: `#${id}`,
  title: "",
  author,
  performed_on: "2026-10-29",
  recovery_mean_pct: 80,
  recovery_rsd_pct: 5,
  qc_status: "pass",
  source_result_ids: [],
});
const group = (key: string, fail: number, analyzed: number, ratio: number | null): RecordGroup => ({
  key,
  experiments: [],
  experiment_count: analyzed,
  analyzed_count: analyzed,
  recovery_n: analyzed,
  fail_count: fail,
  fail_ratio: ratio,
  pass_count: analyzed - fail,
  pass_ratio: null,
});
const pair = (delta: number, significant: boolean) => ({
  experiment_a: exp(1, "김"),
  experiment_b: exp(2, "이"),
  days_apart: 1,
  condition_key_count: 13,
  recovery_delta_pct_points: delta,
  p_value: significant ? 0.001 : 0.4,
  alpha: 0.05,
  significant,
  significant_analytes: [],
});
const operators = (pairs: ReturnType<typeof pair>[]): OperatorRecords => ({ project_ids: [1], window_days: 14, authors: [], pairs });
const conditions = (groups: RecordGroup[]): ConditionRecords => ({ key: "cleanup_sorbent", project_ids: [1], groups });
const periods: PeriodRecords = {
  project_ids: [1],
  gap_days: 21,
  months: [],
  gaps: [{ start: "2026-07-09", end: "2026-08-04", days: 26, before: [], after: [] }],
};

describe("pickRecordsHeadline", () => {
  it("prefers the first significant same-protocol operator pair", () => {
    const h = pickRecordsHeadline(operators([pair(-9, false), pair(8, true)]), conditions([group("GCB", 3, 3, 1)]), periods);
    expect(h?.kind).toBe("operator");
    expect(h?.kind === "operator" && h.pair.recovery_delta_pct_points).toBe(8);
  });
  it("falls back to the condition value with the highest fail ratio (≥ 2 fails), then the gap", () => {
    const h = pickRecordsHeadline(
      operators([pair(3, false)]),
      conditions([group("C18", 3, 23, 0.13), group("GCB", 3, 3, 1), group("X", 1, 1, 1)]),
      periods,
    );
    expect(h?.kind === "condition" && h.group.key).toBe("GCB");
    expect(pickRecordsHeadline(operators([]), conditions([]), periods)?.kind).toBe("gap");
    expect(pickRecordsHeadline(undefined, undefined, undefined)).toBeNull();
  });
});

describe("pickFailureHeadline", () => {
  const base: FailureArchive = { project_ids: [1], experiment_count: 3, analyzed_count: 3, failure_count: 0, types: [], patterns: [], failures: [] };
  it("shows the largest pattern, else the most frequent type, else nothing", () => {
    expect(pickFailureHeadline(base)).toBeNull();
    const typed = { ...base, failure_count: 2, types: [{ id: "no_change", label: "조건 변경 없이", count: 2, experiment_ids: [1, 2] }] };
    expect(pickFailureHeadline(typed)?.kind).toBe("type");
    const pattern = { id: "p", experiment_ids: [1, 2], codes: ["#1", "#2"], project_ids: [1], shared_analytes: ["a"], links: [], resolution_changes: [] };
    expect(pickFailureHeadline({ ...typed, patterns: [pattern] })?.kind).toBe("pattern");
  });
});
