import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { LineageView } from "../LineageView";
import { RunView } from "../RunView";
import { mockApi, renderWithProviders, type Call } from "./testUtils";

vi.mock("@/api/client", async (orig) => (await import("./testUtils")).mockClientModule(orig));
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const REF = (id: number, v: string) => ({
  template_id: id,
  name: "SOP",
  version: id,
  display_version: v,
  created_at: "2026-11-04T00:00:00Z",
  author: "김연구",
  source_experiment_id: null,
  source_experiment_code: null,
});

const cond = (actual: number | null) => ({
  key: "extraction_time_min",
  label: "추출 시간 (min)",
  unit: "min",
  value_type: "number",
  planned: 10,
  actual,
  deviated: actual !== null && actual !== 10,
  note: actual !== null ? "타이머" : "",
});

const RUN = (actual: number | null) => ({
  id: 5,
  project_id: 1,
  template: REF(2, "v2"),
  operator: "김연구",
  status: "in_progress",
  started_at: "2026-11-04T00:00:00Z",
  completed_at: null,
  experiment_id: null,
  steps: [
    { index: 0, title: "시료 칭량", detail: "", done: true, done_at: null, conditions: [], notes: [] },
    { index: 1, title: "용매 추출", detail: "진탕한다", done: false, done_at: null, conditions: [cond(actual)], notes: [] },
  ],
  deviations:
    actual === null
      ? []
      : [
          {
            step_index: 1,
            step_title: "용매 추출",
            kind: "value",
            key: "extraction_time_min",
            label: "추출 시간 (min)",
            unit: "min",
            planned: 10,
            actual,
            note: "타이머",
          },
        ],
  done_count: 1,
  step_count: 2,
  entry_count: 1,
  current_step_index: 1,
});

describe("RunView", () => {
  it("shows the current step's planned value and records a different actual value", async () => {
    let actual: number | null = null;
    const calls = mockApi({
      "GET /api/eln/protocol-runs/5": () => RUN(actual),
      "POST /api/eln/protocol-runs/5/entries": (c: Call) => {
        actual = Number((c.body as { value: string }).value);
        return RUN(actual);
      },
      "GET /api/eln/projects/1/experiment-draft": () => ({ source: "blank", suggested_code: "#031", draft: {} }),
    });
    renderWithProviders(<RunView runId={5} go={vi.fn()} />);
    expect((await screen.findAllByText("용매 추출")).length).toBeGreaterThan(0);
    expect(screen.getByText("10 min")).toBeTruthy();
    expect(screen.getByText("1/2단계 완료")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "값이 달랐음" }));
    fireEvent.change(screen.getByLabelText(/실제 추출 시간/), { target: { value: "7" } });
    fireEvent.change(screen.getByLabelText("이유 (선택)"), { target: { value: "타이머" } });
    fireEvent.click(screen.getByRole("button", { name: "기록" }));
    await screen.findByText(/프로토콜과 다름/);
    const post = calls.find((c) => c.method === "POST")!;
    expect(post.body).toMatchObject({ kind: "actual", step_index: 1, key: "extraction_time_min", value: "7", note: "타이머" });
    expect(screen.getByText("2단계 용매 추출: 추출 시간 (min) 10 min → 7 min (타이머)")).toBeTruthy();
  });
});

describe("LineageView", () => {
  it("answers which version passes QC best from stored counts and lists changes", async () => {
    const group = (id: number, pass: number, analyzed: number, ratio: number) => ({
      key: String(id),
      value: id,
      experiments: [],
      experiment_count: analyzed,
      analyzed_count: analyzed,
      recovery_n: 0,
      fail_count: analyzed - pass,
      fail_ratio: null,
      pass_count: pass,
      pass_ratio: ratio,
    });
    mockApi({
      "GET /api/eln/projects/1/protocol-lineage": () => ({
        project_id: 1,
        lineages: [
          {
            name: "SOP",
            versions: [
              { template: REF(1, "v1"), description: "", changes_from_previous: [], experiments: [], first_used_on: "2026-05-11", last_used_on: "2026-05-21" },
              {
                template: REF(2, "v2"),
                description: "",
                changes_from_previous: [
                  { key: "sample_mass_g", label: "시료량 (g)", unit: "g", kind: "changed", before: 15, after: 10 },
                ],
                experiments: [],
                first_used_on: "2026-09-08",
                last_used_on: "2026-10-30",
              },
            ],
          },
        ],
      }),
      "GET /api/analysis/records/protocols": () => ({ project_ids: [1], groups: [group(1, 4, 4, 1), group(2, 10, 13, 0.77)] }),
      "GET /api/eln/projects/1/protocol-runs": () => ({ items: [] }),
      "GET /api/eln/projects/1/protocol-templates": () => ({ project_id: 1, total: 0, items: [] }),
    });
    renderWithProviders(<LineageView projectId={1} go={vi.fn()} />);
    await waitFor(() => expect(screen.getByText(/QC 통과율이 가장 높은 버전은/)).toBeTruthy());
    expect(screen.getByText(/QC 통과율이 가장 높은 버전은/).textContent).toContain("v1");
    expect(screen.getByText(/최신 버전\(v2\): 10\/13 통과/)).toBeTruthy();
    expect(screen.getByText("바뀐 조건: 시료량 (g)")).toBeTruthy();
    expect(screen.getByText("15 g")).toBeTruthy();
    expect(screen.getByText("5/11–5/21")).toBeTruthy();
  });
});
