/**
 * Backend-less demo mode (`VITE_DEMO=true`, used by the GitHub Pages build).
 *
 * Every `/api/...` request is answered from a static scenario file exported by the backend
 * (`python -m app.scripts.export_scenario`): `public/scenario.json` (reference profile) or
 * `public/scenario-lab.json` (lab). The file holds the **real API responses**, so the UI
 * still only formats backend-computed numbers. This adapter never computes anything:
 *
 * - GET → exact lookup by canonical key (path + sorted query, pagination removed; the
 *   `limit` the UI asked for is re-applied to list responses, as the API would).
 * - Text downloads (analysis reports) → the recorded body with its content type/filename.
 * - Partner questions → pre-computed answers for the panel's suggestion questions.
 * - Protocol extraction → the recorded answer for the example paste (`demoProtocolExample`).
 * - Any other write → `403 demo_read_only`; `ErrorState` shows it as a notice, not an error.
 */

export const DEMO_PROFILES = { reference: "scenario.json", lab: "scenario-lab.json" } as const;
export type DemoProfile = keyof typeof DEMO_PROFILES;

const STORAGE_KEY = "biopilot.demo.profile";
const PAGINATION = new Set(["limit", "offset"]);

interface Scenario {
  format: string;
  profile: DemoProfile;
  generated_at: string;
  ask_suggestions: string[];
  get: Record<string, unknown>;
  errors: Record<string, { status: number; body: unknown }>;
  text?: Record<string, { body: string; content_type: string; content_disposition: string }>;
  ask: Record<string, unknown>;
  protocol_example?: { text: string; extraction: unknown };
}

export const isDemo = import.meta.env.VITE_DEMO === "true";

/** Profile from `?scenario=lab|reference` (remembered for the session), default reference. */
export function demoProfile(): DemoProfile {
  let stored: string | null = null;
  try {
    const fromUrl = new URLSearchParams(window.location.search).get("scenario");
    if (fromUrl === "lab" || fromUrl === "reference") window.sessionStorage.setItem(STORAGE_KEY, fromUrl);
    stored = window.sessionStorage.getItem(STORAGE_KEY);
  } catch {
    stored = new URLSearchParams(window.location.search).get("scenario");
  }
  return stored === "lab" ? "lab" : "reference";
}

/** Switch profile and reload (the whole snapshot changes). */
export function switchDemoProfile(profile: DemoProfile): void {
  // Back to the app root: ids differ between scenarios and static hosts only serve index.html.
  window.location.assign(`${import.meta.env.BASE_URL}?scenario=${profile}`);
}

/** Canonical request key — must match `request_key()` in `backend/app/scripts/export_scenario.py`. */
export function requestKey(pathname: string, params: URLSearchParams): string {
  const items = [...params.entries()]
    .filter(([k, v]) => v !== "" && !PAGINATION.has(k))
    .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));
  if (items.length === 0) return pathname;
  return `${pathname}?${new URLSearchParams(items).toString()}`;
}

let scenario: Promise<Scenario> | null = null;

function loadScenario(): Promise<Scenario> {
  scenario ??= fetch(`${import.meta.env.BASE_URL}${DEMO_PROFILES[demoProfile()]}`).then(async (res) => {
    if (!res.ok) throw new Error(`demo scenario not found (${res.status})`);
    return (await res.json()) as Scenario;
  });
  return scenario;
}

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

/** Error codes the demo adapter answers with — rendered as a notice, not as a failure. */
export const DEMO_ERROR_CODES: ReadonlySet<string> = new Set(["demo_read_only", "not_in_scenario"]);

const READ_ONLY = {
  code: "demo_read_only",
  message: "데모는 읽기 전용이라 저장·실행되지 않습니다. 기록·분석·결정은 로컬 실행(README §7)에서 동작합니다.",
};

const normalize = (text: string) => text.replace(/\r\n/g, "\n").trim();

/** The example paste whose extraction the demo can answer (null outside demo / if absent). */
export async function demoProtocolExample(): Promise<string | null> {
  if (!isDemo) return null;
  const s = await loadScenario().catch(() => null);
  return s?.protocol_example?.text ?? null;
}

async function extraction(s: Scenario, request: Request): Promise<Response> {
  const body = (await request.json().catch(() => ({}))) as { text?: string };
  const example = s.protocol_example;
  if (example && normalize(body.text ?? "") === normalize(example.text)) return json(200, example.extraction);
  return json(403, {
    code: "demo_read_only",
    message: "데모에서는 ‘예시 원문 넣기’로 넣은 원문만 조건을 추출해 볼 수 있습니다. 임의 원문 추출은 로컬 실행에서 동작합니다.",
  });
}

function sse(answer: unknown): Response {
  const events = [
    `event: start\ndata: ${JSON.stringify({ engine_candidate: "rules", demo: true })}\n\n`,
    `event: final\ndata: ${JSON.stringify(answer)}\n\n`,
  ].join("");
  return new Response(events, { status: 200, headers: { "content-type": "text/event-stream" } });
}

async function answer(s: Scenario, request: Request, stream: boolean): Promise<Response> {
  const body = (await request.json().catch(() => ({}))) as {
    project_id?: number;
    experiment_id?: number | null;
    question?: string;
  };
  const key = `${body.project_id ?? ""}|${body.experiment_id ?? ""}|${(body.question ?? "").trim()}`;
  const found = s.ask[key];
  if (found === undefined) {
    return json(403, {
      code: "demo_read_only",
      message: `데모 모드에서는 미리 계산된 질문만 답할 수 있습니다: ${s.ask_suggestions.join(" · ")}`,
    });
  }
  return stream ? sse(found) : json(200, found);
}

/** `fetch` replacement for demo mode; non-`/api/` URLs go to the network unchanged. */
export async function demoFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const raw = input instanceof Request ? input.url : String(input);
  const url = new URL(raw, window.location.origin);
  if (!url.pathname.startsWith("/api/")) return fetch(input, init);
  const request =
    input instanceof Request && init === undefined ? input : new Request(url.toString(), init);
  const s = await loadScenario();
  const method = request.method.toUpperCase();
  if (method === "POST" && url.pathname === "/api/partner/ask/stream") return answer(s, request, true);
  if (method === "POST" && url.pathname === "/api/partner/ask") return answer(s, request, false);
  if (method === "POST" && url.pathname === "/api/eln/protocol-extractions") return extraction(s, request);
  if (method !== "GET") return json(403, READ_ONLY);

  const key = requestKey(url.pathname, url.searchParams);
  const text = s.text?.[key];
  if (text) {
    return new Response(text.body, {
      status: 200,
      headers: { "content-type": text.content_type, "content-disposition": text.content_disposition },
    });
  }
  if (key in s.get) {
    const data = s.get[key];
    const limit = Number(url.searchParams.get("limit"));
    return json(200, Array.isArray(data) && limit > 0 ? data.slice(0, limit) : data);
  }
  const err = s.errors[key];
  if (err) return json(err.status, err.body);
  return json(404, {
    code: "not_in_scenario",
    message: "이 조합은 데모 시나리오에 미리 저장되지 않았습니다(로컬 실행에서는 동작합니다).",
  });
}
