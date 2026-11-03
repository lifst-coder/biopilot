import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CompareModal } from "../CompareModal";
import { DatasetUploadPanel } from "../DatasetUploadPanel";
import { HistoryPanel } from "../HistoryPanel";
import { MetadataDialog } from "../MetadataDialog";
import { NotebookPage } from "../NotebookPage";
import { OriginalVsDigest } from "../OriginalVsDigest";
import type { ExperimentSummary } from "@/api/types";
import type { DatasetOut, ExperimentOut } from "../types";
import { CONDITION_FIELDS, EXPERIMENT, SUMMARY, VALIDATION, mockApi, renderWithProviders, type Call } from "./testUtils";

vi.mock("@/api/client", async (orig) => (await import("./testUtils")).mockClientModule(orig));
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const METRICS = (id: number, mean: number) => ({
  experiment_id: id,
  analyzed: true,
  recovery_mean_pct: mean,
  recovery_rsd_pct: 4.2,
  recovery_n: 50,
  per_analyte_recovery: [],
  min_r_squared: 0.9991,
  max_abs_back_calc_error_pct: 5.5,
  calibration_weighting: "1/x",
  is_injections_total: 10,
  is_injections_flagged: id === 7 ? 3 : 0,
  matrix_effect_pct: {},
  flags: [],
  source_result_ids: [1],
});

const DIGEST = (id: number, engine: "rules" | "claude", summary: string) => ({
  id,
  experiment_id: 7,
  engine,
  model: engine === "claude" ? "claude-x" : null,
  summary,
  key_points: ["포인트"],
  created_at: "2026-10-01T00:00:00Z",
});

describe("CompareModal", () => {
  it("shows Memory condition diff and Analysis result deltas exactly as returned", async () => {
    const calls = mockApi({
      "GET /api/memory/diff": () => ({
        a: SUMMARY(1, "#018"),
        b: SUMMARY(7, "#024", 1),
        relation: "a_is_ancestor",
        common_ancestor_id: 1,
        condition_changes: [
          { key: "extraction_time_min", label: "추출 시간 (min)", change: "changed", value_a: 10, value_b: 5 },
          { key: "cleanup_sorbent", label: "정제 흡착제 (d-SPE)", change: "changed", value_a: "C18", value_b: "GCB" },
        ],
        unchanged_keys: ["ph"],
        note_diff: [
          { op: "delete", text: "10분" },
          { op: "insert", text: "5분" },
        ],
        datasets: { only_a: [], only_b: [], both: ["calibration", "recovery"] },
      }),
      "GET /api/analysis/compare": () => ({
        experiment_a: 1,
        experiment_b: 7,
        metrics_a: METRICS(1, 89.12),
        metrics_b: METRICS(7, 61.98),
        recovery_delta_pct_points: -27.14,
        per_analyte: [{ analyte: "carbendazim", mean_a_pct: 85.8, mean_b_pct: 44.4, delta_pct_points: -41.4 }],
        recovery_t_test: { t_statistic: 9.1, p_value: 0.00001, n_a: 50, n_b: 50 },
      }),
    });
    renderWithProviders(
      <CompareModal experiments={[SUMMARY(1, "#018"), SUMMARY(7, "#024", 1)]} current={7} defaultBaseline={1} onClose={() => {}} />,
    );
    const dialog = await screen.findByRole("dialog");
    expect(await within(dialog).findByText("추출 시간 (min)")).toBeTruthy();
    expect(within(dialog).getByText("GCB")).toBeTruthy();
    expect(within(dialog).getByText("기준이 조상")).toBeTruthy();
    expect(await within(dialog).findByText("-27.1%p")).toBeTruthy();
    expect(within(dialog).getByText("89.1%")).toBeTruthy();
    expect(within(dialog).getByText("3/10")).toBeTruthy();
    expect(within(dialog).getByText(/p < 0.001/)).toBeTruthy();
    expect(within(dialog).getByText("-41.4%p")).toBeTruthy();
    fireEvent.click(within(dialog).getByText(/메모 차이 보기/));
    expect(within(dialog).getByText(/\+ 5분/)).toBeTruthy();
    const diffCall = calls.find((c) => c.path === "/api/memory/diff")!;
    expect([diffCall.query.get("a"), diffCall.query.get("b")]).toEqual(["1", "7"]);
  });
});

