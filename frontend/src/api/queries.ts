/**
 * React Query hooks — the only way UI code talks to the backend.
 * Query keys are namespaced by backend module so invalidation stays local.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ApiError, api, apiFetch, unwrap, type Schemas } from "./client";
import type { DecisionCreate } from "./types";

// Request-body aliases used by mutation hooks below (one block; add new aliases here).
type CriteriaCreate = Schemas["CriteriaCreate"];
type ConditionBlock = Schemas["ConditionBlock"];
type ExperimentCreate = Schemas["ExperimentCreate"];
type ExperimentMetadataUpdate = Schemas["ExperimentMetadataUpdate"];
type ProtocolTemplateCreate = Schemas["ProtocolTemplateCreate"];
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

// eln — Notebook authoring (ELN-1..9). Multipart endpoints take a FormData body.
type ElnKind = "calibration" | "recovery" | "matrix_effect" | "ion_ratio" | "other";
const asForm = (form: FormData) => form as unknown as { file: string; kind: ElnKind; format: string };
const passForm = (body: unknown) => body as FormData;

/** Invalidate every query that shows one experiment's ELN state (and the audit log). */
const invalidateExperiment = (qc: ReturnType<typeof useQueryClient>, experimentId: number) => {
  void qc.invalidateQueries({ queryKey: ["eln", "experiment", experimentId] });
  void qc.invalidateQueries({ queryKey: ["eln", "datasets", experimentId] });
  void qc.invalidateQueries({ queryKey: ["eln", "history", experimentId] });
  void qc.invalidateQueries({ queryKey: ["eln", "audit", experimentId] });
  void qc.invalidateQueries({ queryKey: ["eln", "experiments"] });
  void qc.invalidateQueries({ queryKey: ["system", "audit"] });
};

export const useDatasetKinds = () =>
  useQuery({
    queryKey: ["eln", "dataset-kinds"],
    queryFn: () => unwrap(api.GET("/api/eln/dataset-kinds")),
    staleTime: Infinity,
  });

export const useImportFormats = () =>
  useQuery({
    queryKey: ["eln", "import-formats"],
    queryFn: () => unwrap(api.GET("/api/eln/import-formats")),
    staleTime: Infinity,
  });

export const useConditionTemplate = (projectId: number | null) =>
  useQuery({
    queryKey: ["eln", "condition-template", projectId],
    enabled: enabled(projectId),
    queryFn: () =>
      unwrap(
        api.GET("/api/eln/projects/{project_id}/condition-template", {
          params: { path: { project_id: projectId! } },
        }),
      ),
  });

export const useCheckConditions = () =>
  useMutation({
    mutationFn: ({ projectId, block }: { projectId: number; block: ConditionBlock }) =>
      unwrap(
        api.POST("/api/eln/projects/{project_id}/condition-check", {
          params: { path: { project_id: projectId } },
          body: block,
        }),
      ),
  });

export const useExperimentDraft = (
  projectId: number | null,
  source: { sourceExperimentId?: number | null; protocolTemplateId?: number | null },
  active = true,
) =>
  useQuery({
    queryKey: ["eln", "draft", projectId, source.sourceExperimentId ?? null, source.protocolTemplateId ?? null],
    enabled: active && enabled(projectId),
    staleTime: 0,
    gcTime: 0,
    queryFn: () =>
      unwrap(
        api.GET("/api/eln/projects/{project_id}/experiment-draft", {
          params: {
            path: { project_id: projectId! },
            query: {
              source_experiment_id: source.sourceExperimentId ?? undefined,
              protocol_template_id: source.protocolTemplateId ?? undefined,
            },
          },
        }),
      ),
  });

export const useCreateExperiment = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ projectId, body }: { projectId: number; body: ExperimentCreate }) =>
      unwrap(
        api.POST("/api/eln/projects/{project_id}/experiments", {
          params: { path: { project_id: projectId } },
          body,
        }),
      ),
    onSuccess: (exp) => {
      invalidateExperiment(qc, exp.id);
      void qc.invalidateQueries({ queryKey: ["eln", "projects"] });
      void qc.invalidateQueries({ queryKey: ["memory"] });
    },
  });
};

export const useUpdateMetadata = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ experimentId, body }: { experimentId: number; body: ExperimentMetadataUpdate }) =>
      unwrap(
        api.PATCH("/api/eln/experiments/{experiment_id}/metadata", {
          params: { path: { experiment_id: experimentId } },
          body,
        }),
      ),
    onSuccess: (exp) => invalidateExperiment(qc, exp.id),
  });
};

export const useAddAddendum = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ experimentId, note, author }: { experimentId: number; note: string; author: string }) =>
      unwrap(
        api.POST("/api/eln/experiments/{experiment_id}/addenda", {
          params: { path: { experiment_id: experimentId } },
          body: { note, author },
        }),
      ),
    onSuccess: (a) => invalidateExperiment(qc, a.experiment_id),
  });
};

