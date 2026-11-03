import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { AcceptanceCriteria } from "./types";

const createMutate = vi.fn();
const runMutate = vi.fn();
const criteria: AcceptanceCriteria = {
  source: "SANTE/11312/2021",
  recovery_min_pct: 70,
  recovery_max_pct: 120,
  rsd_max_pct: 20,
  r_squared_min: 0.99,
  back_calc_tolerance_pct: 20,
  is_response_min_pct: 50,
  is_response_max_pct: 150,
  matrix_effect_abs_max_pct: 20,
  expanded_uncertainty_max_pct: 50,
  ion_ratio_tolerance_pct: 30,
  lod_k: 3,
  lod_range_factor: 10,
  loq_k: 10,
  grubbs_alpha: 0.05,
  heteroscedasticity_alpha: 0.01,
  comparison_alpha: 0.05,
  coverage_factor: 2,
  spike_uncertainty_pct: 0,
};
const version = { id: null, project_id: 1, version: 0, label: "default", criteria, note: "기본값", created_at: null };

vi.mock("@/api/queries", () => ({
  useProjectCriteria: () => ({
    isPending: false,
    isError: false,
    data: { project_id: 1, active: version, history: [version] },
  }),
  useCreateCriteria: () => ({ mutate: createMutate, isPending: false, error: null }),
  useRunAnalysis: () => ({ mutate: runMutate, isPending: false, error: null, data: { created: 4, reused: 0, skipped: [] } }),
}));

const { CriteriaPanel, CRITERIA_FIELDS } = await import("./CriteriaPanel");

describe("CriteriaPanel", () => {
  it("covers every numeric criterion", () => {
    const keys = Object.keys(criteria).filter((k) => k !== "source").sort();
    expect(CRITERIA_FIELDS.map((f) => f.key).sort()).toEqual(keys);
  });

  it("saves a new version with the edited thresholds and re-runs", () => {
    render(<CriteriaPanel projectId={1} experimentId={7} />);
    expect(screen.getAllByText("default").length).toBeGreaterThan(0);
    const save = screen.getByRole("button", { name: /새 기준 버전 저장 \(0개 변경\)/ });
    expect((save as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(screen.getByLabelText("회수율 하한 (%)"), { target: { value: "60" } });
    fireEvent.change(screen.getByPlaceholderText(/변경 사유/), { target: { value: "내부 기준" } });
    fireEvent.click(screen.getByRole("button", { name: /1개 변경/ }));
    expect(createMutate).toHaveBeenCalledOnce();
    const [{ projectId, body }] = createMutate.mock.calls[0] as [{ projectId: number; body: { criteria: AcceptanceCriteria; note: string } }];
    expect(projectId).toBe(1);
    expect(body.criteria.recovery_min_pct).toBe(60);
    expect(body.criteria.recovery_max_pct).toBe(120);
    expect(body.note).toBe("내부 기준");
    fireEvent.click(screen.getByRole("button", { name: "현재 기준으로 재분석" }));
    expect(runMutate).toHaveBeenCalledWith(7);
    expect(screen.getByText(/새 결과 4/)).toBeTruthy();
  });
});
