/**
 * React Query hooks — the only way UI code talks to the backend.
 * Query keys are namespaced by backend module so invalidation stays local.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, unwrap } from "./client";
import type { Schemas } from "./client";
import type { DecisionCreate } from "./types";

type CriteriaCreate = Schemas["CriteriaCreate"];

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

export const useConditionFields = () =>
  useQuery({
    queryKey: ["eln", "condition-fields"],
    queryFn: () => unwrap(api.GET("/api/eln/condition-fields")),
    staleTime: Infinity,
  });
