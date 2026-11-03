import { useState } from "react";
import { Badge } from "@/components";
import type { ConditionField, ConditionIssue } from "./types";

export type ConditionValues = Record<string, unknown>;

interface Props {
  fields: ConditionField[];
  value: ConditionValues;
  onChange: (next: ConditionValues) => void;
  issues: ConditionIssue[];
}

const NUMBER_RE = /^-?\d+(\.\d+)?$/;

/** Parse a free-form custom value: numeric text becomes a number, anything else stays text. */
export function parseCustomValue(text: string): string | number {
  const trimmed = text.trim();
  return NUMBER_RE.test(trimmed) ? Number(trimmed) : text;
}

/**
 * Condition-block editor. Known keys come from `/api/eln/condition-fields` with their
 * unit and input type; extra keys are free-form (unit belongs in the key name, e.g.
 * `centrifuge_rpm`). Template issues from the server are shown next to each field.
 */
export function ConditionBlockEditor({ fields, value, onChange, issues }: Props) {
  const known = new Set(fields.map((f) => f.key));
  const [newKey, setNewKey] = useState("");
  const [newValue, setNewValue] = useState("");
  const issuesByKey = new Map<string, ConditionIssue[]>();
  for (const issue of issues) issuesByKey.set(issue.key, [...(issuesByKey.get(issue.key) ?? []), issue]);

  const set = (key: string, v: unknown) => {
    const next = { ...value };
    if (v === "" || v === null || v === undefined || (typeof v === "number" && Number.isNaN(v))) delete next[key];
    else next[key] = v;
    onChange(next);
  };
  const custom = Object.entries(value).filter(([k]) => !known.has(k));

  return (
    <div className="space-y-3">
      <div className="grid gap-x-4 gap-y-2 md:grid-cols-2">
        {fields.map((f) => {
          const id = `cond-${f.key}`;
          const current = value[f.key];
          const fieldIssues = issuesByKey.get(f.key) ?? [];
          const hasError = fieldIssues.some((i) => i.level === "error");
          return (
            <div key={f.key}>
              <label htmlFor={id} className="mb-0.5 flex items-center gap-1 text-xs text-ink-muted">
                {f.label}
              </label>
              {f.value_type === "choice" ? (
                <select
                  id={id}
                  className="bp-input py-1 text-xs"
                  value={current === undefined ? "" : String(current)}
                  onChange={(e) => set(f.key, e.target.value)}
                >
                  <option value="">—</option>
                  {f.options.map((o) => (
                    <option key={o} value={o}>
                      {o}
                    </option>
                  ))}
                </select>
              ) : (
                <div className="flex items-center gap-1">
                  <input
                    id={id}
                    type={f.value_type === "number" ? "number" : "text"}
                    step="any"
                    aria-invalid={hasError}
                    className={`bp-input py-1 text-xs ${hasError ? "border-crit" : ""}`}
                    value={current === undefined || current === null ? "" : String(current)}
                    onChange={(e) =>
                      set(f.key, f.value_type === "number" ? (e.target.value === "" ? "" : Number(e.target.value)) : e.target.value)
                    }
                  />
                  {f.unit && <span className="w-8 shrink-0 font-mono text-xs text-ink-faint">{f.unit}</span>}
                </div>
              )}
              {fieldIssues.map((i) => (
                <p key={i.code} className={`mt-0.5 text-xs ${i.level === "error" ? "text-crit" : "text-warn"}`}>
                  {i.message}
                </p>
              ))}
            </div>
          );
        })}
      </div>

      <div>
        <h4 className="mb-1 text-xs font-semibold text-ink-muted">추가 조건 (자유 키 · 단위는 키 이름에, 예: centrifuge_rpm)</h4>
        {custom.length > 0 && (
          <ul className="mb-2 space-y-1">
            {custom.map(([k, v]) => (
              <li key={k} className="flex items-center gap-2 text-xs">
                <span className="w-40 truncate font-mono">{k}</span>
                <input
                  aria-label={`${k} 값`}
                  className="bp-input py-1 text-xs"
                  value={String(v)}
                  onChange={(e) => set(k, parseCustomValue(e.target.value))}
                />
                {(issuesByKey.get(k) ?? []).map((i) => (
                  <Badge key={i.code} tone={i.level === "error" ? "crit" : "warn"}>
                    {i.message}
                  </Badge>
                ))}
                <button type="button" className="bp-btn-ghost px-2 py-0.5 text-xs" onClick={() => set(k, undefined)}>
                  삭제
                </button>
              </li>
            ))}
          </ul>
        )}
        <div className="flex items-center gap-2">
          <input
            aria-label="새 조건 키"
            placeholder="키 (예: centrifuge_rpm)"
            className="bp-input w-48 py-1 font-mono text-xs"
            value={newKey}
            onChange={(e) => setNewKey(e.target.value.replace(/\s+/g, "_"))}
          />
          <input
            aria-label="새 조건 값"
            placeholder="값"
            className="bp-input py-1 text-xs"
            value={newValue}
            onChange={(e) => setNewValue(e.target.value)}
          />
          <button
            type="button"
            className="bp-btn-ghost shrink-0 whitespace-nowrap px-2 py-1 text-xs"
            disabled={!newKey.trim() || !newValue.trim() || known.has(newKey.trim())}
            onClick={() => {
              set(newKey.trim(), parseCustomValue(newValue));
              setNewKey("");
              setNewValue("");
            }}
          >
            추가
          </button>
        </div>
      </div>
    </div>
  );
}
