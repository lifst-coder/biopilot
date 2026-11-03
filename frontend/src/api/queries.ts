/**
 * React Query hooks — the only way UI code talks to the backend.
 * Query keys are namespaced by backend module so invalidation stays local.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ApiError, api, unwrap, type Schemas } from "./client";
import type { DecisionCreate } from "./types";

type AskRequest = Schemas["AskRequest"];
type AskResponse = Schemas["AskResponse"];
type HypothesisStatusChange = Schemas["HypothesisStatusChange"];

const enabled = (...ids: Array<number | null | undefined>) => ids.every((v) => v != null);

// ---------------------------------------------------------------- system
export const useSystemInfo = () =>
  useQuery({ queryKey: ["system", "info"], queryFn: () => unwrap(api.GET("/api/system/info")) });

export const useAudit = (projectId: number | null, limit = 20) =>
  useQuery({
    queryKey: ["system", "audit", projectId, limit],
    enabled: enabled(projectId),
    queryFn: () =>
      unwrap(api.GET("/api/audit", { params: { query: { project_id: projectId!, limit } } })),
  });

// ------------------------------------------------------------------- eln
export const useProjects = () =>
  useQuery({ queryKey: ["eln", "projects"], queryFn: () => unwrap(api.GET("/api/eln/projects")) });

export const useExperiments = (projectId: number | null) =>
  useQuery({
    queryKey: ["eln", "experiments", projectId],
    enabled: enabled(projectId),
    queryFn: () =>
      unwrap(
        api.GET("/api/eln/projects/{project_id}/experiments", {
          params: { path: { project_id: projectId! } },
        }),
      ),
  });

export const useExperiment = (id: number | null) =>
  useQuery({
    queryKey: ["eln", "experiment", id],
    enabled: enabled(id),
    queryFn: () =>
      unwrap(
        api.GET("/api/eln/experiments/{experiment_id}", { params: { path: { experiment_id: id! } } }),
      ),
  });

export const useDatasets = (experimentId: number | null) =>
  useQuery({
    queryKey: ["eln", "datasets", experimentId],
    enabled: enabled(experimentId),
    queryFn: () =>
      unwrap(
        api.GET("/api/eln/experiments/{experiment_id}/datasets", {
          params: { path: { experiment_id: experimentId! } },
        }),
      ),
  });

export const useDatasetPreview = (datasetId: number | null, limit = 20) =>
  useQuery({
    queryKey: ["eln", "dataset", datasetId, limit],
    enabled: enabled(datasetId),
    queryFn: () =>
      unwrap(
        api.GET("/api/eln/datasets/{dataset_id}", {
          params: { path: { dataset_id: datasetId! }, query: { limit } },
        }),
      ),
  });

// ---------------------------------------------------------------- memory
export const useTimeline = (projectId: number | null) =>
  useQuery({
    queryKey: ["memory", "timeline", projectId],
    enabled: enabled(projectId),
    queryFn: () =>
      unwrap(
        api.GET("/api/memory/projects/{project_id}/timeline", {
          params: { path: { project_id: projectId! } },
        }),
      ),
  });

export const useDiff = (a: number | null, b: number | null) =>
  useQuery({
    queryKey: ["memory", "diff", a, b],
    enabled: enabled(a, b),
    queryFn: () => unwrap(api.GET("/api/memory/diff", { params: { query: { a: a!, b: b! } } })),
  });

export const useDigests = (experimentId: number | null) =>
  useQuery({
    queryKey: ["memory", "digests", experimentId],
    enabled: enabled(experimentId),
    queryFn: () =>
      unwrap(
        api.GET("/api/memory/experiments/{experiment_id}/digests", {
          params: { path: { experiment_id: experimentId! } },
        }),
      ),
  });

export const useCreateDigest = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (experimentId: number) =>
      unwrap(
        api.POST("/api/memory/experiments/{experiment_id}/digests", {
          params: { path: { experiment_id: experimentId } },
        }),
      ),
    onSuccess: (d) => qc.invalidateQueries({ queryKey: ["memory", "digests", d.experiment_id] }),
  });
};

// -------------------------------------------------------------- analysis
export const useCriteria = () =>
  useQuery({
    queryKey: ["analysis", "criteria"],
    queryFn: () => unwrap(api.GET("/api/analysis/criteria")),
    staleTime: Infinity,
  });

export const useMetrics = (experimentId: number | null) =>
  useQuery({
    queryKey: ["analysis", "metrics", experimentId],
    enabled: enabled(experimentId),
    queryFn: () =>
      unwrap(
        api.GET("/api/analysis/experiments/{experiment_id}/metrics", {
          params: { path: { experiment_id: experimentId! } },
        }),
      ),
  });

export const useResults = (experimentId: number | null) =>
  useQuery({
    queryKey: ["analysis", "results", experimentId],
    enabled: enabled(experimentId),
    queryFn: () =>
      unwrap(
        api.GET("/api/analysis/results", { params: { query: { experiment_id: experimentId! } } }),
      ),
  });

export const useCompare = (a: number | null, b: number | null) =>
  useQuery({
    queryKey: ["analysis", "compare", a, b],
    enabled: enabled(a, b),
    queryFn: () =>
      unwrap(api.GET("/api/analysis/compare", { params: { query: { a: a!, b: b! } } })),
  });

export const useTrend = (projectId: number | null) =>
  useQuery({
    queryKey: ["analysis", "trend", projectId],
    enabled: enabled(projectId),
    queryFn: () =>
      unwrap(
        api.GET("/api/analysis/projects/{project_id}/trend", {
          params: { path: { project_id: projectId! } },
        }),
      ),
  });

// --------------------------------------------------------------- partner
export const usePartnerMode = () =>
  useQuery({
    queryKey: ["partner", "mode"],
    queryFn: () => unwrap(api.GET("/api/partner/mode")),
  });

export const useCritiques = (experimentId: number | null) =>
  useQuery({
    queryKey: ["partner", "critiques", experimentId],
    enabled: enabled(experimentId),
    queryFn: () =>
      unwrap(
        api.GET("/api/partner/experiments/{experiment_id}/critiques", {
          params: { path: { experiment_id: experimentId! } },
        }),
      ),
  });

export const useRunCritique = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (experimentId: number) =>
      unwrap(
        api.POST("/api/partner/experiments/{experiment_id}/critiques", {
          params: { path: { experiment_id: experimentId } },
        }),
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["partner"] }),
  });
};

export const useHypotheses = (projectId: number | null, experimentId?: number | null) =>
  useQuery({
    queryKey: ["partner", "hypotheses", projectId, experimentId ?? null],
    enabled: enabled(projectId),
    queryFn: () =>
      unwrap(
        api.GET("/api/partner/hypotheses", {
          params: { query: { project_id: projectId!, experiment_id: experimentId ?? undefined } },
        }),
      ),
  });

export const useProposals = (projectId: number | null, experimentId?: number | null) =>
  useQuery({
    queryKey: ["partner", "proposals", projectId, experimentId ?? null],
    enabled: enabled(projectId),
    queryFn: () =>
      unwrap(
        api.GET("/api/partner/proposals", {
          params: { query: { project_id: projectId!, experiment_id: experimentId ?? undefined } },
        }),
      ),
  });

export const useDecideProposal = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ proposalId, body }: { proposalId: number; body: DecisionCreate }) =>
      unwrap(
        api.POST("/api/partner/proposals/{proposal_id}/decision", {
          params: { path: { proposal_id: proposalId } },
          body,
        }),
      ),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["partner"] });
      void qc.invalidateQueries({ queryKey: ["system", "audit"] });
    },
  });
};

export const useAsk = () =>
  useMutation({
    mutationFn: (body: { project_id: number; experiment_id?: number | null; question: string }) =>
      unwrap(api.POST("/api/partner/ask", { body })),
  });

/** Proposals ranked by the backend's deterministic priority score (PAR-8). */
export const usePrioritizedProposals = (projectId: number | null, experimentId?: number | null) =>
  useQuery({
    queryKey: ["partner", "proposals", projectId, experimentId ?? null, "priority"],
    enabled: enabled(projectId),
    queryFn: () =>
      unwrap(
        api.GET("/api/partner/proposals", {
          params: {
            query: { project_id: projectId!, experiment_id: experimentId ?? undefined, sort: "priority" },
          },
        }),
      ),
  });

