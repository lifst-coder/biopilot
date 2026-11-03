/** Shared E2E helpers: resolve seed records through the API (no hard-coded ids or numbers). */
import type { APIRequestContext } from "@playwright/test";
import { expect } from "@playwright/test";

export interface ProjectRef {
  id: number;
  name: string;
}

export async function getJson<T>(request: APIRequestContext, path: string): Promise<T> {
  const res = await request.get(path);
  expect(res.ok(), `${path} → ${res.status()}`).toBeTruthy();
  return (await res.json()) as T;
}

export async function projects(request: APIRequestContext): Promise<ProjectRef[]> {
  return getJson<ProjectRef[]>(request, "/api/eln/projects");
}

/** `{code: id}` for every experiment of a project. */
export async function experimentIds(
  request: APIRequestContext,
  projectId: number,
): Promise<Record<string, number>> {
  const list = await getJson<Array<{ id: number; code: string }>>(
    request,
    `/api/eln/projects/${projectId}/experiments?limit=500`,
  );
  return Object.fromEntries(list.map((e) => [e.code, e.id]));
}
