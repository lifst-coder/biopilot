import { useEffect, useMemo, useState } from "react";
import { useLocation } from "react-router-dom";
import { demoProfile, isDemo, switchDemoProfile } from "@/api/demo";
import {
  useAllProtocolTemplates,
  useProtocolDiff,
  useProtocolLineage,
  useProtocolRecords,
  useProtocolRuns,
} from "@/api/queries";
import type { RecordExperiment } from "@/api/types";
import { Badge, Card, CodeText, Disclosure, EmptyState, ErrorState, ExperimentChip, ExperimentLink, LoadingState } from "@/components";
import { formatDate, formatRatio, formatShortDate, formatWithUnit } from "@/lib/format";
import { conditionText } from "./format";
import { StartRun } from "./StartRun";
import type { ProtocolsNav } from "./ProtocolsPage";
import type { ConditionValueChange, ProtocolVersionNode, RecordGroup } from "./types";

interface VersionRow {
  node: ProtocolVersionNode;
  name: string;
  group: RecordGroup | null;
}

/** "4/4 통과 (100%)" from stored counts; "분석 없음" when nothing was analyzed. */
function passText(g: RecordGroup | null): string {
  if (!g || g.pass_ratio == null) return "분석된 실험 없음";
  return `${g.pass_count}/${g.analyzed_count} 통과 (${formatRatio(g.pass_ratio)})`;
}

/** "5/11–5/20" — when the version's experiments were performed (stored dates). */
function usedRange(node: ProtocolVersionNode): string {
  if (!node.first_used_on || !node.last_used_on) return "사용 기록 없음";
  const a = formatShortDate(node.first_used_on);
  const b = formatShortDate(node.last_used_on);
  return a === b ? a : `${a}–${b}`;
}

