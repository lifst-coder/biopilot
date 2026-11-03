import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Schemas } from "@/api/client";
import {
  experimentOf,
  filterGraph,
  layoutGraph,
  neighbours,
  truncate,
  type KGEdge,
  type KGNode,
} from "./graphLayout";
import { splitHighlights } from "./highlight";
import { KnowledgeGraphView } from "./KnowledgeGraphView";

afterEach(cleanup);

const node = (id: string, type: KGNode["type"], label: string, extra: Partial<KGNode> = {}): KGNode => ({
  id,
  type,
  label,
  ref_type: null,
  ref_id: null,
  experiment_id: null,
  attrs: {},
  ...extra,
});
const edge = (source: string, target: string, relation: KGEdge["relation"]): KGEdge => ({
  source,
  target,
  relation,
  source_ref: null,
  attrs: {},
});

const NODES: KGNode[] = [
  node("experiment:1", "experiment", "#018 기준", { ref_type: "eln.Experiment", ref_id: 1, experiment_id: 1 }),
  node("experiment:7", "experiment", "#024 GCB", { ref_type: "eln.Experiment", ref_id: 7, experiment_id: 7 }),
  node("analyte:carbendazim", "analyte", "carbendazim"),
  node("condition:ph=5", "condition", "pH: 5"),
  node("hypothesis:1", "hypothesis", "GCB 흡착 손실", { ref_type: "partner.Hypothesis", ref_id: 1, experiment_id: 7 }),
];
const EDGES: KGEdge[] = [
  edge("experiment:7", "experiment:1", "derived_from"),
  edge("experiment:7", "analyte:carbendazim", "measures"),
  edge("experiment:1", "condition:ph=5", "uses_condition"),
  edge("experiment:7", "hypothesis:1", "raises_hypothesis"),
];
const GRAPH: Schemas["KnowledgeGraph"] = {
  project_id: 1,
  nodes: NODES,
  edges: EDGES,
  counts: { experiment: 2, analyte: 1, condition: 1, hypothesis: 1 },
  refresh: { mode: "incremental", applied_events: 1, last_event_id: 52 },
};

function Where() {
  const loc = useLocation();
  return <p data-testid="where">{loc.pathname + loc.search}</p>;
}

