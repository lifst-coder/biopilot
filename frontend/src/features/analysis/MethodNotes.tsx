import type { MethodDoc } from "./types";

/** Collapsible formula sheet stored with the result (formulas · assumptions · references). */
export function MethodNotes({ method }: { method: MethodDoc | null | undefined }) {
  if (!method) return null;
  return (
    <details className="mt-3 rounded-md border border-border bg-subtle/40 px-3 py-2 text-xs">
      <summary className="cursor-pointer select-none font-medium text-ink-muted">
        공식과 가정 · {method.version}
      </summary>
      <div className="mt-2 grid gap-3 lg:grid-cols-2">
        <div>
          <h3 className="mb-1 font-semibold text-ink">공식</h3>
          <ul className="space-y-0.5 font-mono text-[11px] text-ink">
            {method.formulas.map((f) => (
              <li key={f}>{f}</li>
            ))}
          </ul>
        </div>
        <div>
          <h3 className="mb-1 font-semibold text-ink">가정</h3>
          <ul className="list-disc space-y-0.5 pl-4 text-ink-muted">
            {method.assumptions.map((a) => (
              <li key={a}>{a}</li>
            ))}
          </ul>
          {method.references.length > 0 && (
            <p className="mt-2 text-ink-faint">참고: {method.references.join("; ")}</p>
          )}
        </div>
      </div>
    </details>
  );
}