describe("CompareModal — unanalysed current experiment", () => {
  it("flags the unanalysed side and runs analysis, then shows the stored deltas", async () => {
    let ran = false;
    const calls = mockApi({
      "GET /api/memory/diff": () => ({
        a: SUMMARY(1, "#018"),
        b: SUMMARY(8, "#025", 1),
        relation: "a_is_ancestor",
        common_ancestor_id: 1,
        condition_changes: [],
        unchanged_keys: [],
        note_diff: [],
        datasets: { only_a: [], only_b: [], both: ["calibration", "recovery"] },
      }),
      "GET /api/analysis/compare": () => ({
        experiment_a: 1,
        experiment_b: 8,
        metrics_a: METRICS(1, 89.12),
        metrics_b: ran ? METRICS(8, 70.5) : { ...METRICS(8, 0), analyzed: false, recovery_mean_pct: null },
        recovery_delta_pct_points: ran ? -18.62 : null,
        per_analyte: [],
        recovery_t_test: null,
      }),
      "POST /api/analysis/experiments/8/run": () => {
        ran = true;
        return { experiment_id: 8, results: [], created: 2, skipped: [] };
      },
    });
    renderWithProviders(
      <CompareModal experiments={[SUMMARY(1, "#018"), SUMMARY(8, "#025", 1)]} current={8} defaultBaseline={1} onClose={() => {}} />,
    );
    const dialog = await screen.findByRole("dialog");
    expect(await within(dialog).findByText("현재 실험 미분석")).toBeTruthy();
    expect(within(dialog).getByText(/현재 실험이 아직 분석되지 않아/)).toBeTruthy();
    fireEvent.click(within(dialog).getByText("#025 분석 실행"));
    expect(await within(dialog).findByText("-18.6%p")).toBeTruthy();
    expect(within(dialog).queryByText("현재 실험 미분석")).toBeNull();
    expect(calls.some((c) => c.method === "POST" && c.path === "/api/analysis/experiments/8/run")).toBe(true);
  });
});

describe("HistoryPanel", () => {
  it("renders version history and a filterable audit log", async () => {
    mockApi({
      "GET /api/eln/experiments/7/history": () => ({
        experiment_id: 7,
        current_revision: 2,
        entries: [
          { kind: "created", occurred_at: "2026-10-01T00:00:00Z", revision: 1, summary: "#024 원본 기록", ref_type: "eln.Experiment", ref_id: 7, title: "옛 제목", author: "김", changes: {} },
          {
            kind: "metadata",
            occurred_at: "2026-10-02T00:00:00Z",
            revision: 2,
            summary: "메타데이터 수정 (title) — 오타",
            ref_type: "eln.ExperimentRevision",
            ref_id: 1,
            title: "새 제목",
            author: "김",
            changes: { title: { before: "옛 제목", after: "새 제목" } },
          },
        ],
      }),
      "GET /api/eln/experiments/7/audit": () => [
        { id: 3, occurred_at: "2026-10-02T00:00:00Z", actor: "user", action: "update_metadata", entity_type: "eln.Experiment", entity_id: 7, project_id: 1, payload: { reason: "오타" } },
        { id: 2, occurred_at: "2026-10-01T00:00:00Z", actor: "ai:rules", action: "memory.digest", entity_type: "memory.ExperimentDigest", entity_id: 4, project_id: 1, payload: { experiment_id: 7 } },
      ],
    });
    renderWithProviders(<HistoryPanel experimentId={7} />);
    expect(await screen.findByText("메타데이터 수정 (title) — 오타")).toBeTruthy();
    expect(screen.getByText("옛 제목", { selector: ".line-through" })).toBeTruthy();
    expect(screen.getByText("현재 메타데이터 버전 v2")).toBeTruthy();
    fireEvent.click(screen.getByRole("tab", { name: "감사 로그" }));
    expect(await screen.findByText("update_metadata")).toBeTruthy();
    expect(screen.getByText("memory.digest")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("감사 로그 모듈 필터"), { target: { value: "memory" } });
    expect(screen.queryByText("update_metadata")).toBeNull();
    fireEvent.click(screen.getByText("memory.digest"));
    expect(screen.getByText(/"experiment_id": 7/)).toBeTruthy();
  });
});

