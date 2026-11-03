import { useSearchParams } from "react-router-dom";
import { PageHeader } from "@/components";
import { FAILURE_QUESTION, TABS } from "@/layout/tabs";
import { projectShortName, useActiveProject } from "@/lib/selection";
import { CrossView } from "./CrossView";
import { FailureView } from "./FailureView";
import { Segmented, type ProjectLabels } from "./parts";

const QUESTION = TABS.find((t) => t.path === "/records")?.question ?? "";
type View = "cross" | "failures";

/**
 * Records tab — everything stored so far, across projects. Two views, each answering one
 * question: "지금까지 쌓인 기록에서 무엇이 보이는가?" (`?view=` absent) and "같은 실패를
 * 반복하고 있지 않은가?" (`?view=failures`). Scope (`?scope=`) defaults to every project.
 */
export function RecordsPage() {
  const [params, setParams] = useSearchParams();
  const { projects } = useActiveProject();
  const view: View = params.get("view") === "failures" ? "failures" : "cross";
  const scopeRaw = Number(params.get("scope"));
  const scope = projects.some((p) => p.id === scopeRaw) ? scopeRaw : null;
  const labels: ProjectLabels =
    scope === null && projects.length > 1 ? Object.fromEntries(projects.map((p) => [p.id, projectShortName(p.name)])) : {};
  const set = (k: string, v: string | null) =>
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        if (v === null) next.delete(k);
        else next.set(k, v);
        return next;
      },
      { replace: true },
    );
  const inScope = projects.filter((p) => scope === null || p.id === scope);

  return (
    <div className="space-y-4">
      <PageHeader
        title="Records"
        question={view === "failures" ? FAILURE_QUESTION : QUESTION}
        actions={
          projects.length > 1 ? (
            <label className="flex items-center gap-2 text-sm text-ink-muted">
              범위
              <select
                className="bp-input w-auto py-1"
                value={scope ?? ""}
                onChange={(e) => set("scope", e.target.value || null)}
              >
                <option value="">모든 프로젝트 ({projects.length}개)</option>
                {projects.map((p) => (
                  <option key={p.id} value={p.id}>
                    {projectShortName(p.name)} · 실험 {p.experiment_count}
                  </option>
                ))}
              </select>
            </label>
          ) : undefined
        }
      />
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <Segmented<View>
          label="Records 보기"
          value={view}
          onChange={(v) => set("view", v === "failures" ? "failures" : null)}
          options={[
            { value: "cross", label: "기록 가로지르기" },
            { value: "failures", label: "실패 아카이브" },
          ]}
        />
        {inScope.length > 0 && (
          <span className="text-sm tabular-nums text-ink-muted">
            저장된 실험 {inScope.map((p) => `${projectShortName(p.name)} ${p.experiment_count}건`).join(" · ")}
          </span>
        )}
      </div>
      {view === "failures" ? (
        <FailureView scope={scope} labels={labels} />
      ) : (
        <CrossView scope={scope} labels={labels} projectCount={scope === null ? projects.length : 1} />
      )}
    </div>
  );
}
