import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ExperimentSummary } from "@/api/types";
import { GuideBar, guideTargets, useGuideBar } from "./GuideBar";

vi.mock("@/api/queries", () => ({
  useProjects: () => ({ data: [{ id: 1 }], isLoading: false }),
  useExperiments: () => ({ data: EXPERIMENTS }),
  useExperiment: () => ({ data: undefined, isLoading: false }),
}));

afterEach(() => {
  cleanup();
  window.localStorage.clear();
});

const exp = (id: number, code: string, parent: number | null): ExperimentSummary => ({
  id,
  project_id: 1,
  code,
  title: code,
  author: "",
  performed_on: "2026-10-01",
  parent_experiment_id: parent,
  dataset_kinds: [],
});

const { EXPERIMENTS } = vi.hoisted(() => {
  const mk = (id: number, code: string, parent: number | null) => ({
    id,
    project_id: 1,
    code,
    title: code,
    author: "",
    performed_on: "2026-10-01",
    parent_experiment_id: parent,
    dataset_kinds: [] as ExperimentSummary["dataset_kinds"],
  });
  return { EXPERIMENTS: [mk(1, "#018", null), mk(2, "#019", 1), mk(7, "#024", 1)] };
});

function Harness() {
  const guide = useGuideBar();
  return (
    <>
      {!guide.open && (
        <button type="button" onClick={guide.show}>
          안내
        </button>
      )}
      <GuideBar open={guide.open} onClose={guide.dismiss} />
    </>
  );
}

describe("GuideBar", () => {
  it("targets #024 and its parent, falling back to the latest experiment", () => {
    expect(guideTargets(EXPERIMENTS).focus?.code).toBe("#024");
    expect(guideTargets(EXPERIMENTS).baseline?.code).toBe("#018");
    const other = [exp(1, "#A1", null), exp(2, "#A2", 1)];
    expect(guideTargets(other).focus?.code).toBe("#A2");
    expect(guideTargets([]).focus).toBeNull();
  });

  it("links the four steps and can be dismissed and reopened", async () => {
    render(
      <MemoryRouter initialEntries={["/overview"]}>
        <Harness />
      </MemoryRouter>,
    );
    const open = await screen.findByRole("link", { name: /#024 열기/ });
    expect(open.getAttribute("href")).toBe("/notebook?exp=7");
    expect(screen.getByRole("link", { name: /#018과 비교/ }).getAttribute("href")).toBe("/notebook?exp=7&compare=1");
    expect(screen.getByRole("link", { name: /Critic 보기/ }).getAttribute("href")).toBe("/research-ai?exp=7#critic");
    expect(screen.getByRole("link", { name: /제안 기각해보기/ }).getAttribute("href")).toBe("/research-ai?exp=7#proposals");

    fireEvent.click(screen.getByRole("button", { name: "안내 닫기" }));
    expect(screen.queryByRole("region", { name: "데모 안내" })).toBeNull();
    expect(window.localStorage.getItem("biopilot.guide.dismissed")).toBe("1");
    fireEvent.click(screen.getByRole("button", { name: "안내" }));
    expect(await screen.findByRole("region", { name: "데모 안내" })).toBeTruthy();
  });
});
