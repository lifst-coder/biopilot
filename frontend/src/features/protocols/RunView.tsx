import clsx from "clsx";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAddRunEntry, useCompleteRun, useExperimentDraft, useProtocolRun } from "@/api/queries";
import { Card, Disclosure, ErrorState, LoadingState } from "@/components";
import { formatDateTime } from "@/lib/format";
import { experimentSearch } from "@/lib/selection";
import { conditionText, deviationText } from "./format";
import type { ProtocolsNav } from "./ProtocolsPage";
import type { ProtocolRunCompletion, ProtocolRunOut, RunCondition, RunStep } from "./types";

const BIG = "min-h-[2.75rem] w-full justify-center sm:w-auto";

/** One segment per step, filled when checked: progress without arithmetic. */
function Progress({ run }: { run: ProtocolRunOut }) {
  return (
    <div className="flex gap-1" role="img" aria-label={`${run.step_count}단계 중 ${run.done_count}단계 완료`}>
      {run.steps.map((s) => (
        <span
          key={s.index}
          className={clsx(
            "h-2 flex-1 rounded-full",
            s.done ? "bg-ok" : s.index === run.current_step_index ? "bg-brand/60" : "bg-subtle",
          )}
        />
      ))}
    </div>
  );
}

function ConditionLine({
  cond,
  step,
  run,
  editable,
}: {
  cond: RunCondition;
  step: RunStep;
  run: ProtocolRunOut;
  editable: boolean;
}) {
  const add = useAddRunEntry(run.id);
  const [open, setOpen] = useState(false);
  const [value, setValue] = useState(cond.actual != null ? String(cond.actual) : "");
  const [note, setNote] = useState(cond.note);
  const id = `run-${step.index}-${cond.key}`;
  const record = (v: string | null) =>
    add.mutate(
      { kind: "actual", step_index: step.index, key: cond.key, value: v, note: v === null ? "" : note },
      { onSuccess: () => setOpen(false) },
    );
  return (
    <li className="py-2.5">
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-sm text-ink-muted">{cond.label}</span>
        <span className="text-right">
          {cond.deviated ? (
            <>
              <s className="mr-2 font-mono text-sm tabular-nums text-ink-muted">
                <span className="sr-only">계획 </span>
                {conditionText(cond.planned, cond.unit)}
              </s>
              <span className="font-mono text-lg font-semibold tabular-nums text-warn">
                <span className="sr-only">실제 </span>
                {conditionText(cond.actual, cond.unit)}
              </span>
            </>
          ) : (
            <span className="font-mono text-lg font-semibold tabular-nums">{conditionText(cond.planned, cond.unit)}</span>
          )}
        </span>
      </div>
      {cond.deviated && (
        <p className="mt-0.5 text-right text-xs text-warn">
          ! 프로토콜과 다름{cond.note && ` — ${cond.note}`}
        </p>
      )}
      {editable && !open && (
        <div className="mt-1 flex justify-end gap-3">
          <button type="button" className="text-sm font-medium text-brand hover:underline" onClick={() => setOpen(true)}>
            {cond.deviated ? "실제 값 고치기" : "값이 달랐음"}
          </button>
          {cond.deviated && (
            <button type="button" className="text-sm text-ink-muted hover:underline" disabled={add.isPending} onClick={() => record(null)}>
              계획대로 되돌리기
            </button>
          )}
        </div>
      )}
      {open && (
        <div className="mt-2 space-y-2 rounded-md bg-subtle p-3">
          <label htmlFor={id} className="block text-sm text-ink-muted">
            실제 {cond.label}
          </label>
          <div className="flex items-center gap-2">
            <input
              id={id}
              className={clsx("bp-input", cond.value_type === "number" && "text-right font-mono tabular-nums")}
              inputMode={cond.value_type === "number" ? "decimal" : undefined}
              value={value}
              onChange={(e) => setValue(e.target.value)}
              autoFocus
            />
            {cond.unit && <span className="shrink-0 text-sm text-ink-muted">{cond.unit}</span>}
          </div>
          <input
            aria-label="이유 (선택)"
            className="bp-input"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="이유 (선택)"
          />
          <div className="flex flex-wrap gap-2">
            <button type="button" className={clsx("bp-btn-primary", BIG)} disabled={!value.trim() || add.isPending} onClick={() => record(value)}>
              기록
            </button>
            <button type="button" className={clsx("bp-btn-ghost", BIG)} onClick={() => setOpen(false)}>
              취소
            </button>
          </div>
          {add.error && <ErrorState error={add.error} />}
        </div>
      )}
    </li>
  );
}

