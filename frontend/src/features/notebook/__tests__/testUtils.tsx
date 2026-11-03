/**
 * Test helpers for Notebook components: an in-memory fetch router (no network) and a
 * render wrapper with React Query + router. Each test file must also mock
 * `@/api/client` with {@link mockClientModule} so requests use an absolute base URL.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";
import type { ExperimentSummary } from "@/api/types";

export const BASE = "http://bp.test";

export interface Call {
  method: string;
  path: string;
  query: URLSearchParams;
  body: unknown;
}

type Handler = (call: Call) => { status?: number; body: unknown } | unknown;

/** Install a fetch stub; `routes` keys are `"METHOD /path"` (exact pathname). */
export function mockApi(routes: Record<string, Handler>) {
  const calls: Call[] = [];
  const fetchStub = vi.fn(async (input: Request) => {
    const url = new URL(input.url);
    const method = input.method.toUpperCase();
    const type = input.headers.get("content-type") ?? "";
    let body: unknown = null;
    const raw = (input as Request & { rawBody?: unknown }).rawBody;
    if (raw instanceof FormData) body = raw;
    else if (method !== "GET" && type.includes("application/json")) body = await input.json();
    const call = { method, path: url.pathname, query: url.searchParams, body };
    calls.push(call);
    const handler = routes[`${method} ${url.pathname}`];
    if (!handler) {
      return new Response(JSON.stringify({ code: "not_found", message: `no mock for ${method} ${url.pathname}` }), {
        status: 404,
        headers: { "content-type": "application/json" },
      });
    }
    const result = handler(call);
    const wrapped =
      result && typeof result === "object" && "body" in (result as object)
        ? (result as { status?: number; body: unknown })
        : { body: result };
    return new Response(JSON.stringify(wrapped.body), {
      status: wrapped.status ?? 200,
      headers: { "content-type": "application/json" },
    });
  });
  vi.stubGlobal("fetch", fetchStub);
  return calls;
}

/**
 * Request that keeps a FormData body as-is: jsdom's FormData is not understood by Node's
 * Request, so multipart bodies are handed to the fetch stub untouched (`rawBody`).
 */
class CapturingRequest extends Request {
  rawBody?: unknown;
  constructor(input: RequestInfo | URL, init?: RequestInit) {
    const isForm = init?.body instanceof FormData;
    super(input, isForm ? { ...init, body: null } : init);
    if (isForm) this.rawBody = init?.body;
  }
}

/** Factory for `vi.mock("@/api/client", ...)`: same module, client with an absolute base URL. */
export async function mockClientModule(importOriginal: () => Promise<unknown>) {
  const mod = (await importOriginal()) as Record<string, unknown>;
  const createClient = (await import("openapi-fetch")).default;
  return {
    ...mod,
    api: createClient({
      baseUrl: BASE,
      Request: CapturingRequest,
      fetch: (req: Request) => globalThis.fetch(req),
    }),
  };
}

export function renderWithProviders(ui: ReactElement, path = "/notebook") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

// ------------------------------------------------------------------ fixtures

export const CONDITION_FIELDS = [
  { key: "matrix", label: "매트릭스", unit: null, value_type: "text", options: [], description: "" },
  { key: "ph", label: "pH", unit: null, value_type: "number", options: [], description: "" },
  { key: "extraction_time_min", label: "추출 시간 (min)", unit: "min", value_type: "number", options: [], description: "" },
  {
    key: "calibration_weighting",
    label: "검량선 가중",
    unit: null,
    value_type: "choice",
    options: ["none", "1/x", "1/x2"],
    description: "",
  },
];

export const SUMMARY = (id: number, code: string, parent: number | null = null): ExperimentSummary => ({
  id,
  project_id: 1,
  code,
  title: `실험 ${code}`,
  author: "김연구",
  performed_on: "2026-09-08",
  parent_experiment_id: parent,
  dataset_kinds: ["calibration"],
});

export const EXPERIMENT = (id: number, code: string, extra: Record<string, unknown> = {}) => ({
  ...SUMMARY(id, code),
  raw_note: `${code} 원본 메모`,
  condition_block: { extraction_time_min: 10 },
  attachments: [],
  created_at: "2026-09-08T00:00:00Z",
  cloned_from_experiment_id: null,
  protocol_template_id: null,
  revision: 1,
  addenda: [],
  attachment_files: [],
  warnings: [],
  ...extra,
});

export const VALIDATION = (ok: boolean, issues: unknown[] = []) => ({
  ok,
  kind: "calibration",
  schema_ref: "calibration@1",
  filename: "cal.csv",
  encoding: "cp949",
  sha256: "a".repeat(64),
  row_count: 2,
  columns: ["injection_id", "level_ng_ml"],
  preview_rows: [
    { injection_id: "C1", level_ng_ml: 1 },
    { injection_id: "C2", level_ng_ml: "abc" },
  ],
  issues,
});