describe("OriginalVsDigest", () => {
  it("shows original and digest side by side and regenerates a digest", async () => {
    let created = false;
    const calls = mockApi({
      "GET /api/memory/experiments/7/digests": () =>
        created ? [DIGEST(2, "rules", "새 정리본"), DIGEST(1, "rules", "옛 정리본")] : [DIGEST(1, "rules", "옛 정리본")],
      "POST /api/memory/experiments/7/digests": () => {
        created = true;
        return { status: 201, body: DIGEST(2, "rules", "새 정리본") };
      },
      "GET /api/system/info": () => ({ version: "0.1.0", ai_mode: "rules", claude_model: null }),
      "GET /api/eln/condition-fields": () => CONDITION_FIELDS,
    });
    const exp = EXPERIMENT(7, "#024", {
      addenda: [{ id: 1, experiment_id: 7, note: "보충 메모", author: "이", created_at: "2026-10-03T00:00:00Z" }],
    }) as unknown as ExperimentOut;
    renderWithProviders(<OriginalVsDigest exp={exp} />);
    expect(screen.getByText("#024 원본 메모")).toBeTruthy();
    expect(screen.getByText("보충 메모")).toBeTruthy();
    expect(await screen.findByText("옛 정리본")).toBeTruthy();
    expect(await screen.findByText("오프라인 템플릿 모드")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "정리본 재생성" }));
    expect(await screen.findByText("새 정리본")).toBeTruthy();
    expect(calls.some((c) => c.method === "POST" && c.path === "/api/memory/experiments/7/digests")).toBe(true);
    expect(screen.getByLabelText("정리본 버전")).toBeTruthy();
  });
});

describe("DatasetUploadPanel", () => {
  it("re-uploads with supersedes_dataset_id after a passing dry-run", async () => {
    const calls = mockApi({
      "POST /api/eln/datasets/validate-upload": () => VALIDATION(true),
      "POST /api/eln/experiments/7/datasets/upload": () => ({ status: 201, body: { id: 50, experiment_id: 7 } }),
      "GET /api/eln/import-formats": () => [],
    });
    const onDone = vi.fn();
    const previous = { id: 12, kind: "calibration", filename: "old.csv" } as DatasetOut;
    renderWithProviders(<DatasetUploadPanel experimentId={7} supersedes={previous} onDone={onDone} />);
    expect(screen.getByText(/old.csv/)).toBeTruthy();
    expect(screen.getByLabelText("데이터셋 종류")).toHaveProperty("disabled", true);
    fireEvent.change(screen.getByTestId("file-input"), { target: { files: [new File(["x"], "new.csv")] } });
    expect(await screen.findByText("검증 통과")).toBeTruthy();
    expect(screen.getByText(/cp949/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "재업로드" }));
    await waitFor(() => expect(onDone).toHaveBeenCalled());
    const upload = calls.find((c) => c.path === "/api/eln/experiments/7/datasets/upload")!;
    expect((upload.body as FormData).get("supersedes_dataset_id")).toBe("12");
  });

  it("keeps upload disabled when the dry-run fails and converts vendor files in import mode", async () => {
    const calls = mockApi({
      "POST /api/eln/datasets/validate-upload": () =>
        VALIDATION(false, [{ level: "error", code: "missing_columns", message: "필수 컬럼 누락: is_area" }]),
      "GET /api/eln/import-formats": () => [
        { name: "wide_analyte_columns", label: "분석물 열 와이드 형식", description: "", target_kinds: ["calibration"], example_header: ["Injection", "Level"] },
      ],
      "POST /api/eln/import/preview": () => ({
        format: "wide_analyte_columns",
        kind: "calibration",
        analytes: ["azoxystrobin", "carbendazim"],
        source_rows: 3,
        converted_csv: "",
        validation: VALIDATION(true),
      }),
      "POST /api/eln/experiments/7/datasets/import": (c: Call) => ({ status: 201, body: { id: 51, experiment_id: 7, format: (c.body as FormData).get("format") } }),
    });
    renderWithProviders(<DatasetUploadPanel experimentId={7} />);
    fireEvent.change(screen.getByTestId("file-input"), { target: { files: [new File(["x"], "bad.csv")] } });
    expect(await screen.findByText("필수 컬럼 누락: is_area")).toBeTruthy();
    expect(screen.getByRole("button", { name: "업로드" })).toHaveProperty("disabled", true);
    fireEvent.click(screen.getByRole("tab", { name: "장비 내보내기 변환" }));
    expect(await screen.findByText(/Injection, Level/)).toBeTruthy();
    fireEvent.change(screen.getByTestId("file-input"), { target: { files: [new File(["x"], "vendor.csv")] } });
    expect(await screen.findByText(/원본 3행 → 분석물 2종/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "업로드" }));
    await waitFor(() => expect(calls.some((c) => c.path === "/api/eln/experiments/7/datasets/import")).toBe(true));
    const imp = calls.find((c) => c.path === "/api/eln/experiments/7/datasets/import")!;
    expect((imp.body as FormData).get("format")).toBe("wide_analyte_columns");
  });
});

