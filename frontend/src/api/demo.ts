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
 * - Partner questions → pre-computed answers for the panel's suggestion questions.
 * - Any other write → `403 demo_read_only`, shown by the UI's normal error handling.
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
  ask: Record<string, unknown>;
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

const READ_ONLY = {
  code: "demo_read_only",
  message: "데모 모드(읽기 전용): 백엔드 없이 저장된 시나리오만 보여줍니다. 로컬 실행에서는 기록·분석·결정이 가능합니다.",
};

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
  if (method !== "GET") return json(403, READ_ONLY);

  const key = requestKey(url.pathname, url.searchParams);
  if (key in s.get) {
    const data = s.get[key];
    const limit = Number(url.searchParams.get("limit"));
    return json(200, Array.isArray(data) && limit > 0 ? data.slice(0, limit) : data);
  }
  const err = s.errors[key];
  if (err) return json(err.status, err.body);
  return json(404, {
    code: "not_in_scenario",
    message: "데모 시나리오에 미리 저장되지 않은 요청입니다(로컬 실행에서는 동작합니다).",
  });
}
