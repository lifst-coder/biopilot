import clsx from "clsx";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { demoProfile, isDemo, switchDemoProfile } from "@/api/demo";
import { usePartnerMode } from "@/api/queries";
import { Badge } from "@/components";
import { PartnerPanel } from "@/features/partner-panel/PartnerPanel";
import { useActiveProject } from "@/lib/selection";
import { GuideBar, useGuideBar } from "./GuideBar";
import { TABS } from "./tabs";

/**
 * Header + tab navigation + main outlet + Research Partner panel.
 * ≥ lg: fixed-height shell, main and the right-hand partner panel scroll independently.
 * < lg: one scrolling page — the header wraps and the partner panel moves below the main
 * content at full width, so nothing is squeezed or scrolls sideways.
 */
export function AppShell() {
  const { project } = useActiveProject();
  const { data: mode } = usePartnerMode();
  const { search } = useLocation();
  const guide = useGuideBar();
  return (
    <div className="flex min-h-full flex-col lg:h-full">
      <header className="flex shrink-0 flex-wrap items-center gap-x-6 gap-y-2 border-b border-border bg-surface px-4 py-2 sm:px-5 lg:h-[var(--bp-header-height)] lg:flex-nowrap lg:py-0">
        <div className="flex items-center gap-2">
          <span className="grid h-7 w-7 place-items-center rounded-md bg-brand text-xs font-bold text-white">
            BP
          </span>
          <span className="font-semibold">BioPilot</span>
        </div>
        <nav className="-mx-1 flex max-w-full gap-1 overflow-x-auto px-1" aria-label="주요 탭">
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
              className="rounded-md border border-brand/40 px-2 py-1 font-medium text-brand hover:bg-brand-soft"
              onClick={guide.show}
            >
              안내
            </button>
          )}
          {project && <span className="min-w-0 truncate">{project.name}</span>}
          {mode && <Badge tone="ai">{mode.mode === "claude" ? "Claude 모드" : "규칙 모드"}</Badge>}
          {isDemo && <DemoSwitch />}
        </div>
      </header>
      <GuideBar open={guide.open} onClose={guide.dismiss} />
      <div className="flex flex-1 flex-col lg:min-h-0 lg:flex-row">
        <main className="min-w-0 flex-1 p-4 sm:p-5 lg:overflow-y-auto">
          <Outlet />
        </main>
        <aside className="shrink-0 border-t border-border bg-surface lg:w-partner lg:overflow-y-auto lg:border-l lg:border-t-0">
          <PartnerPanel />
        </aside>
      </div>
    </div>
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
