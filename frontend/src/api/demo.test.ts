import { afterEach, describe, expect, it, vi } from "vitest";

const SCENARIO = {
  format: "biopilot-scenario@1",
  profile: "reference",
  generated_at: "2026-11-03T00:00:00+00:00",
  ask_suggestions: ["회수율이 왜 낮나?"],
  get: {
    "/api/eln/projects": [{ id: 1, name: "p" }],
    "/api/audit?project_id=1": [{ id: 3 }, { id: 2 }, { id: 1 }],
    "/api/memory/diff?a=1&b=7": { relation: "a_is_ancestor" },
    "/api/memory/projects/1/search?q=%EC%B6%94%EC%B6%9C+%EC%8B%9C%EA%B0%84": [{ code: "#024" }],
  },
  errors: { "/api/partner/proposals/3/experiment-draft": { status: 400, body: { code: "validation_failed", message: "decided" } } },
  text: {
    "/api/analysis/experiments/7/report?format=csv": {
      body: "a,b\n1,2\n",
      content_type: "text/csv; charset=utf-8",
      content_disposition: 'attachment; filename="report-024.csv"',
    },
  },
  ask: { "1|7|회수율이 왜 낮나?": { answer: "stored", engine: "rules" } },
  protocol_example: { text: "SOP\n1. 사과 10 g\n", extraction: { engine: "rules", field_count: 1 } },
};

async function load() {
  vi.resetModules();
  const network = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input instanceof Request ? input.url : input);
    if (url.endsWith("scenario.json")) return new Response(JSON.stringify(SCENARIO), { status: 200 });
    return new Response("network", { status: 200 });
  });
  vi.stubGlobal("fetch", network);
  const mod = await import("./demo");
  return { ...mod, network };
}

afterEach(() => vi.unstubAllGlobals());

describe("demo scenario adapter", () => {
  it("builds the same canonical key as the backend exporter", async () => {
    const { requestKey } = await load();
    const params = new URLSearchParams("b=7&limit=20&a=1&experiment_id=");
    expect(requestKey("/api/memory/diff", params)).toBe("/api/memory/diff?a=1&b=7");
    expect(requestKey("/api/eln/projects", new URLSearchParams())).toBe("/api/eln/projects");
  });

  it("answers GETs from the scenario, re-applying limit and replaying stored errors", async () => {
    const { demoFetch } = await load();
    const res = await demoFetch("/api/memory/diff?b=7&a=1");
    expect(await res.json()).toEqual({ relation: "a_is_ancestor" });
    const audit = await demoFetch("/api/audit?project_id=1&limit=2");
    expect((await audit.json()).map((a: { id: number }) => a.id)).toEqual([3, 2]);
    const search = await demoFetch(`/api/memory/projects/1/search?q=${encodeURIComponent("추출 시간")}&limit=20`);
    expect(await search.json()).toEqual([{ code: "#024" }]);
    const draft = await demoFetch("/api/partner/proposals/3/experiment-draft");
    expect(draft.status).toBe(400);
    const missing = await demoFetch("/api/memory/diff?a=2&b=3");
    expect(missing.status).toBe(404);
    expect((await missing.json()).code).toBe("not_in_scenario");
  });

  it("is read-only except for pre-computed Partner answers (JSON and SSE)", async () => {
    const { demoFetch } = await load();
    const write = await demoFetch("/api/partner/proposals/1/decision", { method: "POST", body: "{}" });
    expect(write.status).toBe(403);
    expect((await write.json()).code).toBe("demo_read_only");
    const body = JSON.stringify({ project_id: 1, experiment_id: 7, question: " 회수율이 왜 낮나? " });
    const ask = await demoFetch("/api/partner/ask", { method: "POST", body });
    expect(await ask.json()).toEqual({ answer: "stored", engine: "rules" });
    const stream = await demoFetch("/api/partner/ask/stream", { method: "POST", body });
    const text = await stream.text();
    expect(text).toContain("event: final");
    expect(text).toContain('"answer":"stored"');
    const other = await demoFetch("/api/partner/ask", {
      method: "POST",
      body: JSON.stringify({ project_id: 1, experiment_id: 7, question: "임의 질문" }),
    });
    expect(other.status).toBe(403);
  });

  it("replays recorded text downloads with their headers", async () => {
    const { demoFetch } = await load();
    const res = await demoFetch("/api/analysis/experiments/7/report?format=csv");
    expect(res.status).toBe(200);
    expect(await res.text()).toBe("a,b\n1,2\n");
    expect(res.headers.get("content-disposition")).toContain("report-024.csv");
  });

  it("answers protocol extraction only for the recorded example paste", async () => {
    const { demoFetch } = await load();
    const post = (text: string) =>
      demoFetch("/api/eln/protocol-extractions", { method: "POST", body: JSON.stringify({ text }) });
    const example = await post("SOP\r\n1. 사과 10 g");
    expect(await example.json()).toEqual({ engine: "rules", field_count: 1 });
    const other = await post("다른 원문");
    expect(other.status).toBe(403);
    expect((await other.json()).code).toBe("demo_read_only");
  });

  it("passes non-API URLs to the network", async () => {
    const { demoFetch, network } = await load();
    await demoFetch("/assets/logo.svg");
    expect(network).toHaveBeenCalled();
  });
});
