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

/** What the user can do about a failed request, by backend error code (CLAUDE.md §3 envelope). */
const NEXT_STEP: Record<string, string> = {
  not_found: "찾는 기록이 없습니다 — 다른 실험을 고르거나 헤더에서 프로젝트를 확인하세요.",
  validation_failed: "입력값을 고친 뒤 다시 시도하세요.",
  immutable_record: "원본은 고칠 수 없습니다 — 보충 기록이나 새 실험으로 남기세요.",
  revision_conflict: "다른 곳에서 먼저 수정했습니다 — 새로 고친 뒤 다시 수정하세요.",
  conflict: "이미 같은 기록이 있습니다 — 새로 고쳐 현재 상태를 확인하세요.",
  payload_too_large: "파일이 너무 큽니다 — 나눠서 올리거나 필요한 열만 남겨 올리세요.",
  internal_error: "서버에서 처리하지 못했습니다 — 잠시 후 다시 시도하고, 반복되면 서버 로그를 확인하세요.",
};

/** One sentence: what failed (if the backend said) and what to do next. */
export function errorAdvice(error: unknown): { message: string | null; next: string } {
  if (error instanceof ApiError) {
    const next =
      NEXT_STEP[error.code] ??
      (error.status === 422
        ? "입력 형식이 맞지 않습니다 — 빈 칸과 숫자 칸을 확인하세요."
        : error.status >= 500
          ? NEXT_STEP.internal_error!
          : "새로 고친 뒤 다시 시도하세요.");
    return { message: error.message || null, next };
  }
  // fetch() rejects with a TypeError when the server cannot be reached at all.
  if (error instanceof TypeError) {
    return { message: null, next: "서버에 연결하지 못했습니다 — 백엔드(uvicorn)가 켜져 있는지 확인하고 새로 고치세요." };
  }
  return { message: error instanceof Error ? error.message : String(error), next: "새로 고친 뒤 다시 시도하세요." };
}

/**
 * A failed request, phrased as what to do next. The backend-less demo's "read-only" /
 * "not recorded" answers are shown as a neutral notice instead, so a visitor who tries a
 * write sees why nothing happened.
 */
export function ErrorState({ error }: { error: unknown }) {
  if (isDemoNotice(error)) {
    const message = error instanceof Error ? error.message : String(error);
    return (
      <p role="status" className="rounded-md border border-warn/30 bg-warn-soft px-3 py-2 text-sm text-ink">
        <span className="font-semibold text-warn">데모 · 읽기 전용</span> — {message}
      </p>
    );
  }
  const { message, next } = errorAdvice(error);
  return (
    <p role="alert" className="rounded-md bg-crit-soft px-3 py-2 text-sm text-crit">
      <span className="font-semibold">{next}</span>
      {message && <span className="block text-ink-muted">서버 응답: {message}</span>}
    </p>
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
