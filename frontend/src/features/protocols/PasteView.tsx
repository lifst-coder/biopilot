import { useEffect, useMemo, useState } from "react";
import { demoProtocolExample } from "@/api/demo";
import { useAllProtocolTemplates, useCreateProtocolTemplate, useExtractProtocol } from "@/api/queries";
import { Badge, Card, Disclosure, EngineBadge, ErrorState } from "@/components";
import type { ProtocolsNav } from "./ProtocolsPage";
import { StartRun } from "./StartRun";
import type { ExtractedField, ExtractedStep, ProtocolExtraction, ProtocolTemplateOut } from "./types";

const STATUS: Record<ExtractedField["status"], { glyph: string; label: string; className: string }> = {
  recognized: { glyph: "✓", label: "원문에서 읽음", className: "text-ok" },
  ambiguous: { glyph: "!", label: "값이 여러 개 — 확인 필요", className: "text-warn" },
  unrecognized: { glyph: "?", label: "인식하지 못함", className: "text-ink-muted" },
};

/** Candidate value as the input's starting text (numbers as written, never rounded). */
function initialText(f: ExtractedField): string {
  return f.value == null ? "" : String(f.value);
}

function FieldRow({
  field,
  value,
  onChange,
}: {
  field: ExtractedField;
  value: string;
  onChange: (v: string) => void;
}) {
  const s = STATUS[field.status];
  const id = `pf-${field.key}`;
  const edited = value.trim() !== initialText(field).trim();
  return (
    <li className="grid gap-1 py-2.5 sm:grid-cols-[12rem_1fr] sm:gap-x-4">
      <div className="flex items-baseline justify-between gap-2 sm:block">
        <label htmlFor={id} className="text-sm font-medium text-ink">
          {field.label}
          {field.unit && !field.label.includes(`(${field.unit})`) && (
            <span className="ml-1 font-normal text-ink-muted">({field.unit})</span>
          )}
        </label>
        <span className={`flex items-center gap-1 text-xs font-medium sm:mt-0.5 ${s.className}`}>
          <span aria-hidden>{s.glyph}</span>
          {s.label}
          {edited && <Badge tone="brand">수정함</Badge>}
        </span>
      </div>
      <div className="min-w-0">
        {field.value_type === "choice" ? (
          <select id={id} className="bp-input" value={value} onChange={(e) => onChange(e.target.value)}>
            <option value="">(비워 둠)</option>
            <option value="none">none (무가중)</option>
            <option value="1/x">1/x</option>
            <option value="1/x2">1/x²</option>
          </select>
        ) : (
          <input
            id={id}
            className={`bp-input ${field.value_type === "number" ? "text-right font-mono tabular-nums" : ""}`}
            inputMode={field.value_type === "number" ? "decimal" : undefined}
            value={value}
            placeholder={field.status === "recognized" ? "" : "비워 두거나 직접 입력"}
            onChange={(e) => onChange(e.target.value)}
          />
        )}
        {field.source_text && (
          <p className="mt-1 break-words text-xs text-ink-muted">
            원문{field.line != null && ` ${field.line}행`}: <q className="text-ink">{field.source_text}</q>
          </p>
        )}
        {field.note && <p className="mt-0.5 text-xs text-warn">{field.note}</p>}
      </div>
    </li>
  );
}

function StepsEditor({
  steps,
  setSteps,
  labels,
}: {
  steps: ExtractedStep[];
  setSteps: (s: ExtractedStep[]) => void;
  labels: Map<string, string>;
}) {
  if (steps.length === 0) {
    return (
      <p className="bp-prose text-ink-muted">
        단계를 찾지 못했습니다. 번호를 매긴 줄(1. 2. …)이나 “절차:” 아래 줄이 단계가 됩니다. 단계 없이 저장하면 실행 화면은
        조건 확인 한 단계로 시작합니다.
      </p>
    );
  }
  return (
    <ol className="space-y-2">
      {steps.map((st, i) => (
        <li key={i} className="flex items-start gap-2">
          <span className="mt-2 w-6 shrink-0 text-right text-sm tabular-nums text-ink-muted">{i + 1}.</span>
          <div className="min-w-0 flex-1">
            <input
              aria-label={`${i + 1}단계 제목`}
              className="bp-input"
              value={st.title}
              onChange={(e) => setSteps(steps.map((x, j) => (j === i ? { ...x, title: e.target.value } : x)))}
            />
            {st.condition_keys.length > 0 && (
              <p className="mt-1 text-xs text-ink-muted">
                조건: {st.condition_keys.map((k) => labels.get(k) ?? k).join(", ")}
              </p>
            )}
          </div>
          <button
            type="button"
            className="bp-btn-ghost px-2 py-1"
            aria-label={`${i + 1}단계 삭제`}
            onClick={() => setSteps(steps.filter((_, j) => j !== i))}
          >
            삭제
          </button>
        </li>
      ))}
    </ol>
  );
}