export const useExperimentHistory = (experimentId: number | null) =>
  useQuery({
    queryKey: ["eln", "history", experimentId],
    enabled: enabled(experimentId),
    queryFn: () =>
      unwrap(
        api.GET("/api/eln/experiments/{experiment_id}/history", {
          params: { path: { experiment_id: experimentId! } },
        }),
      ),
  });

export const useExperimentAudit = (experimentId: number | null, limit = 200) =>
  useQuery({
    queryKey: ["eln", "audit", experimentId, limit],
    enabled: enabled(experimentId),
    queryFn: () =>
      unwrap(
        api.GET("/api/eln/experiments/{experiment_id}/audit", {
          params: { path: { experiment_id: experimentId! }, query: { limit } },
        }),
      ),
  });

export const useValidateDatasetUpload = () =>
  useMutation({
    mutationFn: (form: FormData) =>
      unwrap(
        api.POST("/api/eln/datasets/validate-upload", { body: asForm(form), bodySerializer: passForm }),
      ),
  });

export const useUploadDataset = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ experimentId, form }: { experimentId: number; form: FormData }) =>
      unwrap(
        api.POST("/api/eln/experiments/{experiment_id}/datasets/upload", {
          params: { path: { experiment_id: experimentId } },
          body: asForm(form),
          bodySerializer: passForm,
        }),
      ),
    onSuccess: (d) => invalidateExperiment(qc, d.experiment_id),
  });
};

export const usePreviewImport = () =>
  useMutation({
    mutationFn: (form: FormData) =>
      unwrap(api.POST("/api/eln/import/preview", { body: asForm(form), bodySerializer: passForm })),
  });

export const useImportDataset = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ experimentId, form }: { experimentId: number; form: FormData }) =>
      unwrap(
        api.POST("/api/eln/experiments/{experiment_id}/datasets/import", {
          params: { path: { experiment_id: experimentId } },
          body: asForm(form),
          bodySerializer: passForm,
        }),
      ),
    onSuccess: (d) => invalidateExperiment(qc, d.experiment_id),
  });
};

export const useUploadAttachment = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ experimentId, form }: { experimentId: number; form: FormData }) =>
      unwrap(
        api.POST("/api/eln/experiments/{experiment_id}/attachment-files", {
          params: { path: { experiment_id: experimentId } },
          body: asForm(form),
          bodySerializer: passForm,
        }),
      ),
    onSuccess: (f) => invalidateExperiment(qc, f.experiment_id),
  });
};

export const useProtocolTemplates = (projectId: number | null) =>
  useQuery({
    queryKey: ["eln", "protocol-templates", projectId],
    enabled: enabled(projectId),
    queryFn: () =>
      unwrap(
        api.GET("/api/eln/projects/{project_id}/protocol-templates", {
          params: { path: { project_id: projectId! } },
        }),
      ),
  });

export const useCreateProtocolTemplate = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ projectId, body }: { projectId: number; body: ProtocolTemplateCreate }) =>
      unwrap(
        api.POST("/api/eln/projects/{project_id}/protocol-templates", {
          params: { path: { project_id: projectId } },
          body,
        }),
      ),
    onSuccess: (t) => {
      void qc.invalidateQueries({ queryKey: ["eln", "protocol-templates", t.project_id] });
      void qc.invalidateQueries({ queryKey: ["system", "audit"] });
    },
  });
};

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

export const useKnowledgeGraph = (projectId: number | null) =>
  useQuery({
    queryKey: ["memory", "knowledge-graph", projectId],
    enabled: enabled(projectId),
    queryFn: () =>
      unwrap(
        api.GET("/api/memory/projects/{project_id}/knowledge-graph", {
          params: { path: { project_id: projectId! } },
        }),
      ),
  });

export const useMemorySearch = (projectId: number | null, q: string, limit = 20) =>
  useQuery({
    queryKey: ["memory", "search", projectId, q, limit],
    enabled: enabled(projectId) && q.trim().length > 0,
    queryFn: () =>
      unwrap(
        api.GET("/api/memory/projects/{project_id}/search", {
          params: { path: { project_id: projectId! }, query: { q: q.trim(), limit } },
        }),
      ),
  });

export const useRecall = (projectId: number | null, q: string) =>
  useQuery({
    queryKey: ["memory", "recall", projectId, q],
    enabled: enabled(projectId) && q.trim().length > 0,
    queryFn: () =>
      unwrap(
        api.GET("/api/memory/projects/{project_id}/recall", {
          params: { path: { project_id: projectId! }, query: { q: q.trim() } },
        }),
      ),
  });

