/**
 * Cross-tab selection state lives in the URL, so every tab and the Research Partner panel
 * agree on it and links are shareable:
 *
 * - `?project=<id>` — the active project (header switcher). Without it, the project of
 *   `?exp=` is used (so a link to another project's experiment opens that project), else
 *   the first project.
 * - `?exp=<id>` — the selected experiment of the active project.
 */
import { useCallback, useMemo } from "react";
import { useSearchParams } from "react-router-dom";
import { useExperiment, useExperiments, useProjects } from "@/api/queries";
import type { ExperimentSummary, ProjectOut } from "@/api/types";

export interface ActiveProject {
  project: ProjectOut | null;
  projects: ProjectOut[];
  isLoading: boolean;
  /** Switch project: sets `?project=` and clears the experiment selection. */
  selectProject: (id: number) => void;
}

/** The active project from `?project=`, else the project of `?exp=`, else the first. */
export function useActiveProject(): ActiveProject {
  const { data, isLoading } = useProjects();
  const [params, setParams] = useSearchParams();
  const projects = useMemo(() => data ?? [], [data]);
  const fromUrl = Number(params.get("project"));
  const explicit = projects.find((p) => p.id === fromUrl) ?? null;
  const expId = Number(params.get("exp"));
  const inferFromExp = explicit === null && expId > 0;
  const exp = useExperiment(inferFromExp ? expId : null);
  const fromExp = inferFromExp ? (projects.find((p) => p.id === exp.data?.project_id) ?? null) : null;
  const waiting = inferFromExp && exp.isLoading;
  const project = explicit ?? fromExp ?? (waiting ? null : (projects[0] ?? null));
  const selectProject = useCallback(
    (id: number) =>
      setParams((prev) => {
        const next = new URLSearchParams(prev);
        next.set("project", String(id));
        next.delete("exp");
        next.delete("compare");
        return next;
      }),
    [setParams],
  );
  return { project, projects, isLoading: isLoading || waiting, selectProject };
}

/** `?project=&exp=` search string for a link that opens an experiment of any project. */
export function experimentSearch(experimentId: number, projectId?: number | null): string {
  const params = new URLSearchParams();
  if (projectId != null) params.set("project", String(projectId));
  params.set("exp", String(experimentId));
  return `?${params.toString()}`;
}

/** Short project label for badges: the first word of the name ("잔류농약", "발효식품"). */
export function projectShortName(name: string): string {
  return name.trim().split(/\s+/)[0] ?? name;
}

export interface ExperimentSelection {
  experiments: ExperimentSummary[];
  selected: ExperimentSummary | null;
  selectedId: number | null;
  select: (id: number) => void;
}

/** Selected experiment from `?exp=`; defaults to the most recent experiment. */
export function useSelectedExperiment(): ExperimentSelection {
  const { project } = useActiveProject();
  const { data: experiments = [] } = useExperiments(project?.id ?? null);
  const [params, setParams] = useSearchParams();
  const raw = Number(params.get("exp"));
  const selected = useMemo(
    () => experiments.find((e) => e.id === raw) ?? experiments[experiments.length - 1] ?? null,
    [experiments, raw],
  );
  const projectId = project?.id ?? null;
  const select = useCallback(
    (id: number) =>
      setParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          // pin the project so selecting does not re-infer it from the new experiment
          if (projectId != null) next.set("project", String(projectId));
          next.set("exp", String(id));
          return next;
        },
        { replace: true },
      ),
    [setParams, projectId],
  );
  return { experiments, selected, selectedId: selected?.id ?? null, select };
}
