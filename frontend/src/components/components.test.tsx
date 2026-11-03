import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { DataTable } from "./DataTable";
import { EvidenceChip } from "./EvidenceChip";
import { StatTile } from "./StatTile";

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