/** Changed conditions (before → after), values as stored; numbers right-aligned, monospace. */
export function ChangeTable({ changes, empty }: { changes: ConditionValueChange[]; empty: string }) {
  if (changes.length === 0) return <p className="text-sm text-ink-muted">{empty}</p>;
  return (
    <table className="w-full text-sm">
      <thead className="sr-only">
        <tr>
          <th scope="col">조건</th>
          <th scope="col">이전 → 이후</th>
        </tr>
      </thead>
      <tbody>
        {changes.map((c) => (
          <tr key={c.key} className="border-t border-border align-top first:border-t-0">
            <th scope="row" className="w-2/5 py-1.5 pr-3 text-left font-normal text-ink">
              {c.label}
              {c.kind !== "changed" && (
                <span className="ml-1 text-xs text-ink-muted">({c.kind === "added" ? "추가" : "삭제"})</span>
              )}
            </th>
            <td className="break-words py-1.5 text-right font-mono tabular-nums">
              <span className="text-ink-muted">{conditionText(c.before, c.unit)}</span>
              <span className="mx-1.5 text-ink-faint" aria-label="에서">
                →
              </span>
              <span className="font-semibold">{conditionText(c.after, c.unit)}</span>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/** Short deviation text: numbers as "label a→b", text values only by name (full in title). */
function deviationSummary(devs: ConditionValueChange[]): string {
  return devs
    .map((d) =>
      typeof d.before === "number" || typeof d.after === "number"
        ? `${d.label} ${conditionText(d.before, null)}→${conditionText(d.after, d.unit)}`
        : `${d.label} ${d.kind === "added" ? "추가" : d.kind === "removed" ? "삭제" : "변경"}`,
    )
    .join(", ");
}

/** Pass ratio as a bar with the counts beside it (shape + text, not color alone). */
function PassBar({ group }: { group: RecordGroup | null }) {
  const ratio = group?.pass_ratio ?? null;
  return (
    <div className="flex items-center gap-2">
      <div
        className="h-2 w-24 shrink-0 overflow-hidden rounded-full bg-subtle"
        role="img"
        aria-label={`QC 통과율 ${formatRatio(ratio)}`}
      >
        {ratio != null && <div className="h-full rounded-full bg-ok" style={{ width: `${ratio * 100}%` }} />}
      </div>
      <span className="min-w-[8.5rem] text-right text-sm tabular-nums">{passText(group)}</span>
    </div>
  );
}

/** Demo only: where the version lineage can be seen when this project has none. */
function DemoLineageHint() {
  if (demoProfile() === "reference") {
    return (
      <p className="text-center text-sm text-ink-muted">
        프로토콜 버전 계보(버전별 바뀐 조건과 QC 통과)는 lab 시나리오에 있습니다.{" "}
        <button type="button" className="font-medium text-brand underline" onClick={() => switchDemoProfile("lab")}>
          lab 시나리오로 전환
        </button>
      </p>
    );
  }
  return (
    <p className="text-center text-sm text-ink-muted">
      헤더의 프로젝트 전환으로 다른 프로젝트를 고르면 프로토콜 버전 계보를 볼 수 있습니다.
    </p>
  );
}

/**
 * Lineage view: which protocol version's experiments pass QC (answer on top), then each
 * version's condition changes and experiments (collapsed), then an any-two-versions diff.
 */
export function LineageView({ projectId, go }: { projectId: number; go: ProtocolsNav }) {
  const lineage = useProtocolLineage(projectId);
  const records = useProtocolRecords(projectId);
  const runs = useProtocolRuns(projectId, "in_progress");
  const templates = useAllProtocolTemplates(projectId);
  // `#protocol-<id>` (the context line's protocol link): open that version and scroll to it.
  const { hash } = useLocation();
  const target = hash.startsWith("#protocol-") ? Number(hash.slice("#protocol-".length)) : null;

  const rows: VersionRow[] = useMemo(() => {
    const groups = new Map((records.data?.groups ?? []).map((g) => [Number(g.value), g]));
    return (lineage.data?.lineages ?? []).flatMap((l) =>
      l.versions.map((node) => ({ node, name: l.name, group: groups.get(node.template.template_id) ?? null })),
    );
  }, [lineage.data, records.data]);
  const recordsById = useMemo(() => {
    const out = new Map<number, RecordExperiment>();
    for (const g of records.data?.groups ?? []) for (const e of g.experiments) out.set(e.experiment_id, e);
    return out;
  }, [records.data]);

  const loaded = !lineage.isLoading && !records.isLoading;
  useEffect(() => {
    if (loaded && target !== null) document.getElementById(`protocol-${target}`)?.scrollIntoView({ block: "start" });
  }, [loaded, target]);

  if (lineage.isLoading || records.isLoading) return <LoadingState />;
  if (lineage.error) return <ErrorState error={lineage.error} />;
  if (rows.length === 0) {
    return (
      <Card>
        <EmptyState>
          저장된 프로토콜이 없습니다. 프로토콜 문서나 표를 붙여넣으면 조건을 읽어 드립니다.
        </EmptyState>
        {isDemo && <DemoLineageHint />}
        <button type="button" className="bp-btn-primary mt-3" onClick={() => go("new")}>
          + 붙여넣어 새 프로토콜
        </button>
      </Card>
    );
  }

  // Backend order: highest pass ratio first (ties by analyzed count).
  const ranked = (records.data?.groups ?? []).filter((g) => g.pass_ratio != null);
  const top = ranked[0] ?? null;
  const best = top ? rows.filter((r) => r.group && r.group.pass_ratio === top.pass_ratio) : [];
  const latest = rows[rows.length - 1]!;
  const stepsOf = new Map((templates.data?.items ?? []).map((t) => [t.id, t.steps]));

  return (
    <div className="space-y-4">
      <Card title="버전별 QC 통과" subtitle="각 버전으로 기록된 실험의 저장된 QC 판정(치명 플래그 없음 = 통과)">
        {best.length > 0 ? (
          <div className="mb-3 space-y-1">
            <p className="bp-prose text-base">
              QC 통과율이 가장 높은 버전은{" "}
              <strong>{best.map((b) => b.node.template.display_version).join(", ")}</strong> —{" "}
              {[...new Set(best.map((b) => passText(b.group)))].join(" · ")}
            </p>
            {!best.includes(latest) && (
              <p className="bp-prose text-ink-muted">
                지금 쓰는 최신 버전({latest.node.template.display_version}): {passText(latest.group)}. 펼쳐 보면 불합격
                실험이 프로토콜과 어떤 조건이 달랐는지 나옵니다.
              </p>
            )}
          </div>
        ) : (
          <p className="mb-3 text-sm text-ink-muted">아직 분석된 실험이 없습니다.</p>
        )}
        <ol className="divide-y divide-border">
          {rows.map((r) => {
            const isBest = best.includes(r);
            return (
              <li
                key={r.node.template.template_id}
                className="grid gap-x-4 gap-y-1 py-2 md:grid-cols-[1fr_auto_10rem] md:items-center"
              >
                <div className="flex min-w-0 flex-wrap items-baseline gap-x-2">
                  <span className="font-semibold">{r.node.template.display_version}</span>
                  <span className="text-sm tabular-nums text-ink-muted">{usedRange(r.node)}</span>
                  <span className="text-sm tabular-nums text-ink-muted">실험 {r.node.experiments.length}</span>
                  {isBest && <Badge tone="ok">✓ 최고</Badge>}
                  {r === latest && <Badge tone="brand">최신</Badge>}
                </div>
                <PassBar group={r.group} />
                <span className="text-sm tabular-nums text-ink-muted md:text-right">
                  {r.group?.recovery_median_pct != null
                    ? `회수율 중앙값 ${formatWithUnit(r.group.recovery_median_pct, "%")}`
                    : ""}
                </span>
              </li>
            );
          })}
        </ol>
        <div className="mt-4 border-t border-border pt-3">
          <p className="mb-2 text-sm font-medium">
            {latest.name} {latest.node.template.display_version}로 실험 시작
          </p>
          <StartRun templateId={latest.node.template.template_id} label="단계별로 진행하기" go={go} />
        </div>
      </Card>

      {(runs.data?.items.length ?? 0) > 0 && (
        <Card title="진행 중인 실행">
          <ul className="space-y-2">
            {runs.data!.items.map((run) => (
              <li key={run.id} className="flex flex-wrap items-center justify-between gap-2">
                <span className="text-sm">
                  {run.template.name} {run.template.display_version} ·{" "}
                  <span className="tabular-nums">
                    {run.done_count}/{run.step_count}단계
                  </span>
                  {run.operator && ` · ${run.operator}`} · {formatDate(run.started_at)}
                </span>
                <button type="button" className="bp-btn-ghost min-h-[2.5rem]" onClick={() => go("run", run.id)}>
                  이어서 →
                </button>
              </li>
            ))}
          </ul>
        </Card>
      )}

      <div className="space-y-2">
        <h2 className="px-1 pt-2 text-sm font-semibold text-ink-muted">버전별 바뀐 조건과 실험</h2>
        {rows.map((r, i) => (
          <VersionDetail
            key={r.node.template.template_id}
            row={r}
            first={i === 0 || rows[i - 1]!.name !== r.name}
            recordsById={recordsById}
            stepTitles={(stepsOf.get(r.node.template.template_id) ?? []).map((s) => s.title)}
            projectId={projectId}
            go={go}
            open={r.node.template.template_id === target}
          />
        ))}
        {rows.length > 1 && <CompareVersions rows={rows} />}
      </div>
    </div>
  );
}

function VersionDetail({
  row,
  first,
  recordsById,
  stepTitles,
  projectId,
  go,
  open,
}: {
  /** Start expanded (linked to with `#protocol-<id>`). */
  open: boolean;
  row: VersionRow;
  first: boolean;
  recordsById: Map<number, RecordExperiment>;
  stepTitles: string[];
  projectId: number;
  go: ProtocolsNav;
}) {
  const { node } = row;
  const t = node.template;
  const summary = first
    ? "첫 버전"
    : node.changes_from_previous.length
      ? `바뀐 조건: ${node.changes_from_previous.map((c) => c.label).join(", ")}`
      : "조건 변경 없음";
  return (
    <Disclosure
      id={`protocol-${t.template_id}`}
      className="scroll-mt-4"
      defaultOpen={open}
      title={`${row.name} ${t.display_version}`}
      summary={summary}
      tone={row.group && row.group.fail_count > 0 ? "warn" : "default"}
    >
      <div className="space-y-4">
        <p className="bp-prose text-ink-muted">
          {node.description ? <CodeText text={node.description} projectId={projectId} /> : "설명 없음"}
          <span className="block text-sm">
            {usedRange(node)} 사용 · 등록 {formatDate(t.created_at)} · {t.author || "작성자 미기재"}
            {t.source_experiment_code && t.source_experiment_id != null && (
              <>
                {" · 계기 실험 "}
                <ExperimentLink id={t.source_experiment_id} projectId={projectId}>
                  {t.source_experiment_code}
                </ExperimentLink>
              </>
            )}
          </span>
        </p>
        {!first && (
          <section>
            <h3 className="mb-1 text-sm font-semibold">이전 버전 대비 바뀐 조건</h3>
            <ChangeTable changes={node.changes_from_previous} empty="조건 값은 이전 버전과 같습니다." />
          </section>
        )}
        <section>
          <h3 className="mb-1 text-sm font-semibold">이 버전으로 기록된 실험 · {passText(row.group)}</h3>
          {node.experiments.length === 0 ? (
            <p className="text-sm text-ink-muted">아직 없습니다.</p>
          ) : (
            <ul className="space-y-1.5">
              {node.experiments.map((e) => {
                const rec = recordsById.get(e.experiment_id);
                return (
                  <li key={e.experiment_id} className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 text-sm">
                    <ExperimentChip
                      id={e.experiment_id}
                      code={e.code}
                      projectId={projectId}
                      qc={rec?.qc_status ?? "not_analyzed"}
                      value={rec?.recovery_mean_pct != null ? formatWithUnit(rec.recovery_mean_pct, "%") : null}
                      title={e.title}
                    />
                    <span
                      className="min-w-0 text-ink-muted"
                      title={e.deviations
                        .map((d) => `${d.label}: ${conditionText(d.before, d.unit)} → ${conditionText(d.after, d.unit)}`)
                        .join("\n")}
                    >
                      {e.deviations.length === 0 ? "프로토콜 그대로" : `다른 조건: ${deviationSummary(e.deviations)}`}
                    </span>
                    {rec?.qc_status === "fail" && (
                      <span className="text-sm">
                        왜 실패?{" "}
                        <ExperimentLink id={e.experiment_id} projectId={projectId} tab="/analysis">
                          판정 근거
                        </ExperimentLink>
                        {" · "}
                        <ExperimentLink id={e.experiment_id} projectId={projectId} tab="/research-ai" hash="#critic">
                          AI 비판
                        </ExperimentLink>
                      </span>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </section>
        {stepTitles.length > 0 && (
          <section>
            <h3 className="mb-1 text-sm font-semibold">단계</h3>
            <ol className="list-decimal space-y-0.5 pl-5 text-sm">
              {stepTitles.map((s, i) => (
                <li key={`${i}-${s}`}>{s}</li>
              ))}
            </ol>
          </section>
        )}
        <StartRun templateId={t.template_id} label={`${t.display_version}로 실험 시작`} go={go} />
      </div>
    </Disclosure>
  );
}

function CompareVersions({ rows }: { rows: VersionRow[] }) {
  const [a, setA] = useState(rows[0]!.node.template.template_id);
  const [b, setB] = useState(rows[rows.length - 1]!.node.template.template_id);
  const diff = useProtocolDiff(a, b);
  const pick = (value: number, set: (v: number) => void, label: string) => (
    <label className="text-sm text-ink-muted">
      {label}
      <select className="bp-input mt-0.5 w-auto" value={value} onChange={(e) => set(Number(e.target.value))}>
        {rows.map((r) => (
          <option key={r.node.template.template_id} value={r.node.template.template_id}>
            {r.name} {r.node.template.display_version}
          </option>
        ))}
      </select>
    </label>
  );
  return (
    <Disclosure title="두 버전 비교" summary="조건값 단위">
      <div className="space-y-3">
        <div className="flex flex-wrap items-end gap-3">
          {pick(a, setA, "기준")}
          <span className="pb-2 text-ink-faint" aria-hidden>
            →
          </span>
          {pick(b, setB, "비교")}
        </div>
        {a === b ? (
          <p className="text-sm text-ink-muted">서로 다른 두 버전을 고르세요.</p>
        ) : diff.error ? (
          <ErrorState error={diff.error} />
        ) : diff.data ? (
          <ChangeTable changes={diff.data.changes} empty="두 버전의 조건 값이 같습니다." />
        ) : (
          <LoadingState />
        )}
      </div>
    </Disclosure>
  );
}
