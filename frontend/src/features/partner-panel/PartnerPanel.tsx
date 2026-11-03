import { useState } from "react";
import { useAsk, useCritiques, usePartnerMode } from "@/api/queries";
import { EngineBadge, EvidenceChip, SeverityBadge } from "@/components";
import { useActiveProject, useSelectedExperiment } from "@/lib/selection";

/**
 * Always-visible Research Partner. Context = the experiment selected via `?exp=`.
 * Shows the latest stored critique and answers questions grounded in evidence.
 */
export function PartnerPanel() {
  const { project } = useActiveProject();
  const { selected } = useSelectedExperiment();
  const { data: mode } = usePartnerMode();
  const { data: critiques = [] } = useCritiques(selected?.id ?? null);
  const ask = useAsk();
  const [question, setQuestion] = useState("");
  const latest = critiques[0];

  const submit = () => {
    if (!project || !question.trim()) return;
    ask.mutate({ project_id: project.id, experiment_id: selected?.id ?? null, question });
  };

  return (
    <div className="flex h-full flex-col gap-4 p-4">
      <header className="flex items-center justify-between">
        <h2 className="text-sm font-semibold">Research Partner</h2>
        {mode && <EngineBadge engine={mode.mode} model={mode.model} />}
      </header>
      <p className="text-xs text-ink-muted">
        컨텍스트: {selected ? `${selected.code} · ${selected.title}` : "실험 미선택"}
      </p>

      <section className="space-y-2">
        <h3 className="text-xs font-semibold text-ink-muted">최근 비판</h3>
        {latest ? (
          <>
            <p className="text-xs">{latest.summary}</p>
            <ul className="space-y-1.5">
              {latest.findings.slice(0, 4).map((f) => (
                <li key={f.title} className="flex items-start gap-2 text-xs">
                  <SeverityBadge severity={f.severity} />
                  <span>{f.title}</span>
                </li>
              ))}
            </ul>
          </>
        ) : (
          <p className="text-xs text-ink-faint">이 실험에 저장된 비판이 없습니다.</p>
        )}
      </section>

      <section className="mt-auto space-y-2">
        <h3 className="text-xs font-semibold text-ink-muted">질문하기</h3>
        <textarea
          className="bp-input h-20 resize-none"
          placeholder="예: IS 억제는 왜 생겼을까?"
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
          onClick={submit}
        >
          {ask.isPending ? "생각 중…" : "질문"}
        </button>
        {ask.isError && <p className="text-xs text-crit">{ask.error.message}</p>}
        {ask.data && (
          <div className="space-y-2 rounded-md bg-ai-soft/60 p-3">
            <EngineBadge engine={ask.data.engine} />
            <p className="whitespace-pre-wrap text-xs">{ask.data.answer}</p>
            <div className="flex flex-wrap gap-1">
              {ask.data.evidence.map((e) => (
                <EvidenceChip key={e.key} evidence={e} />
              ))}
            </div>
          </div>
        )}
      </section>
    </div>
  );
}
