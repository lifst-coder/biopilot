import type { UseQueryResult } from "@tanstack/react-query";
import type { ReactNode } from "react";

export function LoadingState({ label = "불러오는 중…" }: { label?: string }) {
  return <p className="py-6 text-center text-sm text-ink-faint">{label}</p>;
}

export function ErrorState({ error }: { error: unknown }) {
  const message = error instanceof Error ? error.message : String(error);
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