function renderGraph() {
  return render(
    <MemoryRouter initialEntries={["/overview"]}>
      <Routes>
        <Route path="/overview" element={<KnowledgeGraphView graph={GRAPH} />} />
        <Route path="/notebook" element={<Where />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("graph layout helpers", () => {
  it("places each type column left→right and keeps every node", () => {
    const { positions, width, height } = layoutGraph(NODES);
    expect(positions.size).toBe(NODES.length);
    const x = (id: string) => positions.get(id)!.x;
    expect(x("condition:ph=5")).toBeLessThan(x("experiment:1"));
    expect(x("experiment:1")).toBeLessThan(x("analyte:carbendazim"));
    expect(x("analyte:carbendazim")).toBeLessThan(x("hypothesis:1"));
    expect(width).toBeGreaterThan(0);
    expect(height).toBeGreaterThan(0);
  });

  it("filters nodes by type and drops dangling edges", () => {
    const { nodes, edges } = filterGraph(NODES, EDGES, new Set(["experiment", "analyte"]));
    expect(nodes.map((n) => n.id)).toEqual(["experiment:1", "experiment:7", "analyte:carbendazim"]);
    expect(edges.map((e) => e.relation)).toEqual(["derived_from", "measures"]);
  });

  it("finds neighbours, experiment links and truncates labels", () => {
    expect([...neighbours("experiment:1", EDGES)].sort()).toEqual(["condition:ph=5", "experiment:1", "experiment:7"]);
    expect(experimentOf(NODES[1]!)).toBe(7);
    expect(experimentOf(NODES[4]!)).toBe(7);
    expect(experimentOf(NODES[2]!)).toBeNull();
    expect(truncate("가".repeat(30), 5)).toBe("가가가가…");
  });
});

describe("splitHighlights", () => {
  it("marks server spans, merging overlaps and clamping bounds", () => {
    expect(splitHighlights("GCB 정제 GCB", [[0, 3], [7, 99], [1, 2]])).toEqual([
      { text: "GCB", mark: true },
      { text: " 정제 ", mark: false },
      { text: "GCB", mark: true },
    ]);
    expect(splitHighlights("abc", [])).toEqual([{ text: "abc", mark: false }]);
  });
});

describe("KnowledgeGraphView", () => {
  it("renders filter chips with API counts and hides conditions by default", () => {
    renderGraph();
    expect(screen.getByRole("button", { name: "실험 2" }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByRole("button", { name: "조건 1" }).getAttribute("aria-pressed")).toBe("false");
    expect(screen.queryByRole("button", { name: "조건: pH: 5" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "조건 1" }));
    expect(screen.getByRole("button", { name: "조건: pH: 5" })).toBeTruthy();
    expect(screen.getByText(/이벤트 #52/)).toBeTruthy();
  });

  it("opens the experiment when an experiment node is clicked", () => {
    renderGraph();
    fireEvent.click(screen.getByRole("button", { name: "실험: #024 GCB" }));
    expect(screen.getByTestId("where").textContent).toBe("/notebook?exp=7");
  });

  it("selecting another node lists linked experiments (keyboard accessible)", () => {
    renderGraph();
    const hyp = screen.getByRole("button", { name: "가설: GCB 흡착 손실" });
    fireEvent.keyDown(hyp, { key: "Enter" });
    expect(screen.getByText("출처: partner.Hypothesis #1")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "#024 GCB 열기" }));
    expect(screen.getByTestId("where").textContent).toBe("/notebook?exp=7");
  });

  it("shows an empty state when every type is filtered out", () => {
    renderGraph();
    for (const name of ["실험 2", "분석물 1", "가설 1"]) fireEvent.click(screen.getByRole("button", { name }));
    expect(screen.getByText(/표시할 노드가 없습니다/)).toBeTruthy();
  });
});

const { searchData, recallData } = vi.hoisted(() => {
  const hit = (experiment_id: number, code: string, project_id: number, snippet: string) => ({
    experiment_id,
    code,
    project_id,
    field: "raw_note",
    snippet,
    score: 2.5,
    highlights: [[0, 3]],
    source: { ref_type: "eln.Experiment", ref_id: experiment_id, field: "raw_note", experiment_id },
  });
  const exp = (id: number, project_id: number, code: string, title: string) => ({
    experiment: { id, project_id, code, title, author: "", performed_on: "2026-10-20", parent_experiment_id: 1, dataset_kinds: [] },
    score: 3,
    reasons: [],
  });
  return {
    searchData: (all: boolean) => [
      hit(7, "#024", 1, "GCB 정제 도입"),
      ...(all ? [hit(40, "#OA06", 2, "GCB 대신 PSA 정제")] : []),
    ],
    recallData: (q: string, all: boolean) => ({
      query: q,
      terms: [{ term: "gcb", facet: "condition", matches: [] }],
      experiments: [exp(7, 1, "#024", "변경 프로토콜"), ...(all ? [exp(40, 2, "#OA06", "농약 SOP 정제 적용")] : [])],
      protocols: [],
      results: [],
      project_ids: all ? [1, 2] : [1],
    }),
  };
});

const searchResult = (q: string, all: boolean) =>
  q
    ? { isLoading: false, isError: false, isSuccess: true, data: searchData(all) }
    : { isLoading: false, isError: false, isSuccess: false, data: undefined };

vi.mock("@/api/queries", () => ({
  useProjects: () => ({
    data: [
      { id: 1, name: "잔류농약 QuEChERS", experiment_count: 30 },
      { id: 2, name: "발효식품 유기산", experiment_count: 12 },
    ],
  }),
  useMemorySearch: (p: number | null, q: string) => searchResult(p == null ? "" : q, false),
  useRecall: (p: number | null, q: string) => ({ data: p != null && q ? recallData(q, false) : undefined }),
  useMemorySearchAll: (q: string) => searchResult(q, true),
  useRecallAll: (q: string) => ({ data: q ? recallData(q, true) : undefined }),
}));

describe("GlobalSearchBar", () => {
  it("shows facets and highlighted hits, and opens the experiment", async () => {
    const { GlobalSearchBar } = await import("./GlobalSearchBar");
    render(
      <MemoryRouter initialEntries={["/overview"]}>
        <Routes>
          <Route path="/overview" element={<GlobalSearchBar projectId={1} />} />
          <Route path="/notebook" element={<Where />} />
        </Routes>
      </MemoryRouter>,
    );
    vi.useFakeTimers();
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "GCB" } });
    await vi.advanceTimersByTimeAsync(300);
    vi.useRealTimers();
    expect(screen.getByText("조건: gcb")).toBeTruthy();
    expect(screen.getAllByText("GCB")[0]!.tagName).toBe("MARK");
    expect(screen.getByRole("list", { name: "관련 실험" }).textContent).toContain("변경 프로토콜");
    fireEvent.click(screen.getByRole("button", { name: /#024 원본 메모/ }));
    expect(screen.getByTestId("where").textContent).toBe("/notebook?project=1&exp=7");
  });

  it("searches every project by default and labels hits from another project", async () => {
    const { GlobalSearchBar } = await import("./GlobalSearchBar");
    render(
      <MemoryRouter initialEntries={["/overview"]}>
        <Routes>
          <Route path="/overview" element={<GlobalSearchBar projectId={1} />} />
          <Route path="/notebook" element={<Where />} />
        </Routes>
      </MemoryRouter>,
    );
    vi.useFakeTimers();
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "GCB" } });
    await vi.advanceTimersByTimeAsync(300);
    vi.useRealTimers();
    const related = screen.getByRole("list", { name: "관련 실험" });
    expect(related.textContent).toContain("#OA06");
    expect(related.textContent).toContain("발효식품"); // the other project is named
    expect(related.textContent?.match(/잔류농약/)).toBeNull(); // the current one is not
    fireEvent.click(screen.getByRole("button", { name: /#OA06 발효식품 원본 메모/ }));
    expect(screen.getByTestId("where").textContent).toBe("/notebook?project=2&exp=40");
  });

  it("can be narrowed to the current project", async () => {
    const { GlobalSearchBar } = await import("./GlobalSearchBar");
    render(
      <MemoryRouter initialEntries={["/overview"]}>
        <GlobalSearchBar projectId={1} />
      </MemoryRouter>,
    );
    fireEvent.click(screen.getByRole("checkbox", { name: "모든 프로젝트에서 찾기" }));
    vi.useFakeTimers();
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "GCB" } });
    await vi.advanceTimersByTimeAsync(300);
    vi.useRealTimers();
    expect(screen.getByRole("list", { name: "관련 실험" }).textContent).not.toContain("#OA06");
  });
});