function StepCard({ run, step, onMove }: { run: ProtocolRunOut; step: RunStep; onMove: (i: number) => void }) {
  const add = useAddRunEntry(run.id);
  const [noteOpen, setNoteOpen] = useState(false);
  const [note, setNote] = useState("");
  const editable = run.status === "in_progress";
  const last = step.index === run.step_count - 1;
  const toggle = () =>
    add.mutate(
      { kind: step.done ? "uncheck" : "check", step_index: step.index, note: "" },
      {
        onSuccess: (next) => {
          if (!step.done) onMove(next.current_step_index ?? step.index);
        },
      },
    );
  return (
    <Card
      title={
        <span className="flex items-baseline gap-2">
          <span className="shrink-0 whitespace-nowrap tabular-nums text-ink-muted">{step.index + 1}단계</span>
          <span>{step.title}</span>
          {step.done && <span className="text-sm font-medium text-ok">✓ 완료</span>}
        </span>
      }
    >
      {step.detail && <p className="bp-prose -mt-2 mb-2 text-ink-muted">{step.detail}</p>}
      {step.conditions.length > 0 ? (
        <ul className="divide-y divide-border">
          {step.conditions.map((c) => (
            <ConditionLine key={`${c.key}-${String(c.actual)}`} cond={c} step={step} run={run} editable={editable} />
          ))}
        </ul>
      ) : (
        <p className="text-sm text-ink-muted">이 단계에 연결된 조건값은 없습니다.</p>
      )}
      {step.notes.length > 0 && (
        <ul className="mt-2 space-y-1">
          {step.notes.map((n, i) => (
            <li key={i} className="bp-prose rounded-md bg-warn-soft px-3 py-1.5 text-sm">
              <span className="font-medium text-warn">! 다른 점</span> {n}
            </li>
          ))}
        </ul>
      )}
      {editable && (
        <div className="mt-4 space-y-2">
          <button type="button" className={clsx(step.done ? "bp-btn-ghost" : "bp-btn-primary", "min-h-[3rem] w-full justify-center text-base")} disabled={add.isPending} onClick={toggle}>
            {step.done ? "완료 취소" : last ? "✓ 마지막 단계 완료" : "✓ 이 단계 완료"}
          </button>
          {noteOpen ? (
            <div className="space-y-2">
              <label className="block text-sm text-ink-muted">
                프로토콜과 다르게 한 점
                <textarea className="bp-input mt-0.5 h-20" value={note} onChange={(e) => setNote(e.target.value)} autoFocus />
              </label>
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  className={clsx("bp-btn-primary", BIG)}
                  disabled={!note.trim() || add.isPending}
                  onClick={() =>
                    add.mutate(
                      { kind: "note", step_index: step.index, note },
                      {
                        onSuccess: () => {
                          setNote("");
                          setNoteOpen(false);
                        },
                      },
                    )
                  }
                >
                  메모 기록
                </button>
                <button type="button" className={clsx("bp-btn-ghost", BIG)} onClick={() => setNoteOpen(false)}>
                  취소
                </button>
              </div>
            </div>
          ) : (
            <button type="button" className="w-full py-1 text-center text-sm font-medium text-brand hover:underline" onClick={() => setNoteOpen(true)}>
              + 다르게 한 점 메모
            </button>
          )}
          {add.error && <ErrorState error={add.error} />}
        </div>
      )}
      <div className="mt-3 flex justify-between gap-2 border-t border-border pt-3">
        <button type="button" className="bp-btn-ghost min-h-[2.5rem]" disabled={step.index === 0} onClick={() => onMove(step.index - 1)}>
          ← 이전
        </button>
        <button type="button" className="bp-btn-ghost min-h-[2.5rem]" disabled={last} onClick={() => onMove(step.index + 1)}>
          다음 →
        </button>
      </div>
    </Card>
  );
}

function Deviations({ run, title }: { run: ProtocolRunOut; title: string }) {
  if (run.deviations.length === 0) return null;
  return (
    <Card title={title}>
      <ul className="space-y-1.5">
        {run.deviations.map((d, i) => (
          <li key={i} className="bp-prose flex gap-2 text-sm">
            <span aria-hidden className={d.kind === "skipped" ? "text-ink-faint" : "font-bold text-warn"}>
              {d.kind === "skipped" ? "–" : "!"}
            </span>
            <span>{deviationText(d)}</span>
          </li>
        ))}
      </ul>
    </Card>
  );
}

