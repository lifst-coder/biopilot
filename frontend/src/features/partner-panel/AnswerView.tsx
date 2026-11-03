import type { Schemas } from "@/api/client";
import { Badge, EngineBadge, EvidenceChip } from "@/components";
import type { BadgeTone } from "@/components";

type AskResponse = Schemas["AskResponse"];
type Statement = Schemas["AnswerStatement"];
type StatementKind = Statement["kind"];

const KIND: Record<StatementKind, { label: string; tone: BadgeTone }> = {
  fact: { label: "사실", tone: "brand" },
  inference: { label: "판단", tone: "ai" },
  estimate: { label: "추정", tone: "warn" },
};

/** Statements shown before the "더 보기" fold. */
const VISIBLE = 6;

function StatementList({ statements }: { statements: Statement[] }) {
  return (
    <ul className="space-y-2 leading-relaxed">
      {statements.map((s, i) => (
        <li key={`${i}-${s.text}`} className="flex items-start gap-1.5">
          <span className="shrink-0">
            <Badge tone={KIND[s.kind].tone}>{KIND[s.kind].label}</Badge>
          </span>
          <span>
            {s.text}
            {s.evidence_keys.length > 0 && (
              <span className="ml-1 font-mono text-xs text-ink-faint">[{s.evidence_keys.join(", ")}]</span>
            )}
          </span>
        </li>
      ))}
    </ul>
  );
}

/**
 * A grounded answer: each statement is tagged 사실/판단/추정, numbers appear only in
 * evidence chips (stored values), and the stored records behind the answer are listed.
 */
export function AnswerView({ answer }: { answer: AskResponse }) {
  const evidence = new Map(answer.evidence.map((e) => [e.key, e]));
  return (
    <div className="space-y-2 rounded-md bg-ai-soft/60 p-3 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <EngineBadge engine={answer.engine} />
        {answer.critique_id != null && <Badge tone="neutral">비판 #{answer.critique_id}</Badge>}
      </div>
      {answer.fallback_reason && (
        <p className="rounded bg-warn-soft px-2 py-1 text-warn">규칙 모드로 대체: {answer.fallback_reason}</p>
      )}
      {answer.statements.length === 0 ? (
        <p className="whitespace-pre-wrap">{answer.answer}</p>
      ) : (
        <>
          <StatementList statements={answer.statements.slice(0, VISIBLE)} />
          {answer.statements.length > VISIBLE && (
            <details>
              <summary className="cursor-pointer text-ink-muted">
                나머지 문장 보기 ({answer.statements.length - VISIBLE})
              </summary>
              <StatementList statements={answer.statements.slice(VISIBLE)} />
            </details>
          )}
        </>
      )}
      {answer.evidence.length > 0 && (
        <details>
          <summary className="cursor-pointer text-ink-muted">근거 ({answer.evidence.length})</summary>
          <div className="mt-1 flex flex-wrap gap-1">
            {[...evidence.values()].map((e) => (
              <EvidenceChip key={e.key} evidence={e} />
            ))}
          </div>
        </details>
      )}
      {answer.sources.length > 0 && (
        <details>
          <summary className="cursor-pointer text-ink-muted">출처 ({answer.sources.length})</summary>
          <ul className="mt-1 space-y-0.5 text-sm text-ink-muted">
            {answer.sources.map((s) => (
              <li key={`${s.ref_type}-${s.ref_id}`}>
                <span className="font-mono">
                  {s.ref_type} #{s.ref_id}
                </span>{" "}
                · {s.label}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}
