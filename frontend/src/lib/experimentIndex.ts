/**
 * Every experiment of every project, looked up by code or id — so an experiment code that
 * appears anywhere (an evidence chip, a critique sentence, a decision rationale, a raw note)
 * can become a link that opens that experiment in its own project.
 */
import { useRef } from "react";
import { useExperimentsOf, useProjects } from "@/api/queries";
import type { ExperimentSummary } from "@/api/types";

/** An experiment code as written in records: `#024`, `#OA06` (a `#` + optional letters + ≥2 digits). */
export const EXPERIMENT_CODE = /#[A-Z]{0,4}\d{2,4}(?![\d.])/g;

export interface ExperimentIndex {
  /** Experiment with this exact code; codes in `preferProjectId` win when two projects share one. */
  byCode: (code: string, preferProjectId?: number | null) => ExperimentSummary | null;
  byId: (id: number) => ExperimentSummary | null;
  /** Experiments of one project in their stored order (empty while loading). */
  ofProject: (projectId: number | null) => ExperimentSummary[];
}

/** Builds the index from per-project experiment lists (pure; exported for tests). */
export function buildExperimentIndex(lists: ExperimentSummary[][]): ExperimentIndex {
  const codes = new Map<string, ExperimentSummary[]>();
  const ids = new Map<number, ExperimentSummary>();
  const projects = new Map<number, ExperimentSummary[]>();
  for (const list of lists) {
    for (const e of list) {
      ids.set(e.id, e);
      codes.set(e.code, [...(codes.get(e.code) ?? []), e]);
      projects.set(e.project_id, [...(projects.get(e.project_id) ?? []), e]);
    }
  }
  return {
    byCode: (code, preferProjectId) => {
      const found = codes.get(code) ?? [];
      return found.find((e) => e.project_id === preferProjectId) ?? found[0] ?? null;
    },
    byId: (id) => ids.get(id) ?? null,
    ofProject: (projectId) => (projectId == null ? [] : (projects.get(projectId) ?? [])),
  };
}

/** Text split into plain runs and experiment codes, in order (pure; exported for tests). */
export function splitCodes(text: string): Array<string | { code: string }> {
  const out: Array<string | { code: string }> = [];
  let last = 0;
  for (const m of text.matchAll(EXPERIMENT_CODE)) {
    const at = m.index ?? 0;
    if (at > last) out.push(text.slice(last, at));
    out.push({ code: m[0] });
    last = at + m[0].length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

/** Index over all projects' experiments (shares the `useExperiments` cache entries). */
export function useExperimentIndex(): ExperimentIndex {
  const { data: projects = [] } = useProjects();
  const results = useExperimentsOf(projects.map((p) => p.id));
  // `results` is a new array every render; the update stamps say when the data changed.
  const stamp = results.map((r) => r.dataUpdatedAt).join(",");
  const lists = results.map((r) => r.data ?? []);
  const ref = useRef<{ stamp: string; index: ExperimentIndex } | null>(null);
  if (ref.current?.stamp !== stamp) ref.current = { stamp, index: buildExperimentIndex(lists) };
  return ref.current.index;
}
