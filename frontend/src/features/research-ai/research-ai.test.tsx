import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it } from "vitest";
import type { ProposalOut } from "@/api/types";
import { CriticAssessmentView, splitReason } from "./CriticAssessmentView";
import { DecisionHistoryCard } from "./DecisionHistoryCard";
import { DesignDetails } from "./DesignDetails";
import { ProposalCard } from "./ProposalCard";
import type { CriticAssessment, DecisionHistoryEntry, Evidence, ExperimentDesign } from "./types";

const evidence: Evidence[] = [
  {
    key: "E1",
    source: "analysis",
    ref_type: "analysis.AnalysisResult",
    ref_id: 3,
    label: "#024 평균 회수율",
    value: 61.97,
    unit: "%",
    text: null,
  },
  {
    key: "E9",
    source: "partner",
    ref_type: "partner.Decision",
    ref_id: 1,
    label: "P1 기각 사유",
    value: null,
    unit: null,
    text: "블랭크 확보 불가",
  },
];

const assessment: CriticAssessment = {
  id: "recovery_cause",
  question: "#024 회수율 저하의 원인: 전처리 손실인가, 매트릭스 효과인가?",
  claim: "#024의 회수율 저하는 전처리 변경에 따른 손실 때문이다",
  verdict: "indeterminate",
  verdict_reason: "전처리 손실과 매트릭스 효과를 현재 데이터로 구분 불가",
  supporting_evidence: [{ statement: "평균 회수율이 낮아졌다", evidence_keys: ["E1"], basis: "data" }],
  opposing_evidence: [{ statement: "IS 응답 이탈", evidence_keys: [], basis: "data" }],
  missing_controls: [
    {
      id: "pre_post_spike",
      name: "추출 전·후 첨가 비교",
      purpose: "RE와 ME 분리",
      distinguishes: [],
      evidence_keys: ["E9"],
      decision_note: "P1 기각 (사유: '블랭크 확보 불가')",
    },
  ],
  alternative_explanations: [
    {
      id: "matrix_suppression",
      label: "매트릭스 효과 (이온화 억제)",
      mechanism: "이온화 억제",
      supporting: [],
      opposing: [],
      status: "plausible",
    },
  ],
  undetermined_reasons: [{ statement: "용매 검량선 기준 겉보기 회수율", evidence_keys: [], basis: "domain_rule" }],
};

const design: ExperimentDesign = {
  template_id: "pre_post_spike",
  objective: "RE와 ME 분리",
  variables: [
    { key: "spike_stage", label: "첨가 시점", role: "varied", levels: ["pre", "post"] },
    { key: "ph", label: "pH", role: "fixed", levels: [5] },
  ],
  controls: [{ name: "블랭크 추출액", purpose: "간섭 확인" }],
  replicates: 5,
  replicates_basis: "#018 첨가 수준당 반복 수 기준",
  replicates_evidence_key: "E35",
  measurements: ["면적"],
  expected_outcomes: [{ observation: "post ≈ 용매", interpretation: "전처리 손실", supports: [] }],
  discriminating_power: "high",
  discriminates: [],
  power_rationale: "직접 측정",
  addresses_controls: ["pre_post_spike"],
  basis_experiment_ids: [7, 1],
  requires: ["blank_matrix"],
};

const codeOf = (id: number) => ({ 1: "#018", 7: "#024" })[id] ?? `#${id}`;

function wrap(children: ReactNode) {
  return <QueryClientProvider client={new QueryClient()}>{children}</QueryClientProvider>;
}

