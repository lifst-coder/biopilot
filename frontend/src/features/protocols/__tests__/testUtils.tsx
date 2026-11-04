/**
 * Protocols tab test helpers: an in-memory fetch router (no network) and a render wrapper.
 * Test files mock `@/api/client` with {@link mockClientModule} (absolute base URL).
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";

export const BASE = "http://bp.test";

export interface Call {
  method: string;
  path: string;
  query: URLSearchParams;
  body: unknown;
}

type Handler = (call: Call) => unknown;

/** Install a fetch stub; `routes` keys are `"METHOD /path"`. Returns the recorded calls. */
export function mockApi(routes: Record<string, Handler>) {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: Request) => {
      const url = new URL(input.url);
      const method = input.method.toUpperCase();
      const body = method === "GET" ? null : await input.json().catch(() => null);
      const call = { method, path: url.pathname, query: url.searchParams, body };
      calls.push(call);
      const handler = routes[`${method} ${url.pathname}`];
      if (!handler) {
        return new Response(JSON.stringify({ code: "not_found", message: `no mock for ${method} ${url.pathname}` }), {
          status: 404,
          headers: { "content-type": "application/json" },
        });
      }
      return new Response(JSON.stringify(handler(call)), { status: 200, headers: { "content-type": "application/json" } });
    }),
  );
  return calls;
}

export async function mockClientModule(importOriginal: () => Promise<unknown>) {
  const mod = (await importOriginal()) as Record<string, unknown>;
  const createClient = (await import("openapi-fetch")).default;
  return { ...mod, api: createClient({ baseUrl: BASE, fetch: (req: Request) => globalThis.fetch(req) }) };
}

export function renderWithProviders(ui: ReactElement, path = "/protocols") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

const field = (key: string, label: string, extra: Record<string, unknown> = {}) => ({
  key,
  label,
  unit: null,
  value_type: "text",
  value: null,
  status: "unrecognized",
  source_text: null,
  line: null,
  candidates: [],
  note: "",
  ...extra,
});

/** Extraction response as the API returns it (values are whatever the fixture says). */
export const EXTRACTION = {
  engine: "rules",
  model: null,
  fallback_reason: null,
  fields: [
    field("matrix", "매트릭스", { value: "사과", status: "recognized", source_text: "1. 사과 칭량", line: 1 }),
    field("extraction_time_min", "추출 시간 (min)", {
      unit: "min",
      value_type: "number",
      value: 10,
      status: "recognized",
      source_text: "2. 추출 10분",
      line: 2,
    }),
    field("column_temp_c", "컬럼 온도 (°C)", {
      unit: "°C",
      value_type: "number",
      status: "ambiguous",
      source_text: "3. 컬럼 온도 35–40 °C",
      line: 3,
      candidates: ["3. 컬럼 온도 35–40 °C"],
      note: "범위나 여러 값으로 적혀 있음 — 직접 입력하세요",
    }),
    field("ph", "pH", { value_type: "number" }),
  ],
  steps: [
    { title: "사과 칭량", detail: "", condition_keys: ["matrix"], line: 1 },
    { title: "추출 10분", detail: "", condition_keys: ["extraction_time_min"], line: 2 },
  ],
  unmatched_lines: [{ line: 4, text: "4. 원심분리 3000 rpm" }],
  recognized_count: 2,
  field_count: 4,
  source_sha256: "x",
};

export const PASTE = "1. 사과 칭량\n2. 추출 10분\n3. 컬럼 온도 35–40 °C\n4. 원심분리 3000 rpm";
