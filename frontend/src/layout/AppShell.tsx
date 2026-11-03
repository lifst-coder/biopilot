import clsx from "clsx";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { usePartnerMode } from "@/api/queries";
import { Badge } from "@/components";
import { PartnerPanel } from "@/features/partner-panel/PartnerPanel";
import { useActiveProject } from "@/lib/selection";
import { TABS } from "./tabs";

/** Header + tab navigation + main outlet + fixed right Research Partner panel. */
export function AppShell() {
  const { project } = useActiveProject();
  const { data: mode } = usePartnerMode();
  const { search } = useLocation();
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
          {project && <span className="truncate">{project.name}</span>}
          {mode && <Badge tone="ai">{mode.mode === "claude" ? "Claude 모드" : "규칙 모드"}</Badge>}
        </div>
      </header>
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
