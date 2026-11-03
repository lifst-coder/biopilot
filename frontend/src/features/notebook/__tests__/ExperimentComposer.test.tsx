import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ExperimentComposer } from "../ExperimentComposer";
import {
  CONDITION_FIELDS,
  EXPERIMENT,
  SUMMARY,
  VALIDATION,
  mockApi,

  renderWithProviders,
  type Call,
} from "./testUtils";

vi.mock("@/api/client", async (orig) => (await import("./testUtils")).mockClientModule(orig));
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const DRAFT = {
  source: "blank",
  suggested_code: "#025",
  draft: {
    code: "#025",
    title: "새 실험",
    author: "",
    performed_on: "2026-11-03",
    parent_experiment_id: null,
    raw_note: "목적:\n",
    condition_block: {},
    attachments: [],
    cloned_from_experiment_id: null,
    protocol_template_id: null,
  },
};

const routes = (checkFor: (block: Record<string, unknown>) => unknown) => ({
  "GET /api/eln/projects/1/experiment-draft": () => DRAFT,
  "GET /api/eln/projects/1/protocol-templates": () => ({ project_id: 1, total: 0, items: [] }),
  "GET /api/eln/condition-fields": () => CONDITION_FIELDS,
  "POST /api/eln/projects/1/condition-check": (c: Call) => checkFor(c.body as Record<string, unknown>),
  "POST /api/eln/datasets/validate-upload": (c: Call) => {
    const file = (c.body as FormData).get("file") as File;
    return file.name === "bad.csv"
      ? VALIDATION(false, [{ level: "error", code: "not_numeric", message: "level_ng_ml 숫자가 아님: 'abc'", row: 2, column: "level_ng_ml" }])
      : VALIDATION(true);
  },
  "POST /api/eln/projects/1/experiments": (c: Call) => ({
    status: 201,
    body: EXPERIMENT(25, "#025", { title: (c.body as { title: string }).title, warnings: [] }),
  }),
  "POST /api/eln/experiments/25/datasets/upload": () => ({ status: 201, body: { id: 99, experiment_id: 25 } }),
});

const okCheck = () => ({ ok: true, template_version: 0, template_source: "default", issues: [] });
const phCheck = (block: Record<string, unknown>) =>
  block.ph === 15
    ? {
        ok: false,
        template_version: 0,
        template_source: "default",
        issues: [{ key: "ph", level: "error", code: "above_max", message: "pH: 15 > 최대 14" }],
      }
    : okCheck();

describe("ExperimentComposer", () => {
  it("validates conditions on the server and blocks saving on template errors", async () => {
    mockApi(routes(phCheck));
    renderWithProviders(
      <ExperimentComposer projectId={1} experiments={[SUMMARY(7, "#024")]} source={{ kind: "blank" }} onCancel={() => {}} onCreated={() => {}} />,
    );
    const ph = await screen.findByLabelText("pH");
    fireEvent.change(ph, { target: { value: "15" } });
    expect((await screen.findAllByText("pH: 15 > 최대 14")).length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "실험 저장" })).toHaveProperty("disabled", true);
    expect(screen.getByText("조건 블록 오류를 고쳐야 저장할 수 있습니다")).toBeTruthy();
    expect(screen.getByText("min")).toBeTruthy(); // unit shown next to the input
  });

  it("stages CSVs with server dry-run, then creates the experiment and uploads them", async () => {
    const calls = mockApi(routes(okCheck));
    const onCreated = vi.fn();
    renderWithProviders(
      <ExperimentComposer projectId={1} experiments={[SUMMARY(7, "#024")]} source={{ kind: "blank" }} onCancel={() => {}} onCreated={onCreated} />,
    );
    await screen.findByDisplayValue("#025");
    fireEvent.change(screen.getByLabelText("제목"), { target: { value: "추출 7분" } });
    fireEvent.change(screen.getByLabelText("추출 시간 (min)"), { target: { value: "7" } });
    const input = screen.getAllByTestId("file-input")[0]!;
    fireEvent.change(input, { target: { files: [new File(["x"], "bad.csv", { type: "text/csv" })] } });
    expect(await screen.findByText(/level_ng_ml 숫자가 아님: 'abc'/)).toBeTruthy();
    expect(screen.getByText("검증 실패")).toBeTruthy();
    expect(screen.getByRole("button", { name: "실험 저장" })).toHaveProperty("disabled", true);
    fireEvent.click(screen.getByRole("button", { name: "제거" }));
    fireEvent.change(input, { target: { files: [new File(["x"], "good.csv", { type: "text/csv" })] } });
    expect(await screen.findByText("검증 통과")).toBeTruthy();
    await waitFor(() => expect(screen.getByRole("button", { name: "실험 저장" })).toHaveProperty("disabled", false));
    fireEvent.click(screen.getByRole("button", { name: "실험 저장" }));
    await waitFor(() => expect(onCreated).toHaveBeenCalledWith({ experimentId: 25, warnings: [], failures: [] }));
    const create = calls.find((c) => c.path === "/api/eln/projects/1/experiments")!;
    expect(create.body).toMatchObject({ code: "#025", title: "추출 7분", condition_block: { extraction_time_min: 7 } });
    const upload = calls.find((c) => c.path === "/api/eln/experiments/25/datasets/upload")!;
    expect((upload.body as FormData).get("kind")).toBe("calibration");
    expect(((upload.body as FormData).get("file") as File).name).toBe("good.csv");
  });

  it("shows the server error when creation is rejected", async () => {
    mockApi({
      ...routes(okCheck),
      "POST /api/eln/projects/1/experiments": () => ({
        status: 400,
        body: { code: "validation_failed", message: "Experiment code #025 already exists in project" },
      }),
    });
    const onCreated = vi.fn();
    renderWithProviders(
      <ExperimentComposer projectId={1} experiments={[]} source={{ kind: "blank" }} onCancel={() => {}} onCreated={onCreated} />,
    );
    await screen.findByDisplayValue("#025");
    await waitFor(() => expect(screen.getByRole("button", { name: "실험 저장" })).toHaveProperty("disabled", false));
    fireEvent.click(screen.getByRole("button", { name: "실험 저장" }));
    expect(await screen.findByText(/already exists/)).toBeTruthy();
    expect(onCreated).not.toHaveBeenCalled();
  });

  it("requests a clone draft for the source experiment", async () => {
    const calls = mockApi(routes(okCheck));
    renderWithProviders(
      <ExperimentComposer
        projectId={1}
        experiments={[SUMMARY(7, "#024")]}
        source={{ kind: "clone", experimentId: 7 }}
        onCancel={() => {}}
        onCreated={() => {}}
      />,
    );
    await screen.findByDisplayValue("#025");
    expect(screen.getByText("복제: #024")).toBeTruthy();
    const draft = calls.find((c) => c.path.endsWith("/experiment-draft"))!;
    expect(draft.query.get("source_experiment_id")).toBe("7");
  });
});
