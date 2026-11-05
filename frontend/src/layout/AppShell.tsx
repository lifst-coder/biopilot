import clsx from "clsx";
import { useEffect, useRef, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { demoProfile, isDemo, switchDemoProfile } from "@/api/demo";
import { usePartnerMode } from "@/api/queries";
import { Badge } from "@/components";
import { PartnerPanel } from "@/features/partner-panel/PartnerPanel";
import { useActiveProject } from "@/lib/selection";
import { ContextBar } from "./ContextBar";
import { GuideBar, useGuideBar } from "./GuideBar";
import { Shortcuts } from "./Shortcuts";
import { TABS } from "./tabs";

/**
 * Header + tab navigation + main outlet + Research Partner panel.
 * ≥ lg: fixed-height shell, main and the right-hand partner panel scroll independently.
 * < lg: one scrolling page — the header wraps and the partner panel moves below the main
 * content at full width, so nothing is squeezed or scrolls sideways.
 */
export function AppShell() {
  const { data: mode } = usePartnerMode();
  const { pathname, search } = useLocation();
  const guide = useGuideBar();
  const nav = useRef<HTMLElement>(null);
  const [keysOpen, setKeysOpen] = useState(false);
  // Narrow screens scroll the tab row sideways: keep the active tab visible (e.g. after a
  // guide-bar step jumps to Research AI, which starts off-screen at 390 px).
  useEffect(() => {
    const row = nav.current;
    const active = row?.querySelector<HTMLElement>("[aria-current='page']");
    if (!row || !active || row.scrollWidth <= row.clientWidth) return;
    const offset = active.getBoundingClientRect().left - row.getBoundingClientRect().left;
    row.scrollLeft += offset - (row.clientWidth - active.offsetWidth) / 2;
  }, [pathname]);
  return (
    <div className="flex min-h-full flex-col lg:h-full">
      {/* Wraps instead of clipping: every tab stays reachable when the project/demo controls
          need the room (e.g. 1024–1300 px with the guide bar closed). */}
      <header className="flex shrink-0 flex-wrap items-center gap-x-6 gap-y-2 border-b border-border bg-surface px-4 py-2 sm:px-5 lg:min-h-[var(--bp-header-height)]">
        <div className="flex items-center gap-2">
          <span className="grid h-7 w-7 place-items-center rounded-md bg-brand text-xs font-bold text-white">
            BP
          </span>
          <span className="font-semibold">BioPilot</span>
        </div>
        <nav ref={nav} className="-mx-1 flex max-w-full gap-1 overflow-x-auto px-1 lg:shrink-0" aria-label="주요 탭">
          {TABS.map((tab) => (
            <NavLink
              key={tab.path}
              to={{ pathname: tab.path, search }}
              title={tab.description}
              className={({ isActive }) =>
                clsx(
                  "whitespace-nowrap rounded-md px-2 py-1.5 text-sm sm:px-3",
                  isActive ? "bg-brand-soft font-medium text-brand-strong" : "text-ink-muted hover:bg-subtle",
                )
              }
            >
              {tab.label}
            </NavLink>
          ))}
        </nav>
        <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1.5 text-xs text-ink-muted lg:ml-auto lg:flex-nowrap">
          {!guide.open && (
            <button
              type="button"
              className="shrink-0 whitespace-nowrap rounded-md border border-brand/40 px-2 py-1 font-medium text-brand hover:bg-brand-soft"
              onClick={guide.show}
            >
              안내
            </button>
          )}
          <ProjectSwitch />
          {mode && <Badge tone="ai">{mode.mode === "claude" ? "Claude 모드" : "규칙 모드"}</Badge>}
          {isDemo && <DemoSwitch />}
        </div>
      </header>
      <GuideBar open={guide.open} onClose={guide.dismiss} />
      <Shortcuts open={keysOpen} setOpen={setKeysOpen} />
      <div className="flex flex-1 flex-col lg:min-h-0 lg:flex-row">
        <main className="min-w-0 flex-1 p-4 sm:p-5 lg:overflow-y-auto">
          <ContextBar onShortcuts={() => setKeysOpen(true)} />
          <Outlet />
        </main>
        <aside className="shrink-0 border-t border-border bg-surface lg:w-partner lg:overflow-y-auto lg:border-l lg:border-t-0">
          <PartnerPanel />
        </aside>
      </div>
    </div>
  );
}

/**
 * Active project switcher (`?project=`). Switching clears the experiment selection; the
 * Records tab reads every project regardless and only uses this as its default scope.
 */
function ProjectSwitch() {
  const { project, projects, selectProject } = useActiveProject();
  if (projects.length === 0) return null;
  if (projects.length === 1) return <span className="min-w-0 truncate">{projects[0]!.name}</span>;
  return (
    <label className="flex min-w-0 max-w-full items-center gap-1.5">
      <span className="shrink-0">프로젝트</span>
      <select
        aria-label="프로젝트 전환"
        className="bp-input min-w-0 max-w-[18rem] truncate py-1 text-xs font-medium text-ink"
        value={project?.id ?? ""}
        onChange={(e) => selectProject(Number(e.target.value))}
      >
        {projects.map((p) => (
          <option key={p.id} value={p.id}>
            {p.name} · 실험 {p.experiment_count}
          </option>
        ))}
      </select>
    </label>
  );
}

/** Demo build only: read-only notice + switch between the reference and lab scenarios. */
function DemoSwitch() {
  const current = demoProfile();
  return (
    <span className="flex flex-wrap items-center gap-1" title="백엔드 없이 저장된 시나리오(scenario.json)만 보여주는 읽기 전용 데모">
      <Badge tone="warn">데모 · 읽기 전용</Badge>
      <select
        aria-label="데모 시나리오"
        className="bp-input w-auto py-0.5 text-xs"
        value={current}
        onChange={(e) => switchDemoProfile(e.target.value === "lab" ? "lab" : "reference")}
      >
        <option value="reference">reference (7개 실험)</option>
        <option value="lab">lab (2개 프로젝트 · 42개 실험)</option>
      </select>
    </span>
  );
}