describe("MetadataDialog", () => {
  it("sends only changed fields and shows server errors", async () => {
    const calls = mockApi({
      "PATCH /api/eln/experiments/7/metadata": () => ({
        status: 409,
        body: { code: "immutable_record", message: "Experiment fields are immutable: raw_note" },
      }),
    });
    const exp = EXPERIMENT(7, "#024") as unknown as ExperimentOut;
    renderWithProviders(<MetadataDialog exp={exp} onClose={() => {}} />);
    const save = screen.getByRole("button", { name: /저장/ });
    expect(save).toHaveProperty("disabled", true);
    fireEvent.change(screen.getByLabelText("제목"), { target: { value: "고친 제목" } });
    fireEvent.change(screen.getByLabelText(/수정 사유/), { target: { value: "오타" } });
    fireEvent.click(save);
    expect(await screen.findByText(/immutable: raw_note/)).toBeTruthy();
    expect(calls[0]!.body).toEqual({ title: "고친 제목", author: null, reason: "오타" });
  });
});

describe("NotebookPage", () => {
  it("lists seeded experiments, opens one and filters the list", async () => {
    const seeded = ["#018", "#019", "#020", "#021", "#022", "#023", "#024"].map(
      (code, i): ExperimentSummary => ({
        ...SUMMARY(i + 1, code, i ? 1 : null),
        dataset_kinds: code === "#021" ? ["matrix_effect"] : ["calibration", "recovery"],
      }),
    );
    mockApi({
      "GET /api/eln/projects": () => [{ id: 1, name: "P", objective: "", description: "", created_at: "2026-01-01T00:00:00Z", experiment_count: 7 }],
      "GET /api/eln/projects/1/experiments": () => seeded,
      "GET /api/eln/experiments/3": () => EXPERIMENT(3, "#020"),
      "GET /api/eln/experiments/7": () => EXPERIMENT(7, "#024"),
      "GET /api/eln/experiments/3/datasets": () => [],
      "GET /api/eln/experiments/7/datasets": () => [],
      "GET /api/memory/experiments/3/digests": () => [],
      "GET /api/memory/experiments/7/digests": () => [],
      "GET /api/eln/experiments/3/history": () => ({ experiment_id: 3, current_revision: 1, entries: [] }),
      "GET /api/eln/experiments/7/history": () => ({ experiment_id: 7, current_revision: 1, entries: [] }),
      "GET /api/system/info": () => ({ version: "0.1.0", ai_mode: "rules", claude_model: null }),
      "GET /api/eln/condition-fields": () => CONDITION_FIELDS,
    });
    renderWithProviders(<NotebookPage />);
    const list = await screen.findByRole("list", { name: "실험" });
    await waitFor(() => expect(within(list).getAllByRole("button")).toHaveLength(7));
    expect(await screen.findByText("#024 원본 메모")).toBeTruthy(); // defaults to most recent
    fireEvent.click(within(list).getByRole("button", { name: /#020/ }));
    expect(await screen.findByText("#020 원본 메모")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("데이터셋 종류 필터"), { target: { value: "matrix_effect" } });
    expect(within(list).getAllByRole("button")).toHaveLength(1);
    expect(screen.getByText("1/7개")).toBeTruthy();
  });
});