export const useProjectCritiques = (projectId: number | null, scope?: "experiment" | "project") =>
  useQuery({
    queryKey: ["partner", "project-critiques", projectId, scope ?? null],
    enabled: enabled(projectId),
    queryFn: () =>
      unwrap(
        api.GET("/api/partner/projects/{project_id}/critiques", {
          params: { path: { project_id: projectId! }, query: { scope } },
        }),
      ),
  });

export const useRunProjectCritique = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (projectId: number) =>
      unwrap(
        api.POST("/api/partner/projects/{project_id}/critiques", {
          params: { path: { project_id: projectId } },
        }),
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["partner"] }),
  });
};

export const useChangeHypothesisStatus = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ hypothesisId, body }: { hypothesisId: number; body: HypothesisStatusChange }) =>
      unwrap(
        api.POST("/api/partner/hypotheses/{hypothesis_id}/status", {
          params: { path: { hypothesis_id: hypothesisId } },
          body,
        }),
      ),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["partner", "hypotheses"] });
      void qc.invalidateQueries({ queryKey: ["system", "audit"] });
    },
  });
};

export const useExperimentDraft = (proposalId: number | null) =>
  useQuery({
    queryKey: ["partner", "experiment-draft", proposalId],
    enabled: enabled(proposalId),
    queryFn: () =>
      unwrap(
        api.GET("/api/partner/proposals/{proposal_id}/experiment-draft", {
          params: { path: { proposal_id: proposalId! } },
        }),
      ),
  });

