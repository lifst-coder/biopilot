/**
 * Typed HTTP client generated from the backend OpenAPI contract.
 *
 * `schema.d.ts` is GENERATED (`npm run gen:api`) — never edit it by hand.
 * In dev, Vite proxies `/api` to the FastAPI server (see vite.config.ts).
 */
import createClient from "openapi-fetch";
import { demoFetch, isDemo } from "./demo";
import type { components, paths } from "./schema";

/**
 * `fetch` used for every API call: the network normally, the static scenario file in the
 * backend-less demo build (`VITE_DEMO=true`, see `demo.ts`).
 */
export const apiFetch: typeof fetch = isDemo ? demoFetch : (input, init) => fetch(input, init);

export const api = createClient<paths>({
  baseUrl: import.meta.env.VITE_API_BASE_URL ?? "",
  ...(isDemo ? { fetch: (request: Request) => demoFetch(request) } : {}),
});

export type Schemas = components["schemas"];

/** Error raised for any non-2xx API response. */
export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

interface FetchResult<T> {
  data?: T;
  error?: unknown;
  response: Response;
}

/** Return `data` or throw an {@link ApiError} carrying the backend error envelope. */
export async function unwrap<T>(promise: Promise<FetchResult<T>>): Promise<T> {
  const { data, error, response } = await promise;
  if (error !== undefined || data === undefined) {
    const body = (error ?? {}) as { code?: string; message?: string; detail?: unknown };
    const message = body.message ?? (body.detail ? JSON.stringify(body.detail) : response.statusText);
    throw new ApiError(response.status, body.code ?? "http_error", message);
  }
  return data;
}
