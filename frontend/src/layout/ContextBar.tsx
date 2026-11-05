import { useEffect } from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { useAllProtocolTemplates, useExperiment, useMetrics } from "@/api/queries";
import { formatDate } from "@/lib/format";
import { experimentSearch, projectShortName, useActiveProject, useSelectedExperiment } from "@/lib/selection";
import { historyIndex, previousVisit, recordVisit } from "@/lib/trail";
import { TABS } from "./tabs";

/** Tabs that show one experiment (the others show a project or every project). */
const EXPERIMENT_TABS = new Set(["/notebook", "/analysis", "/research-ai"]);

/** Sub-view names that make a screen distinct (`?view=`), per tab. */
const VIEWS: Record<string, Record<string, string>> = {
  "/records": { failures: "실패 아카이브", "": "기록 가로지르기" },
  "/protocols": { new: "붙여넣기", run: "단계별 실행", "": "버전 계보" },
};

/** Stored QC status: a glyph *and* words (never color alone). */
const QC_LABEL: Record<string, { glyph: string; text: string; className: string }> = {
  fail: { glyph: "✕", text: "QC 불합격", className: "text-crit" },
  warning: { glyph: "!", text: "QC 주의", className: "text-warn" },
  pass: { glyph: "✓", text: "QC 통과", className: "text-ok" },
  not_analyzed: { glyph: "–", text: "분석 결과 없음", className: "text-ink-faint" },
};

/** "잔류농약 QuEChERS SOP" + "v2" → "SOP v2" (full name in the link title). */
export function protocolShort(name: string, version: string): string {
  const words = name.trim().split(/\s+/);
  return `${words[words.length - 1] ?? name} ${version}`;
}

const sep = (
  <span aria-hidden className="text-ink-faint">
    ·
  </span>
);
const part =
  "rounded px-0.5 text-ink underline decoration-ink-faint/50 decoration-dotted underline-offset-4 hover:bg-subtle hover:text-brand hover:decoration-solid";

/**
 * One line above every screen: what is being looked at, each part a link to the screen
 * about that part — "잔류농약 · #024 · 2026. 10. 20. · SOP v2 · ✕ QC 불합격" — and, when the
 * user arrived from another screen, "← <that screen>" (browser Back with a visible label).
 */
export function ContextBar({ onShortcuts }: { onShortcuts?: () => void }) {
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const tab = TABS.find((t) => pathname.startsWith(t.path)) ?? null;
  const active = useActiveProject();
  const { selected } = useSelectedExperiment();
  const expTab = tab !== null && EXPERIMENT_TABS.has(tab.path);
  const exp = expTab ? selected : null;
  const { data: detail } = useExperiment(exp?.id ?? null);
  const { data: metrics } = useMetrics(exp?.id ?? null);
  const { data: templates } = useAllProtocolTemplates(detail?.protocol_template_id ? detail.project_id : null);
  const template = templates?.items.find((t) => t.id === detail?.protocol_template_id) ?? null;

  const viewKey = params.get("view") ?? "";
  const view = tab ? (VIEWS[tab.path]?.[viewKey] ?? null) : null;
  const scope = params.get("scope") ?? "";
  // Records has its own scope (every project by default); the line follows it.
  const project =
    tab?.path === "/records" && scope ? (active.projects.find((p) => String(p.id) === scope) ?? active.project) : active.project;
  const compare = params.get("compare") ?? "";
  const screen = [pathname, viewKey, exp?.id ?? "", compare, scope].join("|");
  const label = [tab?.label ?? "BioPilot", view, exp?.code, compare ? "비교" : null].filter(Boolean).join(" · ");
  const idx = historyIndex();
  const back = previousVisit(idx, screen);
  useEffect(() => {
    if (tab) recordVisit(idx, { screen, label });
  }, [idx, screen, label, tab]);

  if (!tab || !project) return null;
  const pid = project.id;
  const expSearch = exp ? experimentSearch(exp.id, exp.project_id) : "";
  const qc = metrics ? (metrics.analyzed ? metrics.qc_status : "not_analyzed") : null;
  const recordsAll = tab.path === "/records" && scope === "";

  return (
    <nav
      aria-label="지금 보는 것"
      className="mb-3 flex flex-wrap items-center gap-x-1.5 gap-y-1 text-sm text-ink-muted"
      data-testid="context-bar"
    >
      {back && (
        <>
          <button
            type="button"
            onClick={() => navigate(-1)}
            className="mr-1 inline-flex items-center gap-1 rounded-md border border-border bg-surface px-2 py-0.5 font-medium text-brand hover:bg-brand-soft"
            title="이전 화면으로 돌아가기 (브라우저 뒤로)"
          >
            <span aria-hidden>←</span>
            <span className="sr-only">돌아가기: </span>
            {back.label}
          </button>
        </>
      )}
      {recordsAll ? (
        <span className="px-0.5 text-ink">모든 프로젝트</span>
      ) : (
        <Link to={{ pathname: "/overview", search: `?project=${pid}` }} className={part} title={`${project.name} — Overview`}>
          {projectShortName(project.name)}
        </Link>
      )}
      {exp ? (
        <>
          {sep}
          <Link to={{ pathname: "/notebook", search: expSearch }} className={`${part} font-semibold`} title={`${exp.title} — Notebook 원본 기록`}>
            {exp.code}
          </Link>
          {sep}
          <Link
            to={{ pathname: "/overview", search: expSearch, hash: "#timeline" }}
            className={`${part} tabular-nums`}
            title="프로젝트 타임라인에서 이 실험의 앞뒤 보기"
          >
            {formatDate(exp.performed_on)}
          </Link>
          {template && (
            <>
              {sep}
              <Link
                to={{ pathname: "/protocols", search: `?project=${pid}`, hash: `#protocol-${template.id}` }}
                className={part}
                title={`${template.name} ${template.display_version} — 이 버전의 계보와 QC 통과`}
              >
                {protocolShort(template.name, template.display_version)}
              </Link>
            </>
          )}
          {qc && (
            <>
              {sep}
              <Link to={{ pathname: "/analysis", search: expSearch }} className={part} title="QC 판정 근거 — Analysis">
                <span aria-hidden className={`font-bold ${QC_LABEL[qc]?.className ?? ""}`}>
                  {QC_LABEL[qc]?.glyph}
                </span>
                <span className="ml-1">{QC_LABEL[qc]?.text ?? qc}</span>
              </Link>
            </>
          )}
        </>
      ) : (
        <>
          {sep}
          <span className="tabular-nums">
            {recordsAll ? "저장된 기록 전체" : `실험 ${project.experiment_count}건`}
            {view ? ` · ${view}` : ""}
          </span>
        </>
      )}
      {onShortcuts && (
        <button
          type="button"
          onClick={onShortcuts}
          className="ml-auto hidden rounded px-1 text-xs text-ink-faint hover:text-brand md:inline"
          title="키보드 단축키"
        >
          단축키 <kbd className="rounded border border-border px-1 font-mono">?</kbd>
        </button>
      )}
    </nav>
  );
}
