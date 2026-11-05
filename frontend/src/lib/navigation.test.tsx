import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { describe, expect, it } from "vitest";
import type { ExperimentSummary, ProjectOut } from "@/api/types";
import { CodeText } from "@/components";
import { Shortcuts } from "@/layout/Shortcuts";
import { buildExperimentIndex, splitCodes } from "./experimentIndex";
import { previousVisit, recordVisit } from "./trail";

const exp = (id: number, projectId: number, code: string): ExperimentSummary =>
  ({ id, project_id: projectId, code, title: `${code} 제목`, author: "", performed_on: "2026-10-01", parent_experiment_id: null, dataset_kinds: [] }) as ExperimentSummary;

const RESIDUE = [exp(18, 1, "#018"), exp(24, 1, "#024")];
const ACIDS = [exp(36, 2, "#OA06")];

/** Query cache pre-filled with two projects' experiment lists (no network). */
function client(): QueryClient {
  const qc = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } });
  qc.setQueryData(["eln", "projects"], [{ id: 1, name: "잔류농약 A" }, { id: 2, name: "발효식품 B" }] as ProjectOut[]);
  qc.setQueryData(["eln", "experiments", 1], RESIDUE);
  qc.setQueryData(["eln", "experiments", 2], ACIDS);
  return qc;
}

function Where() {
  const { pathname, search } = useLocation();
  return <output data-testid="where">{`${pathname}${search}`}</output>;
}

describe("experiment codes anywhere", () => {
  it("splits text into plain runs and codes, leaving numbers and result ids alone", () => {
    expect(splitCodes("#018 대비 #024의 회수율 62.0%")).toEqual([{ code: "#018" }, " 대비 ", { code: "#024" }, "의 회수율 62.0%"]);
    expect(splitCodes("유기산 #OA06, 비판 #4")).toEqual(["유기산 ", { code: "#OA06" }, ", 비판 #4"]);
  });

  it("resolves a code in the preferred project first, else in any project", () => {
    const index = buildExperimentIndex([RESIDUE, [exp(99, 2, "#018")], ACIDS]);
    expect(index.byCode("#018", 2)?.id).toBe(99);
    expect(index.byCode("#018", 1)?.id).toBe(18);
    expect(index.byCode("#OA06", 1)?.project_id).toBe(2);
    expect(index.byCode("#79")).toBeNull();
  });

  it("CodeText links known codes to their own project and keeps the text as recorded", () => {
    const { container } = render(
      <QueryClientProvider client={client()}>
        <MemoryRouter initialEntries={["/research-ai?project=1&exp=24"]}>
          <p data-testid="t">
            <CodeText text="#024는 #OA06과 같은 흡착제, 결과 #79" />
          </p>
          <Routes>
            <Route path="*" element={<Where />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    const p = within(container).getByTestId("t");
    expect(p.textContent).toBe("#024는 #OA06과 같은 흡착제, 결과 #79");
    expect(within(p).getAllByRole("link").map((a) => a.textContent)).toEqual(["#024", "#OA06"]);
    fireEvent.click(within(p).getByRole("link", { name: "#OA06" }));
    expect(within(container).getByTestId("where").textContent).toBe("/notebook?project=2&exp=36");
  });
});

describe("where the user came from", () => {
  it("offers the previous history entry only when it is a different screen", () => {
    recordVisit(0, { screen: "/records|failures||||", label: "Records · 실패 아카이브" });
    recordVisit(1, { screen: "/notebook||28|24|", label: "Notebook · #028 · 비교" });
    expect(previousVisit(1, "/notebook||28|24|")?.label).toBe("Records · 실패 아카이브");
    recordVisit(2, { screen: "/notebook||28|24|", label: "Notebook · #028 · 비교" });
    expect(previousVisit(2, "/notebook||28|24|")).toBeNull();
    expect(previousVisit(0, "/x")).toBeNull();
  });
});

describe("keyboard", () => {
  it("switches tabs with digits, steps experiments with [ ] and ignores typing", () => {
    const { container } = render(
      <QueryClientProvider client={client()}>
        <MemoryRouter initialEntries={["/analysis?project=1&exp=24"]}>
          <Shortcuts open={false} setOpen={() => {}} />
          <input aria-label="입력" />
          <Routes>
            <Route path="*" element={<Where />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    const where = () => within(container).getByTestId("where").textContent;
    fireEvent.keyDown(window, { key: "[" });
    expect(where()).toBe("/analysis?project=1&exp=18");
    fireEvent.keyDown(within(container).getByLabelText("입력"), { key: "6" });
    expect(where()).toBe("/analysis?project=1&exp=18");
    fireEvent.keyDown(window, { key: "5" });
    expect(where()).toBe("/research-ai?project=1&exp=18");
  });
});
