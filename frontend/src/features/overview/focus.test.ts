import { describe, expect, it } from "vitest";
import type { AcceptanceCriteria, TrendPoint } from "@/api/types";
import { pickFocus } from "./FocusCard";

const point = (id: number, mean: number | null, flags = 0): TrendPoint => ({
  experiment_id: id,
  code: `#${id}`,
  performed_on: "2026-10-01",
  recovery_mean_pct: mean,
  recovery_rsd_pct: null,
  flag_count: flags,
  source_result_ids: [],
});
const criteria = { recovery_min_pct: 70, recovery_max_pct: 120 } as AcceptanceCriteria;

describe("pickFocus", () => {
  it("prefers the most recent experiment outside the recovery criterion", () => {
    expect(pickFocus([point(1, 90), point(2, 50, 3), point(3, 95)], criteria)?.experiment_id).toBe(2);
  });
  it("prefers an out-of-range experiment that still has unresolved proposals or hypotheses", () => {
    const points = [point(1, 90), point(2, 50, 3), point(3, 55, 2), point(4, 95)];
    expect(pickFocus(points, criteria, new Set([2]))?.experiment_id).toBe(2);
    expect(pickFocus(points, criteria, new Set([4]))?.experiment_id).toBe(3);
  });
  it("then the most recent one with flags, then the latest analysed", () => {
    expect(pickFocus([point(1, 90, 2), point(2, 95), point(3, null)], criteria)?.experiment_id).toBe(1);
    expect(pickFocus([point(1, 90), point(2, 95), point(3, null)], criteria)?.experiment_id).toBe(2);
    expect(pickFocus([], criteria)).toBeNull();
  });
});
