import type { UseQueryResult } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { ApiError } from "@/api/client";
import { DEMO_ERROR_CODES } from "@/api/demo";

export function LoadingState({ label = "불러오는 중…" }: { label?: string }) {
  return <p className="py-6 text-center text-sm text-ink-faint">{label}</p>;
}

/** True for the read-only demo's answers to writes / unrecorded requests (not real failures). */
export function isDemoNotice(error: unknown): boolean {
  return error instanceof ApiError && DEMO_ERROR_CODES.has(error.code);
}

/**
 * A failed request. The backend-less demo's "read-only" / "not recorded" answers are shown
 * as a neutral notice instead, so a visitor who tries a write sees why nothing happened.
 */
export function ErrorState({ error }: { error: unknown }) {
  const message = error instanceof Error ? error.message : String(error);
  if (isDemoNotice(error)) {
    return (
      <p role="status" className="rounded-md border border-warn/30 bg-warn-soft px-3 py-2 text-sm text-ink">
        <span className="font-semibold text-warn">데모 · 읽기 전용</span> — {message}
      </p>
    );
  }
  return (
    <p className="rounded-md bg-crit-soft px-3 py-2 text-sm text-crit">오류: {message}</p>
  );
}

export function EmptyState({ children }: { children: ReactNode }) {
  return <p className="py-6 text-center text-sm text-ink-faint">{children}</p>;
}

/** Renders loading/error states and hands loaded data to `children`. */
export function QueryState<T>({
  query,
  children,
}: {
  query: UseQueryResult<T>;
  children: (data: T) => ReactNode;
}) {
  if (query.isPending) return <LoadingState />;
  if (query.isError) return <ErrorState error={query.error} />;
  return <>{children(query.data)}</>;
}