/** First non-empty line of the paste, without list numbering — a starting protocol name. */
function suggestedName(text: string): string {
  const line = text.split("\n").find((l) => l.trim()) ?? "";
  return line.replace(/^\s*(\d+[.)]|[-*•])\s*/, "").trim().slice(0, 60);
}

/**
 * Paste → extracted candidates → confirm/edit → save. Extraction is stateless; the save
 * stores the confirmed block, the steps, the pasted original text and the reviewed
 * candidates (the backend records what was accepted, edited or added).
 */
export function PasteView({ projectId, go }: { projectId: number; go: ProtocolsNav }) {
  const extract = useExtractProtocol();
  const create = useCreateProtocolTemplate();
  const templates = useAllProtocolTemplates(projectId);
  const [text, setText] = useState("");
  const [result, setResult] = useState<{ text: string; extraction: ProtocolExtraction } | null>(null);
  const [values, setValues] = useState<Record<string, string>>({});
  const [steps, setSteps] = useState<ExtractedStep[]>([]);
  const [name, setName] = useState("");
  const [versionLabel, setVersionLabel] = useState("");
  const [author, setAuthor] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const [saved, setSaved] = useState<ProtocolTemplateOut | null>(null);

  const names = useMemo(() => [...new Set((templates.data?.items ?? []).map((t) => t.name))], [templates.data]);
  const fields = result?.extraction.fields ?? [];
  const labels = useMemo(() => new Map(fields.map((f) => [f.key, f.label])), [fields]);

  // Demo build: one example paste whose real extraction is part of the scenario snapshot.
  const [example, setExample] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    void demoProtocolExample().then((t) => alive && setExample(t));
    return () => {
      alive = false;
    };
  }, []);

  const runExtract = () =>
    extract.mutate(text, {
      onSuccess: (ex) => {
        setResult({ text, extraction: ex });
        setValues(Object.fromEntries(ex.fields.map((f) => [f.key, initialText(f)])));
        setSteps(ex.steps);
        setName((n) => n || suggestedName(text));
        setSaved(null);
        setFormError(null);
      },
    });

  const save = () => {
    if (!result) return;
    const block: Record<string, string | number> = {};
    for (const f of fields) {
      const raw = (values[f.key] ?? "").trim();
      if (!raw) continue;
      if (f.value_type === "number") {
        const n = Number(raw);
        if (!Number.isFinite(n) || !/^-?\d+(\.\d+)?$/.test(raw)) {
          setFormError(`${f.label}: 숫자 하나로 입력하세요 (단위 ${f.unit ?? "없음"}는 빼고)`);
          return;
        }
        block[f.key] = n;
      } else block[f.key] = raw;
    }
    if (Object.keys(block).length === 0) {
      setFormError("저장할 조건이 없습니다. 하나 이상 확인하거나 입력하세요.");
      return;
    }
    setFormError(null);
    create.mutate(
      {
        projectId,
        body: {
          name: name.trim(),
          version_label: versionLabel.trim(),
          author: author.trim(),
          description: "붙여넣은 원문에서 조건을 추출해 확인 후 저장",
          condition_block: block,
          steps: steps
            .filter((s) => s.title.trim())
            .map((s) => ({ title: s.title.trim(), detail: s.detail, condition_keys: s.condition_keys.filter((k) => k in block) })),
          source_text: result.text,
          extraction: {
            engine: result.extraction.engine,
            model: result.extraction.model,
            fallback_reason: result.extraction.fallback_reason,
            fields: result.extraction.fields,
          },
        },
      },
      { onSuccess: (t) => setSaved(t) },
    );
  };

  if (saved) {
    return (
      <Card title="저장되었습니다" subtitle={`${saved.name} ${saved.display_version} · 붙여넣은 원문도 함께 보존됨`}>
        {saved.extraction && (
          <p className="bp-prose mb-3 text-ink-muted">
            추출 후보 그대로 {saved.extraction.accepted_count}개 · 수정 {saved.extraction.edited_count}개 · 직접 입력{" "}
            {saved.extraction.added_count}개
          </p>
        )}
        <div className="space-y-3">
          <StartRun templateId={saved.id} label="이 프로토콜로 실험 시작" go={go} />
          <button type="button" className="bp-btn-ghost" onClick={() => go("lineage")}>
            프로토콜 목록으로
          </button>
        </div>
      </Card>
    );
  }

  const attention = fields.filter((f) => f.status === "ambiguous");
  const read = fields.filter((f) => f.status === "recognized");
  const missing = fields.filter((f) => f.status === "unrecognized");
  const row = (f: ExtractedField) => (
    <FieldRow key={f.key} field={f} value={values[f.key] ?? ""} onChange={(v) => setValues({ ...values, [f.key]: v })} />
  );

  return (
    <div className="space-y-4">
      <Card
        title={result ? "원문" : "프로토콜 붙여넣기"}
        subtitle="자유 텍스트, 엑셀에서 복사한 표, ‘항목: 값’ 줄 모두 됩니다. 원문은 그대로 함께 저장됩니다."
      >
        <label htmlFor="protocol-paste" className="sr-only">
          프로토콜 원문
        </label>
        <textarea
          id="protocol-paste"
          className="bp-input h-48 font-mono"
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="프로토콜 문서나 조건 표를 여기에 붙여넣으세요"
        />
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <button type="button" className="bp-btn-primary" disabled={!text.trim() || extract.isPending} onClick={runExtract}>
            {extract.isPending ? "읽는 중…" : result ? "다시 추출" : "조건 추출"}
          </button>
          {example && !text.trim() && (
            <button type="button" className="bp-btn-ghost" onClick={() => setText(example)}>
              예시 원문 넣기
            </button>
          )}
          {result && result.text !== text && <span className="text-sm text-warn">원문이 바뀌었습니다 — 다시 추출하세요</span>}
        </div>
        {extract.error && <div className="mt-2"><ErrorState error={extract.error} /></div>}
      </Card>

      {result && (
        <>
          <Card
            title={`조건 ${result.extraction.field_count}개 중 ${result.extraction.recognized_count}개를 읽었습니다`}
            subtitle="값과 원문 줄을 확인하세요. 읽지 못한 조건은 추측하지 않고 비워 두었습니다."
            actions={
              <span className="flex flex-wrap items-center gap-1">
                <EngineBadge engine={result.extraction.engine} model={result.extraction.model} />
                {result.extraction.fallback_reason && (
                  <span className="text-xs text-ink-muted" title={result.extraction.fallback_reason}>
                    Claude 결과를 쓰지 않음
                  </span>
                )}
              </span>
            }
          >
            {attention.length > 0 && (
              <section className="mb-2">
                <h3 className="text-sm font-semibold text-warn">! 확인이 필요한 조건</h3>
                <ul className="divide-y divide-border">{attention.map(row)}</ul>
              </section>
            )}
            <ul className="divide-y divide-border">{read.map(row)}</ul>
            {missing.length > 0 && (
              <Disclosure
                className="mt-2"
                title="인식하지 못한 조건 (비워 둠)"
                summary={missing.map((f) => f.label).join(", ")}
              >
                <ul className="divide-y divide-border">{missing.map(row)}</ul>
              </Disclosure>
            )}
          </Card>

          <Disclosure title="단계" summary={steps.length ? steps.map((s) => s.title).slice(0, 3).join(" → ") + (steps.length > 3 ? " …" : "") : "찾지 못함"}>
            <StepsEditor steps={steps} setSteps={setSteps} labels={labels} />
          </Disclosure>

          {result.extraction.unmatched_lines.length > 0 && (
            <Disclosure title="조건으로 읽지 못한 줄" summary="숫자가 있지만 알려진 조건이 아닌 줄 — 단계 설명으로만 남습니다">
              <ul className="space-y-1 text-sm">
                {result.extraction.unmatched_lines.map((l) => (
                  <li key={l.line} className="break-words">
                    <span className="mr-2 tabular-nums text-ink-muted">{l.line}행</span>
                    {l.text}
                  </li>
                ))}
              </ul>
            </Disclosure>
          )}

          <Card title="확인하고 저장">
            <div className="grid gap-3 sm:grid-cols-[1fr_8rem_10rem]">
              <label className="text-sm text-ink-muted">
                프로토콜 이름
                <input className="bp-input mt-0.5" list="protocol-names" value={name} onChange={(e) => setName(e.target.value)} />
                <datalist id="protocol-names">
                  {names.map((n) => (
                    <option key={n} value={n} />
                  ))}
                </datalist>
              </label>
              <label className="text-sm text-ink-muted">
                버전 이름
                <input className="bp-input mt-0.5" value={versionLabel} onChange={(e) => setVersionLabel(e.target.value)} placeholder="예: v2.1" />
              </label>
              <label className="text-sm text-ink-muted">
                작성자
                <input className="bp-input mt-0.5" value={author} onChange={(e) => setAuthor(e.target.value)} />
              </label>
            </div>
            {names.includes(name.trim()) && (
              <p className="mt-2 text-sm text-ink-muted">같은 이름의 프로토콜이 있어 그 다음 버전으로 저장됩니다.</p>
            )}
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <button
                type="button"
                className="bp-btn-primary"
                disabled={!name.trim() || create.isPending || result.text !== text}
                onClick={save}
              >
                확인하고 저장
              </button>
              <span className="text-sm text-ink-muted">저장 후에는 바꿀 수 없습니다 — 고치려면 새 버전으로 저장합니다.</span>
            </div>
            {formError && <p className="mt-2 text-sm text-crit">{formError}</p>}
            {create.error && <div className="mt-2"><ErrorState error={create.error} /></div>}
          </Card>
        </>
      )}
    </div>
  );
}
