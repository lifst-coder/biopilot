import { useProjects } from "@/api/queries";
import type { ConditionUsage, PrecedentCase, PrecedentsOut } from "@/api/types";
import { Badge, CodeText, DecisionLine, Disclosure, ExperimentChip } from "@/components";
import { formatDate, formatWithUnit } from "@/lib/format";
import { projectShortName } from "@/lib/selection";

/**
 * "과거에 같은 증상이 있었고 그때 이렇게 결론 내렸다" — the output only accumulated records
 * can give. Earlier same-symptom failures (any project, best match first) with the
 * decisions recorded then, plus other projects' use of the condition value this
 * experiment changed to. Rendered only when there is at least one case or usage.
 */
export function PrecedentCard({ data, currentProjectId }: { data: PrecedentsOut; currentProjectId: number | null }) {
  const { data: projects = [] } = useProjects();
  const short = (id: number) => {
    const p = projects.find((x) => x.id === id);
    return p && id !== currentProjectId ? projectShortName(p.name) : null;
  };
  if (data.cases.length === 0 && data.condition_usage.length === 0) return null;
  const [first, ...rest] = data.cases;
  return (
    <section
      className="rounded-card border-2 border-brand/40 bg-surface p-4 sm:p-5"
      aria-labelledby="precedent-title"
      data-testid="precedents"
    >
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h2 id="precedent-title" className="text-lg font-semibold">
          과거에 같은 증상이 있었다
        </h2>
        <Badge tone="brand">기록에서 찾은 사례 {data.cases.length}건</Badge>
      </div>
      <p className="bp-prose mt-1 text-ink-muted">
        이 실험보다 먼저 같은 방식으로 실패한 기록과, 그때 내린 결론입니다. 모든 프로젝트를 찾았습니다.
      </p>

      {first && <CaseView c={first} short={short} />}

      {data.condition_usage.map((u) => (
        <UsageView key={`${u.key}-${u.project_id}`} usage={u} short={short} />
      ))}

      {rest.length > 0 && (
        <Disclosure className="mt-3" title={`다른 사례 ${rest.length}건`} summary={<CodeText text={rest.map((c) => c.experiment.code).join(" · ")} />}>
          <div className="space-y-4">
            {rest.map((c) => (
              <CaseView key={c.experiment.id} c={c} short={short} nested />
            ))}
          </div>
        </Disclosure>
      )}
    </section>
  );
}

function CaseView({ c, short, nested = false }: { c: PrecedentCase; short: (id: number) => string | null; nested?: boolean }) {
  const label = short(c.experiment.project_id);
  return (
    <article className={nested ? "" : "mt-4 rounded-md bg-subtle/60 p-3 sm:p-4"}>
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <ExperimentChip
          id={c.experiment.id}
          code={c.experiment.code}
          projectId={c.experiment.project_id}
          projectLabel={label}
          qc="fail"
          value={c.recovery_mean_pct != null ? formatWithUnit(c.recovery_mean_pct, "%") : null}
        />
        <span className="text-sm font-medium">
          <CodeText text={c.experiment.title} projectId={c.experiment.project_id} />
        </span>
        <span className="text-sm text-ink-faint">
          {label ? `${label} 프로젝트 · ` : ""}
          {formatDate(c.experiment.performed_on)}
        </span>
      </div>
      <ul className="mt-1.5 flex flex-wrap gap-1" aria-label="같은 증상">
        {c.matches.map((m) => (
          <li key={`${m.kind}-${m.key ?? ""}`}>
            <Badge tone="warn">
              <span aria-hidden>≈&nbsp;</span>
              {m.label}
            </Badge>
          </li>
        ))}
      </ul>
      <h3 className="mt-3 text-sm font-semibold text-ink">그때 내린 결론</h3>
      {c.decisions.length > 0 || c.resolution ? (
        <ul className="mt-1.5 space-y-2.5">
          {c.decisions.map((d) => (
            <DecisionLine key={d.decision_id} decision={d} projectId={c.experiment.project_id} projectLabel={label} />
          ))}
          {c.resolution && (
            <li className="flex flex-wrap items-center gap-1 text-sm">
              <span className="font-medium text-ok">
                <span aria-hidden>✓ </span>실패에서 벗어난 실험
              </span>
              <ExperimentChip
                id={c.resolution.experiment_id}
                code={c.resolution.code}
                projectId={c.experiment.project_id}
                projectLabel={label}
                qc={c.resolution.qc_status}
                value={c.resolution.recovery_mean_pct != null ? formatWithUnit(c.resolution.recovery_mean_pct, "%") : null}
              />
              <span className="min-w-0 text-ink-muted">
                <CodeText text={c.resolution.title} projectId={c.experiment.project_id} />
              </span>
            </li>
          )}
        </ul>
      ) : (
        <p className="mt-1 text-sm text-ink-faint">기록된 결정이나 해소 실험이 없습니다.</p>
      )}
    </article>
  );
}

function UsageView({ usage, short }: { usage: ConditionUsage; short: (id: number) => string | null }) {
  const label = short(usage.project_id) ?? projectShortName(usage.project_name);
  return (
    <article className="mt-3 rounded-md border border-border p-3 sm:p-4">
      <h3 className="text-sm font-semibold">
        다른 프로젝트에서 같은 {usage.label}을(를) 쓴 기록 · {label}
      </h3>
      <p className="mt-0.5 break-words text-sm text-ink-muted">{String(usage.value)}</p>
      <div className="mt-2 flex flex-wrap items-center gap-1">
        {usage.experiments.map((e) => (
          <ExperimentChip
            key={e.experiment_id}
            id={e.experiment_id}
            code={e.code}
            projectId={usage.project_id}
            projectLabel={label}
            qc={e.qc_status}
            value={e.recovery_mean_pct != null ? formatWithUnit(e.recovery_mean_pct, "%") : null}
            title={e.title}
          />
        ))}
      </div>
      <p className="mt-1.5 text-sm tabular-nums">
        {usage.fail_count === 0 ? (
          <span className="text-ok">
            <span aria-hidden>✓ </span>그 프로젝트에서는 QC 불합격 0/{usage.analyzed_count}
          </span>
        ) : (
          <span className="text-crit">
            <span aria-hidden>✕ </span>그 프로젝트에서도 QC 불합격 {usage.fail_count}/{usage.analyzed_count}
          </span>
        )}
      </p>
    </article>
  );
}
