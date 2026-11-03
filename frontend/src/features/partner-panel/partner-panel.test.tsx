import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Schemas } from "@/api/client";
import { parseSseBuffer, streamAsk } from "@/api/queries";
import { AnswerView } from "./AnswerView";

type AskResponse = Schemas["AskResponse"];

const answer: AskResponse = {
  answer: "…",
  engine: "rules",
  evidence: [
    {
      key: "E1",
      source: "analysis",
      ref_type: "analysis.AnalysisResult",
      ref_id: 3,
      label: "#024 평균 회수율",
      value: 61.97,
      unit: "%",
      text: null,
    },
  ],
  topics: [],
  intent: "cause",
  experiment_id: 7,
  statements: [
    { text: "평균 회수율이 기준 미달", kind: "fact", evidence_keys: ["E1"] },
    { text: "GCB 흡착 가능성", kind: "estimate", evidence_keys: [] },
  ],
  sources: [{ ref_type: "partner.Critique", ref_id: 2, label: "비판 #2" }],
  critique_id: 2,
  proposal_ids: [],
  exchange_id: 5,
  fallback_reason: "Claude unavailable",
};

afterEach(() => vi.unstubAllGlobals());

describe("Partner panel", () => {
  it("tags statements and lists evidence and sources", () => {
    render(<AnswerView answer={answer} />);
    expect(screen.getByText("사실")).toBeTruthy();
    expect(screen.getByText("추정")).toBeTruthy();
    expect(screen.getByText("62.0%")).toBeTruthy();
    expect(screen.getByText(/partner.Critique #2/)).toBeTruthy();
    expect(screen.getByText(/규칙 모드로 대체/)).toBeTruthy();
  });

  it("parses SSE buffers incrementally", () => {
    const { events, rest } = parseSseBuffer(
      'event: start\ndata: {"engine_candidate":"rules"}\n\nevent: delta\ndata: {"text":"a","provisional":false}\n\nevent: fin',
    );
    expect(events.map((e) => e.event)).toEqual(["start", "delta"]);
    expect(rest).toBe("event: fin");
  });

  it("streams events and resolves with the final answer", async () => {
    const body = [
      'event: start\ndata: {"engine_candidate":"claude"}\n\n',
      'event: delta\ndata: {"text":"임시","provisional":true}\n\nevent: replace\ndata: {"reason":"x"}\n\n',
      `event: final\ndata: ${JSON.stringify(answer)}\n\n`,
    ];
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        for (const chunk of body) controller.enqueue(new TextEncoder().encode(chunk));
        controller.close();
      },
    });
    vi.stubGlobal("fetch", vi.fn(async () => new Response(stream, { status: 200 })));
    const seen: string[] = [];
    const final = await streamAsk({ project_id: 1, question: "왜?" }, (e) => seen.push(e.event));
    expect(seen).toEqual(["start", "delta", "replace", "final"]);
    expect(final.critique_id).toBe(2);
  });

  it("raises ApiError on HTTP errors", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify({ code: "not_found", message: "없음" }), { status: 404 })),
    );
    await expect(streamAsk({ project_id: 9, question: "?" }, () => undefined)).rejects.toThrow("없음");
  });
});
