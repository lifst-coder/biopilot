import clsx from "clsx";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { demoProfile, isDemo, switchDemoProfile } from "@/api/demo";
import { usePartnerMode } from "@/api/queries";
import { Badge } from "@/components";
import { PartnerPanel } from "@/features/partner-panel/PartnerPanel";
import { useActiveProject } from "@/lib/selection";
import { GuideBar, useGuideBar } from "./GuideBar";
import { TABS } from "./tabs";

/** Header + tab navigation + main outlet + fixed right Research Partner panel. */
export function AppShell() {
  const { project } = useActiveProject();
  const { data: mode } = usePartnerMode();
  const { search } = useLocation();
  const guide = useGuideBar();
  return (
    <div className="flex h-full flex-col">
      <header className="flex h-[var(--bp-header-height)] shrink-0 items-center gap-6 border-b border-border bg-surface px-5">
        <div className="flex items-center gap-2">
          <span className="grid h-7 w-7 place-items-center rounded-md bg-brand text-xs font-bold text-white">
            BP
          </span>
          <span className="font-semibold">BioPilot</span>
        </div>
        <nav className="flex gap-1" aria-label="주요 탭">
          {TABS.map((tab) => (
            <NavLink
              key={tab.path}
              to={{ pathname: tab.path, search }}
              title={tab.description}
              className={({ isActive }) =>
                clsx(
                  "rounded-md px-3 py-1.5 text-sm",
                  isActive ? "bg-brand-soft font-medium text-brand-strong" : "text-ink-muted hover:bg-subtle",
                )
              }
            >
              {tab.label}
            </NavLink>
          ))}
        </nav>
        <div className="ml-auto flex min-w-0 items-center gap-3 text-xs text-ink-muted">
          {!guide.open && (
            <button type="button" className="rounded-md px-2 py-1 text-brand hover:bg-brand-soft" onClick={guide.show}>
              안내
            </button>
          )}
          {project && <span className="truncate">{project.name}</span>}
          {mode && <Badge tone="ai">{mode.mode === "claude" ? "Claude 모드" : "규칙 모드"}</Badge>}
          {isDemo && <DemoSwitch />}
        </div>
      </header>
      <GuideBar open={guide.open} onClose={guide.dismiss} />
      <div className="flex min-h-0 flex-1">
        <main className="min-w-0 flex-1 overflow-y-auto p-5">
          <Outlet />
        </main>
        <aside className="w-partner shrink-0 overflow-y-auto border-l border-border bg-surface">
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
    <span className="flex items-center gap-1" title="백엔드 없이 저장된 시나리오(scenario.json)만 보여주는 읽기 전용 데모">
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
