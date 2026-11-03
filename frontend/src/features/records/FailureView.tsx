import { useFailureArchive } from "@/api/queries";
import type { FailureArchiveOut, FailureCause, FailurePattern, FailureRecord } from "@/api/types";
import { Badge, DecisionLine, Disclosure, ExperimentChip, QcMark, QueryState } from "@/components";
import { formatDate, formatWithUnit } from "@/lib/format";
import { projectShortName } from "@/lib/selection";
import { pickFailureHeadline } from "./headline";
import type { ProjectLabels } from "./parts";

/** "같은 실패를 반복하고 있지 않은가?" — the largest repeat first, then types, then every failure. */
export function FailureView({ scope, labels }: { scope: number | null; labels: ProjectLabels }) {
  const query = useFailureArchive(scope);
  return <QueryState query={query}>{(data) => <Archive data={data} labels={labels} />}</QueryState>;
}

function codeOf(data: FailureArchiveOut, id: number): { code: string; projectId: number } | null {
  const f = data.archive.failures.find((x) => x.experiment.id === id);
  return f ? { code: f.experiment.code, projectId: f.experiment.project_id } : null;
}

function Archive({ data, labels }: { data: FailureArchiveOut; labels: ProjectLabels }) {
  const { archive } = data;
  const headline = pickFailureHeadline(archive);
  const others = archive.patterns.slice(headline?.kind === "pattern" ? 1 : 0);
  return (
    <div className="space-y-4">
      {headline?.kind === "pattern" ? (
        <PatternHeadline pattern={headline.pattern} data={data} labels={labels} />
      ) : archive.failure_count === 0 ? (
        <p className="bp-prose text-ink-muted">저장된 QC에 불합격(치명 플래그) 실험이 없습니다.</p>
      ) : (
        <p className="bp-prose text-ink-muted">같은 실패가 반복된 패턴은 없습니다.</p>
      )}
      <p className="px-1 text-sm tabular-nums text-ink-muted">
        분석된 실험 {archive.analyzed_count}건 중 실패(QC 치명 플래그) <b className="text-crit">{archive.failure_count}</b>건 · 반복 패턴{" "}
        <b className="text-ink">{archive.patterns.length}</b>개
      </p>

      {others.length > 0 && (
        <section className="rounded-card border border-border bg-surface p-4">
          <h2 className="text-base font-semibold">다른 반복 패턴</h2>
          <ul className="mt-2 divide-y divide-border/60">
            {others.map((p) => (
              <li key={p.id} className="py-2.5">
                <PatternBody pattern={p} data={data} labels={labels} />
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="rounded-card border border-border bg-surface p-4">
        <h2 className="text-base font-semibold">실패 유형</h2>
        <p className="mt-1 text-sm text-ink-muted">부모 실험 대비 무엇을 바꾼 뒤 실패했는지 (실험마다 한 유형)</p>
        <ul className="mt-2 divide-y divide-border/60">
          {archive.types.map((t) => (
            <li key={t.id} className="grid gap-x-4 gap-y-1 py-2 sm:grid-cols-[minmax(0,1fr)_4rem] sm:items-baseline">
              <div className="min-w-0">
                <span className="text-sm font-medium">{t.label}</span>
                <div className="mt-1 flex flex-wrap gap-1">
                  {t.experiment_ids.map((id) => {
                    const c = codeOf(data, id);
                    return c ? (
                      <ExperimentChip key={id} id={id} code={c.code} projectId={c.projectId} projectLabel={labels[c.projectId]} qc="fail" />
                    ) : null;
                  })}
                </div>
              </div>
              <div className="order-first text-sm font-semibold tabular-nums sm:order-none sm:text-right">
                {t.count}
                <span className="font-normal text-ink-muted">회</span>
              </div>
            </li>
          ))}
        </ul>
      </section>

      <Disclosure
        title={`실패 기록 ${archive.failure_count}건`}
        summary="원인 가설(규칙)과 근거 실험 · 그 뒤 내려진 결정"
        tone={archive.failure_count ? "crit" : "default"}
      >
        <ul className="divide-y divide-border">
          {archive.failures.map((f) => (
            <FailureItem key={f.experiment.id} record={f} data={data} labels={labels} />
          ))}
        </ul>
      </Disclosure>
    </div>
  );
}

function Chain({ pattern, data, labels }: { pattern: FailurePattern; data: FailureArchiveOut; labels: ProjectLabels }) {
  return (
    <div role="group" className="flex flex-wrap items-center gap-1" aria-label="실패 순서">
      {pattern.experiment_ids.map((id, i) => {
        const c = codeOf(data, id);
        return (
          <span key={id} className="inline-flex items-center gap-1">
            {i > 0 && <span aria-hidden className="text-ink-faint">→</span>}
            {c && <ExperimentChip id={id} code={c.code} projectId={c.projectId} projectLabel={labels[c.projectId]} qc="fail" />}
          </span>
        );
      })}
      {pattern.resolution && (
        <span className="inline-flex items-center gap-1">
          <span aria-hidden className="text-ink-faint">→</span>
          <ExperimentChip
            id={pattern.resolution.id}
            code={pattern.resolution.code}
            projectId={pattern.resolution.project_id}
            projectLabel={labels[pattern.resolution.project_id]}
            qc={pattern.resolution_qc ?? "pass"}
            value={pattern.resolution_recovery?.value != null ? formatWithUnit(pattern.resolution_recovery.value, "%") : null}
          />
        </span>
      )}
    </div>
  );
}

function PatternBody({ pattern, data, labels }: { pattern: FailurePattern; data: FailureArchiveOut; labels: ProjectLabels }) {
  const code = (id: number) => codeOf(data, id)?.code ?? `#${id}`;
  return (
    <div className="space-y-1.5">
      <Chain pattern={pattern} data={data} labels={labels} />
      {pattern.shared_analytes.length > 0 && (
        <p className="text-sm">
          반복 미달 분석물: <span className="font-medium">{pattern.shared_analytes.join(", ")}</span>
        </p>
      )}
      <ul className="space-y-0.5 text-sm text-ink-muted">
        {pattern.links.map((l) => (
          <li key={`${l.kind}-${l.from_experiment_id}-${l.to_experiment_id}`}>
            {code(l.from_experiment_id)} → {code(l.to_experiment_id)}:{" "}
            {l.kind === "retry" ? "실패한 실험을 이어 다시 시도했는데 또 실패" : `같은 ${l.label ?? l.key} 값을 다시 사용 (${String(l.value)})`}
          </li>
        ))}
      </ul>
      <p className="text-sm">
        {pattern.resolution ? (
          <>
            <span className="font-medium text-ok">
              <span aria-hidden>✓ </span>벗어난 실험
            </span>{" "}
            {pattern.resolution.code} {pattern.resolution.title}
            {pattern.resolution_changes.length > 0 && (
              <span className="text-ink-muted"> · 바꾼 조건: {pattern.resolution_changes.map((c) => c.label).join(", ")}</span>
            )}
          </>
        ) : (
          <span className="font-medium text-crit">
            <span aria-hidden>✕ </span>아직 이 실패에서 벗어난 후속 실험이 없음
          </span>
        )}
      </p>
    </div>
  );
}

function PatternHeadline({ pattern, data, labels }: { pattern: FailurePattern; data: FailureArchiveOut; labels: ProjectLabels }) {
  return (
    <section className="rounded-card border border-crit/40 bg-surface p-4 sm:p-5" aria-labelledby="failure-headline">
      <p className="text-sm font-semibold text-crit">
        <span aria-hidden>✕ </span>같은 실패가 반복됐다
      </p>
      <div className="mt-2 flex flex-wrap items-baseline gap-x-5 gap-y-1">
        <span className="text-4xl font-semibold tabular-nums">{pattern.experiment_ids.length}회</span>
        <h2 id="failure-headline" className="bp-prose text-lg font-semibold">
          {pattern.shared_analytes.length
            ? `${pattern.shared_analytes.join("·")} 미달이 이어진 실험에서 되풀이됐다`
            : "연결된 실험에서 실패가 되풀이됐다"}
        </h2>
      </div>
      <div className="mt-3">
        <PatternBody pattern={pattern} data={data} labels={labels} />
      </div>
    </section>
  );
}

function CauseItem({ cause, labels }: { cause: FailureCause; labels: ProjectLabels }) {
  return (
    <li className="bp-prose">
      {cause.statement}
      {cause.note_excerpt && <q className="ml-1 text-ink-muted">{cause.note_excerpt}</q>}
      <span className="ml-1 inline-flex flex-wrap gap-1 align-middle">
        {cause.experiments.map((e) => (
          <ExperimentChip key={e.id} id={e.id} code={e.code} projectId={e.project_id} projectLabel={labels[e.project_id]} />
        ))}
      </span>
    </li>
  );
}

function FailureItem({ record, data, labels }: { record: FailureRecord; data: FailureArchiveOut; labels: ProjectLabels }) {
  const exp = record.experiment;
  const explanation = data.explanations.find((e) => e.experiment_id === exp.id);
  const pattern = data.archive.patterns.find((p) => p.experiment_ids.includes(exp.id));
  return (
    <li className="py-3">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <ExperimentChip id={exp.id} code={exp.code} projectId={exp.project_id} projectLabel={labels[exp.project_id]} qc="fail" />
        <span className="text-sm font-medium">{exp.title}</span>
        <span className="text-sm text-ink-faint">
          {projectShortName(record.project_name)} · {formatDate(exp.performed_on)} · {record.type_label}
        </span>
        {pattern && <Badge tone="crit">반복 {pattern.experiment_ids.length}회</Badge>}
      </div>
      <p className="mt-1 text-sm">
        <QcMark status="fail" /> 미달 분석물 {record.failed_analytes.join(", ") || "—"}
        {record.recovery?.value != null && (
          <span className="text-ink-muted"> · 평균 회수율 {formatWithUnit(record.recovery.value, "%")}</span>
        )}
      </p>
      <div className="mt-2 grid gap-4 xl:grid-cols-2">
        <div>
          <h3 className="text-sm font-semibold text-ink-muted">원인 가설 (규칙 기반)</h3>
          <ul className="mt-1 list-disc space-y-1 pl-5">
            {(explanation?.causes ?? []).map((c, i) => (
              <CauseItem key={`${c.rule}-${i}`} cause={c} labels={labels} />
            ))}
          </ul>
        </div>
        <div>
          <h3 className="text-sm font-semibold text-ink-muted">그 뒤 내려진 결정</h3>
          {explanation?.decisions.length ? (
            <ul className="mt-1 space-y-2">
              {explanation.decisions.map((d) => (
                <DecisionLine key={d.decision_id} decision={d} projectLabel={labels[exp.project_id]} projectId={exp.project_id} />
              ))}
            </ul>
          ) : (
            <p className="mt-1 text-sm text-ink-faint">
              기록된 결정 없음
              {pattern?.resolution && !pattern.experiment_ids.includes(pattern.resolution.id)
                ? ` · ${pattern.resolution.code}에서 실패를 벗어남 (${pattern.resolution.title})`
                : ""}
            </p>
          )}
        </div>
      </div>
    </li>
  );
}