describe("Research AI tab", () => {
  it("renders every Research Critic section with stored evidence values", () => {
    render(<CriticAssessmentView assessment={assessment} evidence={evidence} feedback={[]} />);
    for (const title of ["지지 근거", "반대 근거", "누락 대조군", "대안 설명", "현재 데이터로 확정 불가한 이유"]) {
      expect(screen.getByText(title)).toBeTruthy();
    }
    expect(screen.getByText("현재 데이터로 확정 불가")).toBeTruthy();
    expect(screen.getByTestId("verdict-reason").textContent).toContain("구분 불가");
    expect(screen.getByText("62.0%")).toBeTruthy(); // formatted from Evidence.value
    expect(screen.getByText(/결정 이력: P1 기각/)).toBeTruthy();
    expect(screen.getByText("추정")).toBeTruthy();
    expect(screen.getByText("도메인 지식")).toBeTruthy();
  });

  it("splits a verdict reason into conclusion and detail at the first em dash only", () => {
    expect(splitReason("구분 불가 — 비교 A, B 데이터가 없다 — 추가")).toEqual(["구분 불가", "비교 A, B 데이터가 없다 — 추가"]);
    expect(splitReason("근거가 충분하다")).toEqual(["근거가 충분하다", null]);
  });

  it("shows designer fields: variables, controls, replicates, power, basis experiments", () => {
    render(<DesignDetails design={design} codeOf={codeOf} />);
    expect(screen.getByText("첨가 시점")).toBeTruthy();
    expect(screen.getByText(/블랭크 추출액/)).toBeTruthy();
    expect(screen.getByText("5")).toBeTruthy();
    expect(screen.getByText("높음")).toBeTruthy();
    expect(screen.getByText("#024, #018")).toBeTruthy();
  });

  it("lists decisions with rationale and the critiques that reflected them", () => {
    const entry: DecisionHistoryEntry = {
      decision: {
        id: 1,
        proposal_id: 1,
        action: "reject",
        rationale: "블랭크 확보 불가",
        modifications: [],
        decided_by: "researcher",
        reason_category: "resource",
        constraints: ["blank_matrix"],
        created_at: "2026-11-03T00:00:00Z",
      },
      proposal_id: 1,
      proposal_title: "추출 전·후 첨가 비교",
      proposal_changes: [],
      experiment_id: 7,
      experiment_code: "#024",
      reflected_in_critique_ids: [2],
    };
    const { rerender } = render(<DecisionHistoryCard entries={[entry]} />);
    expect(screen.getByText("사유: 블랭크 확보 불가")).toBeTruthy();
    expect(screen.getByText("반영된 비판: #2")).toBeTruthy();
    rerender(<DecisionHistoryCard entries={[]} />);
    expect(screen.getByText("기록된 결정이 없습니다.")).toBeTruthy();
  });

  it("proposal card shows priority, superseded proposals and the recorded decision", () => {
    const proposal: ProposalOut = {
      id: 4,
      project_id: 1,
      experiment_id: 7,
      critique_id: 2,
      hypothesis_id: null,
      title: "표준물 첨가법",
      description: "블랭크 불필요",
      changes: [{ key: "calibration_type", value: "standard-addition" }],
      evidence_keys: [],
      status: "rejected",
      origin: "ai:rules",
      decision: {
        id: 2,
        proposal_id: 4,
        action: "reject",
        rationale: "장비 시간 부족",
        modifications: [],
        decided_by: "researcher",
        reason_category: "resource",
        constraints: ["extra_injections"],
        created_at: "2026-11-03T00:00:00Z",
      },
      design,
      base_experiment_id: 7,
      priority: 6,
      priority_factors: [{ name: "판별력", points: 2, detail: "medium", evidence_keys: [] }],
      signature: "abc",
      supersedes_proposal_ids: [1],
      implementing_changes: [],
      created_at: "2026-11-03T00:00:00Z",
    };
    render(wrap(<ProposalCard proposal={proposal} codeOf={codeOf} />));
    expect(screen.getByText("우선순위 6")).toBeTruthy();
    expect(screen.getByText("기각 사유 반영: P1 대체")).toBeTruthy();
    expect(screen.getByText("사유: 장비 시간 부족")).toBeTruthy();
    expect(screen.queryByText("실험 초안 보기")).toBeNull(); // rejected → no draft
  });
});
