import type { CritiqueOut } from "@/api/types";
import { Card, EngineBadge, EvidenceChip, SeverityBadge } from "@/components";
import { formatDateTime } from "@/lib/format";

/** Findings with evidence chips. Numbers shown in chips are stored evidence values. */
export function CritiqueView({ critique, historyCount }: { critique: CritiqueOut; historyCount: number }) {
  const evidence = new Map(critique.evidence.map((e) => [e.key, e]));
  return (
    <Card
      title="비판적 검토"
      subtitle={`비판 #${critique.id} · ${formatDateTime(critique.created_at)} · 이력 ${historyCount}건`}
      actions={<EngineBadge engine={critique.engine} model={critique.model} />}
    >
      <p className="mb-3 text-sm">{critique.summary}</p>
      {critique.fallback_reason && (
        <p className="mb-3 rounded-md bg-warn-soft px-3 py-2 text-xs text-warn">
          Claude 결과를 사용하지 않고 규칙 모드로 대체: {critique.fallback_reason}
        </p>
      )}
      <ul className="space-y-3">
        {critique.findings.map((f) => (
          <li key={f.title} className="rounded-md border border-border p-3">
            <div className="mb-1 flex items-center gap-2">
              <SeverityBadge severity={f.severity} />
              <span className="text-sm font-medium">{f.title}</span>
            </div>
            <p className="text-xs text-ink-muted">{f.body}</p>
            {f.evidence_keys.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1">
                {f.evidence_keys.map((k) => {
                  const ev = evidence.get(k);
                  return ev ? <EvidenceChip key={k} evidence={ev} /> : null;
                })}
              </div>
            )}
          </li>
        ))}
      </ul>
      <details className="mt-3 text-xs">
        <summary className="cursor-pointer text-ink-muted">근거 전체 ({critique.evidence.length})</summary>
        <div className="mt-2 flex flex-wrap gap-1">
          {critique.evidence.map((e) => (
            <EvidenceChip key={e.key} evidence={e} />
          ))}
        </div>
      </details>
    </Card>
  );
}
