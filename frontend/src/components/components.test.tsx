import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ApiError } from "@/api/client";
import { GLOSSARY } from "@/lib/glossary";
import { DataTable } from "./DataTable";
import { Disclosure } from "./Disclosure";
import { EvidenceChip } from "./EvidenceChip";
import { FlagMark } from "./FlagMark";
import { ErrorState } from "./QueryState";
import { StatTile } from "./StatTile";
import { Term } from "./Term";

describe("common components", () => {
  it("ErrorState shows the demo's read-only answer as a notice, real failures as errors", () => {
    const { rerender } = render(<ErrorState error={new ApiError(403, "demo_read_only", "저장되지 않습니다")} />);
    expect(screen.getByRole("status").textContent).toContain("데모 · 읽기 전용");
    expect(screen.queryByText(/오류:/)).toBeNull();
    rerender(<ErrorState error={new ApiError(500, "internal_error", "boom")} />);
    expect(screen.getByRole("alert").textContent).toContain("잠시 후 다시 시도");
    expect(screen.getByText("서버 응답: boom")).toBeTruthy();
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("ErrorState says what to do next: unreachable server, missing record", () => {
    const { container, rerender } = render(<ErrorState error={new TypeError("Failed to fetch")} />);
    const alert = () => within(container).getByRole("alert").textContent ?? "";
    expect(alert()).toContain("백엔드(uvicorn)가 켜져 있는지");
    expect(alert()).not.toContain("Failed to fetch");
    rerender(<ErrorState error={new ApiError(404, "not_found", "experiment 99 not found")} />);
    expect(alert()).toContain("다른 실험을 고르거나");
  });

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

  it("Disclosure status is a glyph and a spoken label, not color alone", () => {
    const { container } = render(
      <>
        <Disclosure title="회수율" tone="crit">
          <p />
        </Disclosure>
        <Disclosure title="IS" tone="warn">
          <p />
        </Disclosure>
        <Disclosure title="검량선" tone="ok">
          <p />
        </Disclosure>
      </>,
    );
    const summaries = [...container.querySelectorAll("summary")].map((s) => s.textContent ?? "");
    expect(summaries[0]).toContain("✕");
    expect(summaries[0]).toContain("심각");
    expect(summaries[1]).toContain("!");
    expect(summaries[1]).toContain("주의");
    expect(summaries[2]).toContain("✓");
    expect(summaries[2]).toContain("정상");
    // The title says it can be opened, and the hint flips when open (CSS group-open).
    expect(within(container).getAllByText("펼치기")).toHaveLength(3);
  });

  it("FlagMark marks a flagged table value with a glyph and a screen-reader label", () => {
    const { container } = render(<FlagMark tone="crit" label="허용 범위 밖" />);
    const label = within(container).getByText("허용 범위 밖");
    expect(label.className).toContain("sr-only");
    expect(label.parentElement?.textContent).toContain("✕");
    expect(label.parentElement?.getAttribute("title")).toBe("허용 범위 밖");
  });

  it("DataTable right-aligns numeric columns with tabular figures", () => {
    const { container } = render(
      <DataTable
        rows={[{ a: "x", v: "62.0%" }]}
        rowKey={(r) => r.a}
        columns={[
          { key: "a", header: "분석물", render: (r) => r.a },
          { key: "v", header: "평균", align: "right", render: (r) => r.v },
        ]}
      />,
    );
    const cell = within(container).getByText("62.0%");
    expect(cell.className).toContain("text-right");
    expect(cell.className).toContain("tabular-nums");
  });

  it("Term keeps the visible text and explains it in a tooltip", () => {
    render(<Term k="rsd">RSD</Term>);
    expect(screen.getByText("RSD").getAttribute("title")).toBe(GLOSSARY.rsd);
  });
});