export const useDecisionHistory = (projectId: number | null, experimentId?: number | null) =>
  useQuery({
    queryKey: ["partner", "decisions", projectId, experimentId ?? null],
    enabled: enabled(projectId),
    queryFn: () =>
      unwrap(
        api.GET("/api/partner/projects/{project_id}/decisions", {
          params: { path: { project_id: projectId! }, query: { experiment_id: experimentId ?? undefined } },
        }),
      ),
  });

export const useExchanges = (projectId: number | null, experimentId?: number | null) =>
  useQuery({
    queryKey: ["partner", "exchanges", projectId, experimentId ?? null],
    enabled: enabled(projectId),
    queryFn: () =>
      unwrap(
        api.GET("/api/partner/projects/{project_id}/exchanges", {
          params: { path: { project_id: projectId! }, query: { experiment_id: experimentId ?? undefined } },
        }),
      ),
  });

/** One server-sent event of `POST /api/partner/ask/stream`. */
export type AskStreamEvent =
  | { event: "start"; data: { engine_candidate: "rules" | "claude" } }
  | { event: "delta"; data: { text: string; provisional: boolean } }
  | { event: "replace"; data: { reason: string } }
  | { event: "final"; data: AskResponse };

/** Split an SSE buffer into complete events and the unparsed remainder. */
export function parseSseBuffer(buffer: string): { events: AskStreamEvent[]; rest: string } {
  const blocks = buffer.split("\n\n");
  const rest = blocks.pop() ?? "";
  const events: AskStreamEvent[] = [];
  for (const block of blocks) {
    let name = "";
    let data = "";
    for (const line of block.split("\n")) {
      if (line.startsWith("event: ")) name = line.slice(7).trim();
      else if (line.startsWith("data: ")) data += line.slice(6);
    }
    if (name && data) events.push({ event: name, data: JSON.parse(data) } as AskStreamEvent);
  }
  return { events, rest };
}

/** POST a question to the SSE endpoint, calling `onEvent` per event (PAR-9). */
export async function streamAsk(body: AskRequest, onEvent: (e: AskStreamEvent) => void): Promise<AskResponse> {
  const base = import.meta.env.VITE_API_BASE_URL ?? "";
  const response = await fetch(`${base}/api/partner/ask/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify(body),
  });
  if (!response.ok || !response.body) {
    const err = (await response.json().catch(() => ({}))) as { code?: string; message?: string };
    throw new ApiError(response.status, err.code ?? "http_error", err.message ?? response.statusText);
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let final: AskResponse | null = null;
  for (;;) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value, { stream: !done });
    const parsed = parseSseBuffer(done ? `${buffer}\n\n` : buffer);
    buffer = parsed.rest;
    for (const e of parsed.events) {
      if (e.event === "final") final = e.data;
      onEvent(e);
    }
    if (done) break;
  }
  if (!final) throw new ApiError(500, "stream_incomplete", "스트림이 final 이벤트 없이 끝났습니다");
  return final;
}

/** Streaming Q&A state: provisional text, replacement notice, final grounded answer. */
export const useAskStream = () => {
  const qc = useQueryClient();
  const [state, setState] = useState<{ text: string; replaced: string | null; streaming: boolean }>({
    text: "",
    replaced: null,
    streaming: false,
  });
  const mutation = useMutation({
    mutationFn: (body: AskRequest) => {
      setState({ text: "", replaced: null, streaming: true });
      return streamAsk(body, (e) => {
        if (e.event === "delta") setState((s) => ({ ...s, text: s.text + e.data.text }));
        if (e.event === "replace") setState((s) => ({ ...s, text: "", replaced: e.data.reason }));
      });
    },
    onSettled: () => {
      setState((s) => ({ ...s, streaming: false }));
      void qc.invalidateQueries({ queryKey: ["partner"] });
      void qc.invalidateQueries({ queryKey: ["system", "audit"] });
    },
  });
  return { ...mutation, stream: state };
};

export const useConditionFields = () =>
  useQuery({
    queryKey: ["eln", "condition-fields"],
    queryFn: () => unwrap(api.GET("/api/eln/condition-fields")),
    staleTime: Infinity,
  });
