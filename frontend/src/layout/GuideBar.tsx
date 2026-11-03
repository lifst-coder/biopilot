import clsx from "clsx";
import { useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { isDemo } from "@/api/demo";
import { useExperiments } from "@/api/queries";
import type { ExperimentSummary } from "@/api/types";
import { josa } from "@/lib/korean";
import { useActiveProject } from "@/lib/selection";

const STORAGE_KEY = "biopilot.guide.dismissed";

/** The demo's showcase experiment: #024 when present, otherwise the most recent one. */
export function guideTargets(experiments: ExperimentSummary[]): {
  focus: ExperimentSummary | null;
  baseline: ExperimentSummary | null;
} {
  const focus = experiments.find((e) => e.code === "#024") ?? experiments[experiments.length - 1] ?? null;
  const baseline =
    (focus?.parent_experiment_id != null && experiments.find((e) => e.id === focus.parent_experiment_id)) ||
    experiments.find((e) => e.id !== focus?.id) ||
    null;
  return { focus, baseline };
}

function readDismissed(): boolean {
  try {
    return window.localStorage.getItem(STORAGE_KEY) === "1";
  } catch {
    return false;
  }
}

function writeDismissed(value: boolean): void {
  try {
    if (value) window.localStorage.setItem(STORAGE_KEY, "1");
    else window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    /* storage unavailable (private window): the bar just reappears next visit */
  }
}

interface Step {
  key: string;
  label: string;
  to: string;
  active: boolean;
}

/**
 * First-visit guide: one line on what to look at, and the recommended order as clickable
 * steps. Dismissible (remembered in this browser); reopened from the header "안내" button.
 */
export function GuideBar({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { project } = useActiveProject();
  const { data: experiments = [] } = useExperiments(project?.id ?? null);
  const { pathname, search, hash } = useLocation();
  const { focus, baseline } = guideTargets(experiments);
  if (!open || !focus) return null;

  const params = new URLSearchParams(search);
  const onFocus = params.get("exp") === String(focus.id);
  const steps: Step[] = [
    {
      key: "open",
      label: `${focus.code} 열기`,
      to: `/notebook?exp=${focus.id}`,
      active: pathname === "/notebook" && onFocus && !params.has("compare"),
    },
    ...(baseline
      ? [
          {
            key: "compare",
            label: `${josa(baseline.code, "과/와")} 비교`,
            to: `/notebook?exp=${focus.id}&compare=${baseline.id}`,
            active: pathname === "/notebook" && params.get("compare") === String(baseline.id),
          },
        ]
      : []),
    {
      key: "critic",
      label: "Critic 보기",
      to: `/research-ai?exp=${focus.id}#critic`,
      active: pathname === "/research-ai" && onFocus && hash !== "#proposals",
    },
    {
      key: "reject",
      label: "제안 기각해보기",
      to: `/research-ai?exp=${focus.id}#proposals`,
      active: pathname === "/research-ai" && onFocus && hash === "#proposals",
    },
  ];

  return (
    <div
      role="region"
      aria-label="데모 안내"
      className="relative flex shrink-0 flex-wrap items-center gap-x-4 gap-y-2 border-b border-brand/20 bg-brand-soft/60 py-2.5 pl-4 pr-12 text-sm sm:pl-5"
    >
      <p className="min-w-0 text-ink">
        <span className="font-semibold text-brand-strong">이 데모에서 볼 것</span>
        <span className="text-ink-muted"> — 조건을 바꾼 {focus.code}의 결과가 왜 나빠졌는지, 기록 → 계산 → AI 비판 → 결정 순으로</span>
      </p>
      <ol className="flex flex-wrap items-center gap-x-1 gap-y-1.5" aria-label="권장 순서">
        {steps.map((s, i) => (
          <li key={s.key} className="flex items-center gap-1">
            {i > 0 && <span aria-hidden className="text-ink-faint">→</span>}
            <Link
              to={s.to}
              aria-current={s.active ? "step" : undefined}
              className={clsx(
                "inline-flex items-center gap-1 whitespace-nowrap rounded-md border px-2.5 py-1 text-xs font-semibold shadow-sm transition-colors",
                s.active
                  ? "border-brand bg-brand text-white"
                  : "border-brand/50 bg-surface text-brand-strong hover:border-brand hover:bg-brand hover:text-white",
              )}
            >
              {"①②③④"[i]} {s.label}
              <span aria-hidden>›</span>
            </Link>
            {s.key === "reject" && isDemo && (
              <span className="text-xs text-ink-faint" title="데모는 읽기 전용입니다. 기각과 사유 기록은 로컬 실행에서 저장됩니다.">
                (데모: 읽기 전용)
              </span>
            )}
          </li>
        ))}
      </ol>
      <button
        type="button"
        onClick={onClose}
        className="absolute right-3 top-2 grid h-7 w-7 place-items-center rounded-md text-lg leading-none text-ink-muted hover:bg-surface hover:text-ink"
        aria-label="안내 닫기"
        title="안내 닫기 (헤더의 ‘안내’로 다시 열기)"
      >
        ×
      </button>
    </div>
  );
}

/** Open/closed state of the guide bar, remembered per browser. */
export function useGuideBar(): { open: boolean; show: () => void; dismiss: () => void } {
  const [open, setOpen] = useState(() => !readDismissed());
  return {
    open,
    show: () => {
      writeDismissed(false);
      setOpen(true);
    },
    dismiss: () => {
      writeDismissed(true);
      setOpen(false);
    },
  };
}