/** Search across every project (or `projectIds`); each hit carries `project_id`. */
export const useMemorySearchAll = (q: string, projectIds: number[] | null = null, limit = 20) =>
  useQuery({
    queryKey: ["memory", "search-all", projectIds, q, limit],
    enabled: q.trim().length > 0,
    queryFn: () =>
      unwrap(
        api.GET("/api/memory/search", {
          params: { query: { q: q.trim(), limit, ...(projectIds ? { project_id: projectIds } : {}) } },
        }),
      ),
  });

/** Recall across every project (or `projectIds`); experiments ranked across projects. */
export const useRecallAll = (q: string, projectIds: number[] | null = null) =>
  useQuery({
    queryKey: ["memory", "recall-all", projectIds, q],
    enabled: q.trim().length > 0,
    queryFn: () =>
      unwrap(
        api.GET("/api/memory/recall", {
          params: { query: { q: q.trim(), ...(projectIds ? { project_id: projectIds } : {}) } },
        }),
      ),
  });

// -------------------------------------------------------------- analysis
/** Default criteria, or the active criteria of `projectId` when given. */
export const useCriteria = (projectId?: number | null) =>
  useQuery({
    queryKey: ["analysis", "criteria", projectId ?? null],
    queryFn: () =>
      unwrap(
        api.GET("/api/analysis/criteria", {
          params: { query: projectId != null ? { project_id: projectId } : {} },
        }),
      ),
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

export const useProjectCriteria = (projectId: number | null) =>
  useQuery({
    queryKey: ["analysis", "project-criteria", projectId],
    enabled: enabled(projectId),
    queryFn: () =>
      unwrap(
        api.GET("/api/analysis/projects/{project_id}/criteria", {
          params: { path: { project_id: projectId! } },
        }),
      ),
  });

export const useCreateCriteria = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ projectId, body }: { projectId: number; body: CriteriaCreate }) =>
      unwrap(
        api.POST("/api/analysis/projects/{project_id}/criteria", {
          params: { path: { project_id: projectId } },
          body,
        }),
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["analysis"] }),
  });
};

export const useRunAnalysis = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (experimentId: number) =>
      unwrap(
        api.POST("/api/analysis/experiments/{experiment_id}/run", {
          params: { path: { experiment_id: experimentId } },
        }),
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["analysis"] }),
  });
};

/** Stored outcomes grouped by one condition value (all projects unless `projectId`). */
export const useConditionRecords = (key: string | null, projectId: number | null, contains = "") =>
  useQuery({
    queryKey: ["analysis", "records", "conditions", key, projectId, contains.trim()],
    enabled: key != null && key !== "",
    queryFn: () =>
      unwrap(
        api.GET("/api/analysis/records/conditions", {
          params: {
            query: {
              key: key!,
              ...(contains.trim() ? { contains: contains.trim() } : {}),
              ...(projectId != null ? { project_id: [projectId] } : {}),
            },
          },
        }),
      ),
  });

export const useOperatorRecords = (projectId: number | null) =>
  useQuery({
    queryKey: ["analysis", "records", "operators", projectId],
    queryFn: () =>
      unwrap(
        api.GET("/api/analysis/records/operators", {
          params: { query: projectId != null ? { project_id: [projectId] } : {} },
        }),
      ),
  });

export const usePeriodRecords = (projectId: number | null) =>
  useQuery({
    queryKey: ["analysis", "records", "periods", projectId],
    queryFn: () =>
      unwrap(
        api.GET("/api/analysis/records/periods", {
          params: { query: projectId != null ? { project_id: [projectId] } : {} },
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

/** PAR-2 experiment draft built from a Partner proposal (not ELN's clone/protocol draft). */
export const useProposalExperimentDraft = (proposalId: number | null) =>
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
  const response = await apiFetch(`${base}/api/partner/ask/stream`, {
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

/** Failure archive with rule-based causes and linked decisions (all projects unless given). */
export const useFailureArchive = (projectId: number | null) =>
  useQuery({
    queryKey: ["partner", "failure-archive", projectId],
    queryFn: () =>
      unwrap(
        api.GET("/api/partner/failure-archive", {
          params: { query: projectId != null ? { project_id: [projectId] } : {} },
        }),
      ),
  });

/** Earlier same-symptom failures (any project) and what was concluded then. */
export const usePrecedents = (experimentId: number | null) =>
  useQuery({
    queryKey: ["partner", "precedents", experimentId],
    enabled: enabled(experimentId),
    queryFn: () =>
      unwrap(
        api.GET("/api/partner/experiments/{experiment_id}/precedents", {
          params: { path: { experiment_id: experimentId! } },
        }),
      ),
  });

export const useConditionFields = () =>
  useQuery({
    queryKey: ["eln", "condition-fields"],
    queryFn: () => unwrap(api.GET("/api/eln/condition-fields")),
    staleTime: Infinity,
  });
