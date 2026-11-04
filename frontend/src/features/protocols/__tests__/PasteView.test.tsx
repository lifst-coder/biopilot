import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PasteView } from "../PasteView";
import { EXTRACTION, PASTE, mockApi, renderWithProviders, type Call } from "./testUtils";

vi.mock("@/api/client", async (orig) => (await import("./testUtils")).mockClientModule(orig));
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const routes = () => ({
  "GET /api/eln/projects/1/protocol-templates": () => ({ project_id: 1, total: 0, items: [] }),
  "POST /api/eln/protocol-extractions": () => EXTRACTION,
  "POST /api/eln/projects/1/protocol-templates": (c: Call) => ({
    id: 9,
    project_id: 1,
    name: (c.body as { name: string }).name,
    version: 1,
    display_version: "v1",
    description: "",
    raw_note_template: "",
    condition_block: {},
    source_experiment_id: null,
    author: "",
    created_at: "2026-11-04T00:00:00Z",
    steps: [],
    steps_derived: false,
    source_text: PASTE,
    version_label: "",
    extraction: { engine: "rules", items: [], accepted_count: 1, edited_count: 1, added_count: 1 },
  }),
});

async function extracted() {
  const calls = mockApi(routes());
  renderWithProviders(<PasteView projectId={1} go={vi.fn()} />);
  fireEvent.change(screen.getByLabelText("프로토콜 원문"), { target: { value: PASTE } });
  fireEvent.click(screen.getByRole("button", { name: "조건 추출" }));
  await screen.findByText("조건 4개 중 2개를 읽었습니다");
  return calls;
}

describe("PasteView", () => {
  it("shows candidates with their source line and leaves unrecognized keys empty", async () => {
    await extracted();
    expect((screen.getByLabelText(/추출 시간/) as HTMLInputElement).value).toBe("10");
    expect(screen.getByText("2. 추출 10분", { selector: "q" })).toBeTruthy();
    // ambiguous: empty input with the reason, never a guessed value
    expect((screen.getByLabelText(/컬럼 온도/) as HTMLInputElement).value).toBe("");
    expect(screen.getByText(/범위나 여러 값/)).toBeTruthy();
    expect(screen.getAllByText("인식하지 못함").length).toBeGreaterThan(0);
    expect((screen.getByLabelText("pH") as HTMLInputElement).value).toBe("");
    expect(screen.getByText("4. 원심분리 3000 rpm")).toBeTruthy();
  });

  it("saves the confirmed block with the pasted original and the reviewed candidates", async () => {
    const calls = await extracted();
    fireEvent.change(screen.getByLabelText(/추출 시간/), { target: { value: "12" } });
    fireEvent.change(screen.getByLabelText("pH"), { target: { value: "5.5" } });
    expect(screen.getAllByText("수정함")).toHaveLength(2);
    fireEvent.click(screen.getByRole("button", { name: "확인하고 저장" }));
    await screen.findByText("저장되었습니다");
    const post = calls.find((c) => c.method === "POST" && c.path.endsWith("/protocol-templates"))!;
    const body = post.body as Record<string, unknown>;
    expect(body.condition_block).toEqual({ matrix: "사과", extraction_time_min: 12, ph: 5.5 });
    expect(body.source_text).toBe(PASTE);
    expect((body.extraction as { fields: unknown[] }).fields).toHaveLength(4);
    expect((body.steps as Array<{ condition_keys: string[] }>)[1]!.condition_keys).toEqual(["extraction_time_min"]);
  });

  it("refuses a non-numeric value for a numeric key before calling the API", async () => {
    const calls = await extracted();
    fireEvent.change(screen.getByLabelText("pH"), { target: { value: "약 5" } });
    fireEvent.click(screen.getByRole("button", { name: "확인하고 저장" }));
    await waitFor(() => expect(screen.getByText(/pH: 숫자 하나로 입력하세요/)).toBeTruthy());
    expect(calls.some((c) => c.method === "POST" && c.path.endsWith("/protocol-templates"))).toBe(false);
  });
});
