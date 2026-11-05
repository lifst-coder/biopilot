import { useEffect } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useSelectedExperiment } from "@/lib/selection";
import { TABS } from "./tabs";

const EXPERIMENT_TABS = new Set(["/notebook", "/analysis", "/research-ai"]);

/** Keys, in the order the help list shows them. */
export const SHORTCUTS: Array<{ keys: string[]; label: string }> = [
  { keys: ["1", "…", "6"], label: `탭 전환 (${TABS.map((t) => t.label).join(" · ")})` },
  { keys: ["["], label: "이전 실험 (Notebook · Analysis · Research AI)" },
  { keys: ["]"], label: "다음 실험" },
  { keys: ["/"], label: "기록 검색 열기 (Overview)" },
  { keys: ["?"], label: "이 목록 열기 · 닫기" },
];

/** True when the key press belongs to a text field, select or editable element. */
function typing(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  if (!el || !el.tagName) return false;
  return el.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName);
}

/** Focus the Overview search box once it has rendered (lazy tab chunk). */
function focusSearch(tries = 20): void {
  const input = document.querySelector<HTMLInputElement>("[data-global-search]");
  if (input) {
    input.focus();
    input.scrollIntoView({ block: "center" });
  } else if (tries > 0) {
    window.setTimeout(() => focusSearch(tries - 1), 50);
  }
}

/**
 * Keyboard navigation: tab switch (1–6), previous/next experiment ([ ]), search (/), and
 * "?" for the list of keys. Ignored while typing and with Ctrl/⌘/Alt held.
 */
export function Shortcuts({ open, setOpen }: { open: boolean; setOpen: (v: boolean) => void }) {
  const navigate = useNavigate();
  const { pathname, search } = useLocation();
  const { experiments, selectedId, select } = useSelectedExperiment();

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.ctrlKey || e.metaKey || e.altKey || typing(e.target)) return;
      if (e.key === "Escape" && open) {
        setOpen(false);
        return;
      }
      if (e.key === "?") {
        e.preventDefault();
        setOpen(!open);
        return;
      }
      const n = Number(e.key);
      if (Number.isInteger(n) && n >= 1 && n <= TABS.length) {
        e.preventDefault();
        navigate({ pathname: TABS[n - 1]!.path, search });
        return;
      }
      if (e.key === "/") {
        e.preventDefault();
        if (!pathname.startsWith("/overview")) navigate({ pathname: "/overview", search });
        focusSearch();
        return;
      }
      if ((e.key === "[" || e.key === "]") && EXPERIMENT_TABS.has(pathname) && experiments.length > 0) {
        e.preventDefault();
        const at = experiments.findIndex((x) => x.id === selectedId);
        const next = at + (e.key === "]" ? 1 : -1);
        if (next >= 0 && next < experiments.length) select(experiments[next]!.id);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, setOpen, navigate, pathname, search, experiments, selectedId, select]);

  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-ink/20 p-4 pt-24" onClick={() => setOpen(false)}>
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="shortcuts-title"
        className="w-full max-w-sm rounded-card border border-border bg-surface p-4 shadow-lg"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between">
          <h2 id="shortcuts-title" className="text-base font-semibold">
            키보드 단축키
          </h2>
          <button type="button" className="bp-btn-ghost px-2 py-0.5 text-xs" onClick={() => setOpen(false)}>
            닫기
          </button>
        </div>
        <dl className="mt-3 space-y-2 text-sm">
          {SHORTCUTS.map((s) => (
            <div key={s.label} className="flex items-baseline gap-3">
              <dt className="flex w-20 shrink-0 gap-1">
                {s.keys.map((k) =>
                  k === "…" ? (
                    <span key={k} className="text-ink-faint">
                      …
                    </span>
                  ) : (
                    <kbd key={k} className="rounded border border-border bg-subtle px-1.5 font-mono text-xs text-ink">
                      {k}
                    </kbd>
                  ),
                )}
              </dt>
              <dd className="text-ink-muted">{s.label}</dd>
            </div>
          ))}
        </dl>
        <p className="mt-3 text-xs text-ink-faint">입력 칸에 글을 쓰는 중에는 동작하지 않습니다. 이전 화면으로는 브라우저 뒤로(Alt+←).</p>
      </div>
    </div>
  );
}
