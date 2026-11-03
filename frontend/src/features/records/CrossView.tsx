import { useState } from "react";
import { Link } from "react-router-dom";
import {
  useConditionFields,
  useConditionRecords,
  useCriteria,
  useOperatorRecords,
  usePeriodRecords,
} from "@/api/queries";
import type { AcceptanceCriteria, OperatorPair, PeriodRecords, RecordGap, RecordGroup } from "@/api/types";
import { Disclosure, ExperimentChip, QueryState } from "@/components";
import { formatConditionValue, formatMonth, formatNumber, formatPValue, formatShortDate, formatWithUnit } from "@/lib/format";
import { GroupHeader, GroupRow, type ProjectLabels } from "./parts";
import { pickRecordsHeadline, type RecordsHeadline } from "./headline";

const DEFAULT_KEY = "cleanup_sorbent";

interface Props {
  scope: number | null;
  labels: ProjectLabels;
  projectCount: number;
}

/**
 * "지금까지 쌓인 기록에서 무엇이 보이는가?" — one finding first (largest, from stored data),
 * then three cross-cuts: by condition value, by operator (same protocol), by period.
 */
export function CrossView({ scope, labels, projectCount }: Props) {
  const [key, setKey] = useState(DEFAULT_KEY);
  const [contains, setContains] = useState("");
  const fields = useConditionFields();
  const { data: criteria } = useCriteria();
  const conditions = useConditionRecords(key, scope, contains);
  const defaultConditions = useConditionRecords(DEFAULT_KEY, scope);
  const operators = useOperatorRecords(scope);
  const periods = usePeriodRecords(scope);
  const labelOf = (k: string) => fields.data?.find((f) => f.key === k)?.label ?? k;
  const headline = pickRecordsHeadline(operators.data, defaultConditions.data, periods.data);
  const loading = operators.isLoading || periods.isLoading || defaultConditions.isLoading;
  const worst = [...(conditions.data?.groups ?? [])]
    .filter((g) => g.fail_count > 0)
    .sort((a, b) => (b.fail_ratio ?? 0) - (a.fail_ratio ?? 0))[0];
  const significant = operators.data?.pairs.filter((p) => p.significant === true).length ?? 0;

  return (
    <div className="space-y-4">
      {loading ? (
        <p className="text-sm text-ink-faint">기록을 모으는 중…</p>
      ) : headline ? (
        <Headline headline={headline} labels={labels} labelOf={labelOf} projectCount={projectCount} />
      ) : (
        <p className="text-sm text-ink-muted">아직 두드러진 발견이 없습니다 — 아래에서 직접 가로질러 보세요.</p>
      )}

      <div className="space-y-2">
        <h2 className="px-1 pt-2 text-sm font-semibold text-ink-muted">직접 가로지르기</h2>
        <Disclosure
          title="조건값별 결과"
          summary={
            conditions.data
              ? `${labelOf(key)} · 값 ${conditions.data.groups.length}개${worst ? ` · 불합격 비율 최고: ${worst.key} ${worst.fail_count}/${worst.analyzed_count}` : ""}`
              : undefined
          }
          tone={worst ? "warn" : "default"}
        >
          <p className="bp-prose mb-3 text-ink-muted">특정 조건값을 쓴 모든 실험과 그 결과 분포. ✕ = QC 불합격, 초록 띠 = 회수율 허용 기준.</p>
          <div className="mb-3 flex flex-wrap items-end gap-3">
            <label className="flex min-w-0 flex-col gap-1 text-sm text-ink-muted">
              조건
              <select className="bp-input w-auto max-w-full" value={key} onChange={(e) => setKey(e.target.value)}>
                {(fields.data ?? [{ key: DEFAULT_KEY, label: labelOf(DEFAULT_KEY) }]).map((f) => (
                  <option key={f.key} value={f.key}>
                    {f.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex min-w-0 flex-col gap-1 text-sm text-ink-muted">
              값에 포함된 말로 묶기
              <input
                className="bp-input w-48 max-w-full"
                value={contains}
                placeholder="예: GCB"
                onChange={(e) => setContains(e.target.value)}
              />
            </label>
          </div>
          <QueryState query={conditions}>
            {(data) => (
              <>
                <GroupHeader first={labelOf(data.key)} />
                <ul className="divide-y divide-border/60">
                  {data.matched && (
                    <GroupRow
                      label={`‘${data.contains}’ 포함 (묶음)`}
                      group={data.matched}
                      criteria={criteria ?? null}
                      labels={labels}
                      highlight
                    />
                  )}
                  {data.groups.map((g) => (
                    <GroupRow key={g.key} label={g.key} group={g} criteria={criteria ?? null} labels={labels} />
                  ))}
                </ul>
              </>
            )}
          </QueryState>
        </Disclosure>

        <Disclosure
          title="작업자별 — 같은 조건 실험"
          summary={
            operators.data
              ? `같은 조건·${operators.data.window_days}일 이내 쌍 ${operators.data.pairs.length}개 · 유의한 차이 ${significant}`
              : undefined
          }
          tone={significant ? "warn" : "default"}
        >
          <QueryState query={operators}>
            {(data) => (
              <div className="space-y-4">
                <p className="bp-prose text-ink-muted">
                  조건 블록이 완전히 같고 작업자만 다른 실험 쌍({data.window_days}일 이내). 차이는 저장된 회수율 전체 행의 Welch t-검정(α{" "}
                  {data.pairs[0]?.alpha ?? 0.05}).
                </p>
                {data.pairs.length === 0 ? (
                  <p className="text-sm text-ink-faint">같은 조건의 작업자 쌍이 없습니다.</p>
                ) : (
                  <ul className="divide-y divide-border/60">
                    {data.pairs.map((p) => (
                      <PairRow key={`${p.experiment_a.experiment_id}-${p.experiment_b.experiment_id}`} pair={p} labels={labels} />
                    ))}
                  </ul>
                )}
                <div>
                  <h3 className="mb-1 text-sm font-semibold text-ink-muted">작업자별 전체 실험</h3>
                  <GroupHeader first="작업자" />
                  <ul className="divide-y divide-border/60">
                    {data.authors.map((g) => (
                      <GroupRow key={g.key} label={g.key} group={g} criteria={criteria ?? null} labels={labels} />
                    ))}
                  </ul>
                </div>
              </div>
            )}
          </QueryState>
        </Disclosure>

        <Disclosure
          title="기간별 추이와 공백"
          summary={periods.data ? periodSummary(periods.data) : undefined}
          tone={periods.data?.gaps.length ? "warn" : "default"}
        >
          <QueryState query={periods}>
            {(data) => <PeriodList data={data} criteria={criteria ?? null} labels={labels} />}
          </QueryState>
        </Disclosure>
      </div>
    </div>
  );
}

function periodSummary(p: PeriodRecords): string {
  const first = p.months[0]?.key;
  const last = p.months[p.months.length - 1]?.key;
  const range = first && last ? `${formatMonth(first)}–${formatMonth(last).replace(/^\d{4}년 /, "")}` : "";
  const gap = p.gaps[0];
  return gap
    ? `${range} · 기록 공백 ${p.gaps.length}회 (${formatShortDate(gap.start)}–${formatShortDate(gap.end)}, ${gap.days}일)`
    : `${range} · ${p.gap_days}일 이상 공백 없음`;
}

function Headline({
  headline,
  labels,
  labelOf,
  projectCount,
}: {
  headline: RecordsHeadline;
  labels: ProjectLabels;
  labelOf: (k: string) => string;
  projectCount: number;
}) {
  if (headline.kind === "operator") {
    const { pair } = headline;
    const [low, high] =
      (pair.recovery_delta_pct_points ?? 0) >= 0 ? [pair.experiment_a, pair.experiment_b] : [pair.experiment_b, pair.experiment_a];
    return (
      <section className="rounded-card border border-warn/50 bg-surface p-4 sm:p-5" aria-labelledby="records-headline">
        <p className="text-sm font-semibold text-warn">
          <span aria-hidden>! </span>가장 눈에 띄는 발견
        </p>
        <div className="mt-2 flex flex-wrap items-baseline gap-x-5 gap-y-1">
          <span className="text-4xl font-semibold tabular-nums text-ink">
            {formatNumber(Math.abs(pair.recovery_delta_pct_points ?? 0))}%p
          </span>
          <h2 id="records-headline" className="bp-prose text-lg font-semibold">
            같은 조건인데 작업자에 따라 평균 회수율이 달랐다
          </h2>
        </div>
        <ul className="mt-3 grid gap-2 text-sm sm:grid-cols-2">
          {[low, high].map((e) => (
            <li key={e.experiment_id} className="flex flex-wrap items-center gap-2 rounded-md bg-subtle px-3 py-2">
              <ExperimentChip id={e.experiment_id} code={e.code} projectId={e.project_id} projectLabel={labels[e.project_id]} qc={e.qc_status} />
              <span className="font-medium">{e.author}</span>
              <span className="ml-auto text-base font-semibold tabular-nums">{formatWithUnit(e.recovery_mean_pct, "%")}</span>
            </li>
          ))}
        </ul>
        <p className="mt-2 text-sm tabular-nums text-ink-muted">
          조건 블록 {pair.condition_key_count}개 항목 동일 · {pair.days_apart}일 간격 · Welch {formatPValue(pair.p_value)}{" "}
          ({pair.significant ? "유의" : "유의하지 않음"}, α {pair.alpha})
        </p>
        <p className="bp-prose mt-2 text-ink-muted">
          조건 블록에는 차이가 없어 실험 하나만 봐서는 드러나지 않습니다. 두 기록의 원본 메모를 나란히 보세요.{" "}
          <Link
            className="font-medium text-brand hover:underline"
            to={{
              pathname: "/notebook",
              search: `?project=${high.project_id}&exp=${high.experiment_id}&compare=${low.experiment_id}`,
            }}
          >
            원본 메모 비교 →
          </Link>
        </p>
      </section>
    );
  }
  if (headline.kind === "condition") {
    const { group } = headline;
    return (
      <section className="rounded-card border border-crit/40 bg-surface p-4 sm:p-5">
        <p className="text-sm font-semibold text-crit">
          <span aria-hidden>✕ </span>가장 눈에 띄는 발견
        </p>
        <div className="mt-2 flex flex-wrap items-baseline gap-x-5 gap-y-1">
          <span className="text-4xl font-semibold tabular-nums">
            {group.fail_count}/{group.analyzed_count}
          </span>
          <h2 className="bp-prose text-lg font-semibold">
            {labelOf(headline.key)} {formatConditionValue(group.value)}을(를) 쓴 실험의 QC 불합격
          </h2>
        </div>
        <ul className="mt-3">
          <GroupRow label={group.key} group={group} criteria={null} labels={labels} />
        </ul>
      </section>
    );
  }
  return (
    <section className="rounded-card border border-warn/50 bg-surface p-4 sm:p-5">
      <p className="text-sm font-semibold text-warn">
        <span aria-hidden>! </span>가장 눈에 띄는 발견
      </p>
      <GapLine gap={headline.gap} labels={labels} projectCount={projectCount} large />
    </section>
  );
}

function PairRow({ pair, labels }: { pair: OperatorPair; labels: ProjectLabels }) {
  const chip = (e: OperatorPair["experiment_a"]) => (
    <span className="inline-flex flex-wrap items-center gap-1">
      <ExperimentChip id={e.experiment_id} code={e.code} projectId={e.project_id} projectLabel={labels[e.project_id]} qc={e.qc_status} />
      <span className="text-sm">{e.author}</span>
      <span className="text-sm tabular-nums">{formatWithUnit(e.recovery_mean_pct, "%")}</span>
    </span>
  );
  return (
    <li className="grid gap-x-4 gap-y-1 py-2.5 sm:grid-cols-[minmax(0,1fr)_6rem_7rem_7rem] sm:items-center">
      <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
        {chip(pair.experiment_a)}
        <span aria-hidden className="text-ink-faint">↔</span>
        <span className="sr-only">대</span>
        {chip(pair.experiment_b)}
        <span className="text-xs text-ink-faint">{pair.days_apart}일 간격</span>
      </div>
      <div className="text-sm tabular-nums sm:text-right">
        <span className="text-ink-muted sm:hidden">Δ </span>
        {formatWithUnit(pair.recovery_delta_pct_points, "%p")}
      </div>
      <div className="text-sm tabular-nums text-ink-muted sm:text-right">{formatPValue(pair.p_value)}</div>
      <div className={pair.significant ? "text-sm font-medium text-warn sm:text-right" : "text-sm text-ink-muted sm:text-right"}>
        <span aria-hidden>{pair.significant ? "● " : "○ "}</span>
        {pair.significant ? "유의한 차이" : "차이 없음"}
      </div>
    </li>
  );
}

function GapLine({
  gap,
  labels,
  projectCount,
  large = false,
}: {
  gap: RecordGap;
  labels: ProjectLabels;
  projectCount: number;
  large?: boolean;
}) {
  const next = gap.after[0];
  return (
    <div className={large ? "mt-2" : ""}>
      <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
        <span className={large ? "text-4xl font-semibold tabular-nums" : "text-sm font-semibold tabular-nums text-warn"}>
          {large ? `${gap.days}일` : `! 기록 공백 ${gap.days}일`}
        </span>
        <span className={large ? "bp-prose text-lg font-semibold" : "text-sm font-medium"}>
          {formatShortDate(gap.start)} 이후 {formatShortDate(gap.end)}까지 {projectCount > 1 ? "모든 프로젝트에서 " : ""}기록이 없다
        </span>
      </div>
      <div className="mt-1.5 flex flex-wrap items-center gap-1 text-sm text-ink-muted">
        <span>직전</span>
        {gap.before.map((e) => (
          <ExperimentChip key={e.experiment_id} id={e.experiment_id} code={e.code} projectId={e.project_id} projectLabel={labels[e.project_id]} />
        ))}
        <span className="ml-2">다음</span>
        {gap.after.map((e) => (
          <ExperimentChip key={e.experiment_id} id={e.experiment_id} code={e.code} projectId={e.project_id} projectLabel={labels[e.project_id]} />
        ))}
        {next && <span className="min-w-0">{next.title}</span>}
      </div>
    </div>
  );
}

function PeriodList({ data, criteria, labels }: { data: PeriodRecords; criteria: AcceptanceCriteria | null; labels: ProjectLabels }) {
  const projectCount = data.project_ids.length;
  const gapsAfter = (m: RecordGroup) => data.gaps.filter((g) => g.start.startsWith(m.key));
  return (
    <>
      <p className="bp-prose mb-3 text-ink-muted">월별 실험 수·결과 분포·불합격 비율. {data.gap_days}일 이상 실험이 없던 기간은 공백으로 표시합니다.</p>
      <GroupHeader first="월" />
      <ul className="divide-y divide-border/60">
        {data.months.map((m) => (
          <MonthWithGaps key={m.key} month={m} gaps={gapsAfter(m)} criteria={criteria} labels={labels} projectCount={projectCount} />
        ))}
      </ul>
    </>
  );
}

function MonthWithGaps({
  month,
  gaps,
  criteria,
  labels,
  projectCount,
}: {
  month: RecordGroup;
  gaps: RecordGap[];
  criteria: AcceptanceCriteria | null;
  labels: ProjectLabels;
  projectCount: number;
}) {
  return (
    <>
      <GroupRow label={formatMonth(month.key)} group={month} criteria={criteria} labels={labels} />
      {gaps.map((g) => (
        <li key={g.start} className="-mx-2 rounded-md border-l-4 border-warn bg-warn-soft/40 px-3 py-2.5">
          <GapLine gap={g} labels={labels} projectCount={projectCount} />
        </li>
      ))}
    </>
  );
}
