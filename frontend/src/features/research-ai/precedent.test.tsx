import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { PrecedentsOut } from "@/api/types";
import { PrecedentCard } from "./PrecedentCard";

vi.mock("@/api/queries", () => ({
  useProjects: () => ({
    data: [
      { id: 1, name: "잔류농약 QuEChERS", experiment_count: 30 },
      { id: 2, name: "발효식품 유기산", experiment_count: 12 },
    ],
  }),
}));
afterEach(cleanup);

const summary = (id: number, project_id: number, code: string) => ({
  id,
  project_id,
  code,
  title: `${code} 제목`,
  author: "김연구",
  performed_on: "2026-06-17",
  parent_experiment_id: null,
  dataset_kinds: [],
});

const data: PrecedentsOut = {
  experiment_id: 36,
  failed: true,
  failed_analytes: ["citric acid"],
  changed_keys: ["cleanup_sorbent"],
  cases: [
    {
      experiment: summary(9, 1, "#009"),
      project_name: "잔류농약 QuEChERS",
      failed_analytes: ["tebuconazole"],
      recovery_mean_pct: 73.2,
      source_result_ids: [1],
      matches: [{ kind: "same_change", label: "추출 용매 변경 후 실패", analytes: [] }],
      score: 2,
      decisions: [
        {
          decision_id: 3,
          proposal_id: 4,
          proposal_title: "단일 변수: 추출 용매만 변경",
          action: "reject",
          reason_category: "resource",
          rationale: "[컬럼 압력 우려] 메탄올 단독 재시험은 하지 않는다.",
          decided_by: "김연구",
          changes: [],
        },
      ],
      hypotheses: [],
    },
  ],
  condition_usage: [
    {
      key: "cleanup_sorbent",
      label: "정제 흡착제 (d-SPE)",
      value: "PSA 50 mg + MgSO4 150 mg",
      project_id: 1,
      project_name: "잔류농약 QuEChERS",
      experiments: [{ experiment_id: 1, code: "#001", title: "SOP v1", qc_status: "warning", recovery_mean_pct: 82.5, source_result_ids: [] }],
      fail_count: 0,
      analyzed_count: 1,
    },
  ],
};

describe("PrecedentCard", () => {
  it("leads with the past case, what was concluded, and the other project's use of the value", () => {
    render(
      <MemoryRouter>
        <PrecedentCard data={data} currentProjectId={2} />
      </MemoryRouter>,
    );
    expect(screen.getByRole("heading", { name: "과거에 같은 증상이 있었다" })).toBeTruthy();
    expect(screen.getByText("그때 내린 결론")).toBeTruthy();
    expect(screen.getByText(/컬럼 압력 우려/)).toBeTruthy();
    expect(screen.getByText(/기각/)).toBeTruthy(); // the action is a word, not only a color
    const chip = screen.getByRole("link", { name: /#001.*잔류농약.*82\.5%/ });
    expect(chip.getAttribute("href")).toBe("/notebook?project=1&exp=1");
    expect(screen.getByText(/QC 불합격 0\/1/)).toBeTruthy();
  });

  it("renders nothing without a precedent", () => {
    const { container } = render(
      <MemoryRouter>
        <PrecedentCard data={{ ...data, cases: [], condition_usage: [] }} currentProjectId={2} />
      </MemoryRouter>,
    );
    expect(container.textContent).toBe("");
  });
});
