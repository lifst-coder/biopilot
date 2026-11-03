import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it } from "vitest";
import { CalibrationPanel } from "./CalibrationPanel";
import { calibrationOutput, recoveryOutput, resultOf } from "./fixtures";
import { FlagList } from "./FlagList";
import { FLAG_LABELS } from "./labels";
import { latestByKind } from "./AnalysisPage";
import { MethodNotes } from "./MethodNotes";
import { QCVerdictTable } from "./QCVerdictTable";
import { RecoveryPanel } from "./RecoveryPanel";

afterEach(cleanup);

beforeAll(() => {
  globalThis.ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
});

describe("CalibrationPanel", () => {
  it("toggles between the backend fits of each weighting", () => {
    render(<CalibrationPanel result={resultOf(calibrationOutput)} output={calibrationOutput} />);
    const group = screen.getByRole("group", { name: "가중치" });
    expect(within(group).getByRole("button", { name: /1\/x \(보고\)/ }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByText("1.5100e-2")).toBeTruthy();
    fireEvent.click(within(group).getByRole("button", { name: "비가중" }));
    expect(screen.getByText("1.7700e-2")).toBeTruthy();
    fireEvent.click(within(group).getByRole("button", { name: "1/x²" }));
    expect(screen.getByText("1.4900e-2")).toBeTruthy();
  });

  it("shows the heteroscedasticity F-test, residual mode and formula sheet", () => {
    render(<CalibrationPanel result={resultOf(calibrationOutput)} output={calibrationOutput} />);
    expect(screen.getByText(/이분산 → 가중 필요/)).toBeTruthy();
    fireEvent.change(screen.getByLabelText("잔차 종류"), { target: { value: "std" } });
    expect(screen.getByText(/표준화 잔차 √w/)).toBeTruthy();
    expect(screen.getByText(/calibration@3/)).toBeTruthy();
    expect(screen.getByText("R = A_analyte / A_IS")).toBeTruthy();
  });

  it("falls back to the reported fit for results without per-weighting fits", () => {
    const legacy = {
      ...calibrationOutput,
      analytes: calibrationOutput.analytes.map((a) => ({ ...a, fits: [], heteroscedasticity: null })),
    };
    render(<CalibrationPanel result={resultOf(legacy)} output={legacy} />);
    const group = screen.getByRole("group", { name: "가중치" });
    expect(within(group).getAllByRole("button")).toHaveLength(1);
    expect(screen.getByText("1.5100e-2")).toBeTruthy();
  });
});

describe("RecoveryPanel", () => {
  it("filters raw rows by injection ID and shows uncertainty", () => {
    render(<RecoveryPanel result={resultOf(recoveryOutput)} output={recoveryOutput} />);
    expect(screen.getByText("주입별 원시 행 (3)")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("주입 ID 필터"), { target: { value: "s-03" } });
    expect(screen.queryByText("S-01")).toBeNull();
    expect(screen.getAllByText("S-03").length).toBeGreaterThan(0);
    fireEvent.change(screen.getByLabelText("주입 ID 필터"), { target: { value: "zzz" } });
    expect(screen.getByText("일치하는 주입이 없습니다.")).toBeTruthy();
    expect(screen.getByText("108.4")).toBeTruthy();
  });
});

describe("FlagList and verdicts", () => {
  it("labels every flag code and shows the criteria version", () => {
    render(
      <FlagList
        flags={[
          {
            code: "is_suppression",
            severity: "warning",
            analyte: null,
            value: 43.2,
            threshold_low: 50,
            threshold_high: 150,
            context: { injection_id: "S-03" },
            criteria_version: "default",
          },
          {
            code: "outlier_suspected",
            severity: "warning",
            analyte: "tebuconazole",
            value: 1.8,
            threshold_low: null,
            threshold_high: 1.715,
            context: { injection_id: "S-05" },
            criteria_version: "project-1@v2",
          },
        ]}
      />,
    );
    expect(screen.getByText("IS 억제")).toBeTruthy();
    expect(screen.getByText("S-03")).toBeTruthy();
    expect(screen.getByText("tebuconazole · S-05")).toBeTruthy();
    expect(screen.getByText("project-1@v2")).toBeTruthy();
    expect(Object.keys(FLAG_LABELS)).toHaveLength(12);
  });

  it("renders pass/fail badges per analyte", () => {
    render(
      <QCVerdictTable
        verdicts={[
          { analyte: "carbendazim", status: "fail", failed_checks: ["recovery_out_of_range"], warning_checks: [] },
          { analyte: "azoxystrobin", status: "pass", failed_checks: [], warning_checks: [] },
        ]}
      />,
    );
    expect(screen.getByText("불합격")).toBeTruthy();
    expect(screen.getByText("합격")).toBeTruthy();
    expect(screen.getByText("회수율 범위 이탈")).toBeTruthy();
  });

  it("MethodNotes renders nothing without a method", () => {
    const { container } = render(<MethodNotes method={null} />);
    expect(container.innerHTML).toBe("");
  });

  it("latestByKind keeps the newest result of each kind", () => {
    const older = resultOf(recoveryOutput, 1);
    const newer = resultOf(recoveryOutput, 2);
    expect(latestByKind([older, newer]).get("recovery")?.id).toBe(2);
  });
});