function SaveAsExperiment({ run }: { run: ProtocolRunOut }) {
  const draft = useExperimentDraft(run.project_id, {}, run.status === "in_progress");
  const complete = useCompleteRun(run.id);
  const navigate = useNavigate();
  const [code, setCode] = useState<string | null>(null);
  const [title, setTitle] = useState(`${run.template.name} ${run.template.display_version} 수행`);
  const [day, setDay] = useState(() => new Date().toLocaleDateString("sv-SE"));
  const [observations, setObservations] = useState("");
  const [preview, setPreview] = useState<ProtocolRunCompletion | null>(null);
  const effectiveCode = code ?? draft.data?.suggested_code ?? "";
  const body = (dry: boolean) => ({
    code: effectiveCode,
    title,
    author: run.operator,
    performed_on: day,
    observations,
    dry_run: dry,
  });
  return (
    <div className="space-y-3">
      <div className="grid gap-3 sm:grid-cols-[8rem_1fr_10rem]">
        <label className="text-sm text-ink-muted">
          실험 코드
          <input className="bp-input mt-0.5" value={effectiveCode} onChange={(e) => setCode(e.target.value)} />
        </label>
        <label className="text-sm text-ink-muted">
          제목
          <input className="bp-input mt-0.5" value={title} onChange={(e) => setTitle(e.target.value)} />
        </label>
        <label className="text-sm text-ink-muted">
          수행일
          <input type="date" className="bp-input mt-0.5" value={day} onChange={(e) => setDay(e.target.value)} />
        </label>
      </div>
      <label className="block text-sm text-ink-muted">
        관찰
        <textarea className="bp-input mt-0.5 h-24" value={observations} onChange={(e) => setObservations(e.target.value)} placeholder="- 추출액 색, 피크 모양 등" />
      </label>
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          className={clsx("bp-btn-ghost", BIG)}
          disabled={!effectiveCode.trim() || !title.trim() || complete.isPending}
          onClick={() => complete.mutate(body(true), { onSuccess: setPreview })}
        >
          저장 전 미리보기
        </button>
        <button
          type="button"
          className={clsx("bp-btn-primary", BIG)}
          disabled={!preview || complete.isPending}
          onClick={() =>
            complete.mutate(body(false), {
              onSuccess: (done) => {
                if (done.experiment_id) navigate({ pathname: "/notebook", search: experimentSearch(done.experiment_id, run.project_id) });
              },
            })
          }
        >
          실험 기록으로 저장
        </button>
      </div>
      {complete.error && <ErrorState error={complete.error} />}
      {preview && (
        <div className="space-y-2 rounded-md border border-border p-3">
          <p className="text-sm font-medium">저장될 원본 메모 (저장 후 변경 불가)</p>
          <pre className="whitespace-pre-wrap break-words font-sans text-sm leading-relaxed">{preview.experiment.raw_note}</pre>
        </div>
      )}
    </div>
  );
}

/** Step-by-step run of a protocol version; completed runs show what became of them. */
export function RunView({ runId, go }: { runId: number; go: ProtocolsNav }) {
  const run = useProtocolRun(runId);
  const [selected, setSelected] = useState<number | null>(null);
  if (run.isPending) return <LoadingState />;
  if (run.isError) return <ErrorState error={run.error} />;
  const r = run.data;
  const index = selected ?? r.current_step_index ?? r.step_count - 1;
  const step = r.steps[Math.min(index, r.steps.length - 1)];
  const finished = r.status === "completed";

  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <p className="text-sm text-ink-muted">
          {r.template.name} <strong className="text-ink">{r.template.display_version}</strong>
          {r.operator && ` · ${r.operator}`} ·{" "}
          <span className="tabular-nums">
            {r.done_count}/{r.step_count}단계 완료
          </span>
        </p>
        <Progress run={r} />
      </div>

      {finished && (
        <Card title="완료된 실행" subtitle={r.completed_at ? formatDateTime(r.completed_at) : undefined}>
          {r.experiment_id ? (
            <Link className="font-medium text-brand hover:underline" to={{ pathname: "/notebook", search: experimentSearch(r.experiment_id, r.project_id) }}>
              저장된 실험 기록 열기 →
            </Link>
          ) : null}
        </Card>
      )}

      {step && <StepCard run={r} step={step} onMove={(i) => setSelected(i)} />}

      <Deviations run={r} title={finished ? "프로토콜과 다른 점" : "지금까지 프로토콜과 다른 점"} />

      <Disclosure title="전체 단계" summary={`${r.done_count}/${r.step_count} 완료`}>
        <ol className="space-y-1">
          {r.steps.map((s) => (
            <li key={s.index}>
              <button
                type="button"
                className={clsx(
                  "flex w-full items-center gap-2 rounded-md px-2 py-2 text-left text-sm hover:bg-subtle",
                  s.index === step?.index && "bg-brand-soft",
                )}
                onClick={() => setSelected(s.index)}
              >
                <span aria-hidden className={clsx("w-4 font-bold", s.done ? "text-ok" : "text-ink-faint")}>
                  {s.done ? "✓" : "○"}
                </span>
                <span className="tabular-nums text-ink-muted">{s.index + 1}.</span>
                <span className="min-w-0 flex-1">{s.title}</span>
                <span className="sr-only">{s.done ? "완료" : "남음"}</span>
                {s.conditions.some((c) => c.deviated) || s.notes.length > 0 ? (
                  <span className="text-xs font-medium text-warn">! 다름</span>
                ) : null}
              </button>
            </li>
          ))}
        </ol>
      </Disclosure>

      {!finished && (
        <Disclosure
          title="실험 기록으로 저장"
          summary={r.current_step_index === null ? "모든 단계 완료 — 저장할 수 있습니다" : "남은 단계는 ‘완료 표시 없음’으로 기록됩니다"}
          tone={r.current_step_index === null ? "ok" : "default"}
          defaultOpen={r.current_step_index === null}
          key={String(r.current_step_index === null)}
        >
          <SaveAsExperiment run={r} />
        </Disclosure>
      )}
      <button type="button" className="text-sm text-brand hover:underline" onClick={() => go("lineage")}>
        ← 프로토콜 목록
      </button>
    </div>
  );
}
