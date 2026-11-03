import type { ReactNode } from "react";

/** Page title with the one question the screen answers, and optional controls on the right. */
export function PageHeader({ title, question, actions }: { title: ReactNode; question: string; actions?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-lg font-semibold">{title}</h1>
        <p className="text-xs text-ink-faint">이 화면의 질문 · {question}</p>
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}
