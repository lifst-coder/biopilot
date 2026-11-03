import { useState } from "react";
import { useAskStream, useCritiques, useExchanges, usePartnerMode } from "@/api/queries";
import { EngineBadge, SeverityBadge } from "@/components";
import { formatDateTime } from "@/lib/format";
import { useActiveProject, useSelectedExperiment } from "@/lib/selection";
import { AnswerView } from "./AnswerView";

const SUGGESTIONS = ["회수율이 왜 낮나?", "다음 실험은 어떻게 설계할까?", "기각된 제안과 사유는?"];

/**
 * Always-visible Research Partner. Context = the experiment selected via `?exp=` (an
 * experiment code in the question overrides it). Answers stream over SSE; the final
 * answer is the validated, grounded one, and every exchange is stored.
 */
export function PartnerPanel() {
  const { project } = useActiveProject();
  const { selected } = useSelectedExperiment();
  const { data: mode } = usePartnerMode();
  const { data: critiques = [] } = useCritiques(selected?.id ?? null);
  const { data: history } = useExchanges(project?.id ?? null);
  const ask = useAskStream();
  const [question, setQuestion] = useState("");
  const latest = critiques[0];

  const submit = (q = question) => {
    if (!project || !q.trim()) return;
    ask.mutate({ project_id: project.id, experiment_id: selected?.id ?? null, question: q });
  };

  return (
    <div className="flex h-full flex-col gap-5 p-4 sm:p-5">
      <header className="flex items-center justify-between">
        <h2 className="text-base font-semibold">Research Partner</h2>
        {mode && <EngineBadge engine={mode.mode} model={mode.model} />}
      </header>
      <p className="text-sm text-ink-muted">
        컨텍스트: {selected ? `${selected.code} · ${selected.title}` : "실험 미선택 (프로젝트 수준)"}
      </p>

      <section className="space-y-2">
        <h3 className="text-sm font-semibold text-ink-muted">최근 비판</h3>
        {latest ? (
          <>
            {latest.assessments[0] && (
              <p className="bp-prose rounded-md bg-warn-soft/60 px-3 py-2">판정: {latest.assessments[0].verdict_reason}</p>
            )}
            <ul className="space-y-2">
              {latest.findings.slice(0, 4).map((f) => (
                <li key={f.title} className="flex items-start gap-2 text-sm">
                  <span className="shrink-0">
                    <SeverityBadge severity={f.severity} />
                  </span>
                  <span>{f.title}</span>
                </li>
              ))}
            </ul>
          </>
        ) : (
          <p className="text-sm text-ink-faint">이 실험에 저장된 비판이 없습니다.</p>
        )}
      </section>

      <section className="space-y-2">
        <h3 className="text-sm font-semibold text-ink-muted">질문하기</h3>
        <div className="flex flex-wrap gap-1">
          {SUGGESTIONS.map((s) => (
            <button
              key={s}
              type="button"
              className="rounded-full border border-brand/40 bg-surface px-2.5 py-1 text-xs font-medium text-brand-strong hover:bg-brand-soft"
              onClick={() => {
                setQuestion(s);
                submit(s);
              }}
            >
              {s}
            </button>
          ))}
        </div>
        <textarea
          className="bp-input h-20 resize-none"
          placeholder="예: #024 회수율이 왜 낮나?"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) submit();
          }}
        />
        <button
          type="button"
          className="bp-btn-primary w-full justify-center"
          disabled={ask.isPending || !question.trim()}
          onClick={() => submit()}
        >
          {ask.isPending ? "생각 중…" : "질문"}
        </button>
        <p className="text-sm text-ink-faint">
          답변의 각 문장은 사실·판단·추정으로 표시됩니다. 근거 없는 문장은 항상 &lsquo;추정&rsquo;입니다.
        </p>
        {ask.isError && <p className="text-sm text-crit">{ask.error.message}</p>}
        {ask.stream.replaced && (
          <p className="text-sm text-warn">임시 답변을 검증하지 못해 규칙 모드 답변으로 교체했습니다.</p>
        )}
        {ask.isPending && ask.stream.text && (
          <p className="whitespace-pre-wrap rounded-md border border-dashed border-border p-2 text-sm text-ink-muted">
            {ask.stream.text}
          </p>
        )}
        {ask.data && <AnswerView answer={ask.data} />}
      </section>

      <section className="space-y-2">
        <h3 className="text-sm font-semibold text-ink-muted">대화 기록</h3>
        {history && history.items.length > 0 ? (
          <ul className="space-y-1.5">
            {history.items.slice(0, 8).map((x) => (
              <li key={x.id}>
                <details className="text-sm">
                  <summary className="cursor-pointer">
                    <span className="text-ink-faint">{formatDateTime(x.created_at)}</span> · {x.question}
                  </summary>
                  <div className="mt-1">
                    <AnswerView answer={x.response} />
                  </div>
                </details>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-ink-faint">아직 대화가 없습니다.</p>
        )}
      </section>
    </div>
  );
}
