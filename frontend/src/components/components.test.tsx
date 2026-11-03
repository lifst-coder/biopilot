import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { GLOSSARY } from "@/lib/glossary";
import { DataTable } from "./DataTable";
import { Disclosure } from "./Disclosure";
import { EvidenceChip } from "./EvidenceChip";
import { StatTile } from "./StatTile";
import { Term } from "./Term";

describe("common components", () => {
  it("EvidenceChip renders the stored value with unit, not prose", () => {
    render(
      <EvidenceChip
        evidence={{
          key: "E1",
          source: "analysis",
          ref_type: "analysis.AnalysisResult",
          ref_id: 3,
          label: "#024 평균 회수율",
          value: 61.98,
          unit: "%",
          text: null,
        }}
      />,
    );
    expect(screen.getByText("62.0%")).toBeTruthy();
    expect(screen.getByText("E1")).toBeTruthy();
  });

  it("StatTile shows the given value", () => {
    render(<StatTile label="실험" value={7} />);
    expect(screen.getByText("7")).toBeTruthy();
  });

  it("DataTable shows empty text", () => {
    render(<DataTable rows={[]} rowKey={() => 0} columns={[]} empty="없음" />);
    expect(screen.getByText("없음")).toBeTruthy();
  });
});

describe("hierarchy components", () => {
  it("StatTile shows the meaning of the number and the term explanation", () => {
    render(<StatTile label="평균 회수율" value="62.0%" meaning="기준(70–120%) 미달" help="회수율 설명" tone="crit" />);
    expect(screen.getByText("기준(70–120%) 미달").className).toContain("text-crit");
    expect(screen.getByText("평균 회수율").getAttribute("title")).toBe("회수율 설명");
    expect(screen.getByText("회수율 설명")).toBeTruthy();
  });

  it("Disclosure is collapsed by default and renders lazy content only after opening", () => {
    const { container } = render(
      <>
        <Disclosure title="근거" summary="IS 억제 3" tone="warn">
          <p>항상 렌더</p>
        </Disclosure>
        <Disclosure title="무거운 근거" lazy>
          <p>열면 렌더</p>
        </Disclosure>
      </>,
    );
    const [eager, lazy] = container.querySelectorAll("details");
    expect(eager!.open).toBe(false);
    expect(screen.getByText("항상 렌더")).toBeTruthy();
    expect(screen.getByText("IS 억제 3").className).toContain("text-warn");
    expect(screen.queryByText("열면 렌더")).toBeNull();
    lazy!.open = true;
    fireEvent(lazy!, new Event("toggle"));
    expect(screen.getByText("열면 렌더")).toBeTruthy();
  });

  it("Term keeps the visible text and explains it in a tooltip", () => {
    render(<Term k="rsd">RSD</Term>);
    expect(screen.getByText("RSD").getAttribute("title")).toBe(GLOSSARY.rsd);
  });
});
