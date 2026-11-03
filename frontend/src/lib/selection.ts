/**
 * Cross-tab selection state lives in the URL (`?exp=<id>`), so every tab and the
 * Research Partner panel agree on the current experiment and links are shareable.
 */
import { useCallback, useMemo } from "react";
import { useSearchParams } from "react-router-dom";
import { useExperiments, useProjects } from "@/api/queries";
import type { ExperimentSummary, ProjectOut } from "@/api/types";

/** The active project (single-project MVP: the first one). */
export function useActiveProject(): { project: ProjectOut | null; isLoading: boolean } {
  const { data, isLoading } = useProjects();
  return { project: data?.[0] ?? null, isLoading };
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
  const select = useCallback(
    (id: number) =>
      setParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          next.set("exp", String(id));
          return next;
        },
        { replace: true },
      ),
    [setParams],
  );
  return { experiments, selected, selectedId: selected?.id ?? null, select };
}
