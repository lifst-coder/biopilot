import { useEffect, useRef, useState } from "react";
import {
  useCheckConditions,
  useConditionFields,
  useCreateExperiment,
  useExperimentDraft,
  useProtocolTemplates,
  useUploadAttachment,
  useUploadDataset,
  useValidateDatasetUpload,
} from "@/api/queries";
import type { ExperimentSummary } from "@/api/types";
import { Badge, Card, ErrorState, LoadingState } from "@/components";
import { ConditionBlockEditor, type ConditionValues } from "./ConditionBlockEditor";
import { FileDropzone } from "./FileDropzone";
import { IssueList } from "./IssueList";
import {
  DATASET_KINDS,
  errorMessage,
  formatBytes,
  type ConditionIssue,
  type DatasetKind,
  type DatasetValidation,
  type ExperimentCreate,
} from "./types";
import { ValidationReport } from "./ValidationReport";

export type ComposerSource =
  | { kind: "blank" }
  | { kind: "clone"; experimentId: number }
  | { kind: "template"; templateId: number };

export interface ComposerResult {
  experimentId: number;
  warnings: ConditionIssue[];
  failures: string[];
}

interface Props {
  projectId: number;
  experiments: ExperimentSummary[];
  source: ComposerSource;
  onCancel: () => void;
  onCreated: (result: ComposerResult) => void;
}

interface StagedCsv {
  key: number;
  file: File;
  kind: DatasetKind;
  report: DatasetValidation | null;
  error: string | null;
}

interface StagedFile {
  key: number;
  file: File;
  description: string;
}

type FormState = Omit<ExperimentCreate, "condition_block"> & { condition_block: ConditionValues };

const csvForm = (file: File, kind: DatasetKind) => {
  const data = new FormData();
  data.append("file", file, file.name);
  data.append("kind", kind);
  return data;
};

/**
 * New-experiment form: original note + condition block (validated live against the
 * project template, with units) + staged CSV files (server dry-run before saving) +
 * binary attachments. Prefilled from a blank draft, a clone or a protocol template.
 * On save: create experiment → upload staged datasets → upload attachments.
 */
export function ExperimentComposer({ projectId, experiments, source: initial, onCancel, onCreated }: Props) {
  const [source, setSource] = useState<ComposerSource>(initial);
  const draft = useExperimentDraft(projectId, {
    sourceExperimentId: source.kind === "clone" ? source.experimentId : null,
    protocolTemplateId: source.kind === "template" ? source.templateId : null,
  });
  const templates = useProtocolTemplates(projectId);
  const { data: fields = [] } = useConditionFields();
  const check = useCheckConditions();
  const create = useCreateExperiment();
  const validate = useValidateDatasetUpload();
  const upload = useUploadDataset();
  const attach = useUploadAttachment();

  const [form, setForm] = useState<FormState | null>(null);
  const [csvKind, setCsvKind] = useState<DatasetKind>("calibration");
  const [staged, setStaged] = useState<StagedCsv[]>([]);
  const [files, setFiles] = useState<StagedFile[]>([]);
  const [saving, setSaving] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const seq = useRef(0);

  useEffect(() => {
    if (draft.data) {
      const d = draft.data.draft;
      setForm({ ...d, condition_block: { ...(d.condition_block as ConditionValues) } });
    }
  }, [draft.data]);

  // Live template validation of the condition block (debounced, server-side rules).
  const conditionKey = JSON.stringify(form?.condition_block ?? null);
  useEffect(() => {
    if (!form) return;
    const t = setTimeout(() => check.mutate({ projectId, block: form.condition_block }), 300);
    return () => clearTimeout(t);
  }, [conditionKey, projectId]);

  if (draft.isError) return <ErrorState error={draft.error} />;
  if (!form) return <LoadingState label="초안 불러오는 중…" />;

  const issues = check.data?.issues ?? [];
  const hasConditionErrors = issues.some((i) => i.level === "error");
  const csvBlocking = staged.some((s) => !s.report?.ok);
  const update = (patch: Partial<FormState>) => setForm({ ...form, ...patch });

  const stageCsv = async (file: File) => {
    const key = ++seq.current;
    const kind = csvKind;
    setStaged((prev) => [...prev, { key, file, kind, report: null, error: null }]);
    try {
      const report = await validate.mutateAsync(csvForm(file, kind));
      setStaged((prev) => prev.map((s) => (s.key === key ? { ...s, report } : s)));
    } catch (e) {
      setStaged((prev) => prev.map((s) => (s.key === key ? { ...s, error: errorMessage(e) } : s)));
    }
  };

  const save = async () => {
    setSaveError(null);
    setSaving("실험 원본 저장 중…");
    let created;
    try {
      created = await create.mutateAsync({
        projectId,
        body: { ...form, condition_block: form.condition_block } as ExperimentCreate,
      });
    } catch (e) {
      setSaving(null);
      setSaveError(errorMessage(e));
      return;
    }
    const failures: string[] = [];
    for (const s of staged) {
      setSaving(`데이터셋 업로드: ${s.file.name}`);
      try {
        await upload.mutateAsync({ experimentId: created.id, form: csvForm(s.file, s.kind) });
      } catch (e) {
        failures.push(`${s.file.name}: ${errorMessage(e)}`);
      }
    }
    for (const f of files) {
      setSaving(`첨부 업로드: ${f.file.name}`);
      const data = new FormData();
      data.append("file", f.file, f.file.name);
      data.append("description", f.description);
      try {
        await attach.mutateAsync({ experimentId: created.id, form: data });
      } catch (e) {
        failures.push(`${f.file.name}: ${errorMessage(e)}`);
      }
    }
    setSaving(null);
    onCreated({ experimentId: created.id, warnings: created.warnings ?? [], failures });
  };

  const sourceLabel =
    source.kind === "clone"
      ? `복제: ${experiments.find((e) => e.id === source.experimentId)?.code ?? ""}`
      : source.kind === "template"
        ? "프로토콜 템플릿"
        : "빈 실험";

  return (
    <Card
      title="새 실험 작성"
      subtitle="저장하면 원본(메모·조건·CSV)은 불변이 됩니다 — 이후 수정은 보충 기록으로"
      actions={<Badge tone="brand">{sourceLabel}</Badge>}
    >
      <form
        className="space-y-5"
        onSubmit={(e) => {
          e.preventDefault();
          void save();
        }}
      >
        <section className="grid gap-3 md:grid-cols-3">
          <label className="text-xs text-ink-muted">
            실험 코드
            <input className="bp-input mt-0.5 font-mono" value={form.code} onChange={(e) => update({ code: e.target.value })} required />
          </label>
          <label className="text-xs text-ink-muted md:col-span-2">
            제목
            <input className="bp-input mt-0.5" value={form.title} onChange={(e) => update({ title: e.target.value })} required />
          </label>
          <label className="text-xs text-ink-muted">
            작성자
            <input className="bp-input mt-0.5" value={form.author ?? ""} onChange={(e) => update({ author: e.target.value })} />
          </label>
          <label className="text-xs text-ink-muted">
            수행일
            <input
              type="date"
              className="bp-input mt-0.5"
              value={form.performed_on}
              onChange={(e) => update({ performed_on: e.target.value })}
              required
            />
          </label>
          <label className="text-xs text-ink-muted">
            부모 실험
            <select
              className="bp-input mt-0.5"
              value={form.parent_experiment_id ?? ""}
              onChange={(e) => update({ parent_experiment_id: e.target.value ? Number(e.target.value) : null })}
            >
              <option value="">없음 (루트)</option>
              {experiments.map((e) => (
                <option key={e.id} value={e.id}>
                  {e.code} · {e.title}
                </option>
              ))}
            </select>
          </label>
          <label className="text-xs text-ink-muted md:col-span-3">
            프로토콜 템플릿으로 채우기
            <select
              aria-label="프로토콜 템플릿"
              className="bp-input mt-0.5"
              value={source.kind === "template" ? source.templateId : ""}
              onChange={(e) => {
                if (e.target.value) {
                  setForm(null);
                  setSource({ kind: "template", templateId: Number(e.target.value) });
                }
              }}
            >
              <option value="">{(templates.data?.total ?? 0) === 0 ? "저장된 템플릿 없음" : "선택…"}</option>
              {templates.data?.items.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name} v{t.version}
                  {t.description ? ` — ${t.description}` : ""}
                </option>
              ))}
            </select>
          </label>
        </section>

        <section>
          <h3 className="mb-1 text-xs font-semibold text-ink-muted">원본 메모</h3>
          <textarea
            aria-label="원본 메모"
            className="bp-input h-48 font-mono text-xs leading-relaxed"
            value={form.raw_note}
            onChange={(e) => update({ raw_note: e.target.value })}
            required
          />
        </section>

        <section>
          <div className="mb-1 flex items-center gap-2">
            <h3 className="text-xs font-semibold text-ink-muted">조건 블록</h3>
            {check.data && (
              <span className="text-xs text-ink-faint">
                템플릿 {check.data.template_source === "default" ? "기본" : `v${check.data.template_version}`} 기준 검증
              </span>
            )}
          </div>
          <ConditionBlockEditor
            fields={fields}
            value={form.condition_block}
            onChange={(condition_block) => update({ condition_block })}
            issues={issues}
          />
          {issues.length > 0 && (
            <div className="mt-2">
              <IssueList issues={issues} />
            </div>
          )}
        </section>

        <section className="space-y-2">
          <h3 className="text-xs font-semibold text-ink-muted">CSV 데이터셋</h3>
          <label className="flex items-center gap-2 text-xs text-ink-muted">
            추가할 파일 종류
            <select
              aria-label="스테이징 데이터셋 종류"
              className="bp-input w-auto py-1 text-xs"
              value={csvKind}
              onChange={(e) => setCsvKind(e.target.value as DatasetKind)}
            >
              {DATASET_KINDS.map((k) => (
                <option key={k.value} value={k.value}>
                  {k.label}
                </option>
              ))}
            </select>
          </label>
          <FileDropzone label="CSV를 끌어다 놓거나 클릭 — 저장 전에 서버에서 검증합니다" accept=".csv,text/csv,.txt" onFile={(f) => void stageCsv(f)} />
          {staged.map((s) => (
            <div key={s.key} className="space-y-1">
              <div className="flex items-center justify-between text-xs">
                <span>
                  <Badge tone="brand">{s.kind}</Badge> <span className="font-mono">{s.file.name}</span>
                </span>
                <button
                  type="button"
                  className="bp-btn-ghost px-2 py-0.5 text-xs"
                  onClick={() => setStaged((prev) => prev.filter((x) => x.key !== s.key))}
                >
                  제거
                </button>
              </div>
              {s.error && <ErrorState error={s.error} />}
              {!s.report && !s.error && <p className="text-xs text-ink-faint">검증 중…</p>}
              {s.report && <ValidationReport report={s.report} />}
            </div>
          ))}
        </section>

        <section className="space-y-2">
          <h3 className="text-xs font-semibold text-ink-muted">첨부 파일 (크로마토그램, PDF …)</h3>
          <FileDropzone
            label="첨부 파일을 끌어다 놓거나 클릭 (최대 20 MB)"
            onFile={(f) => setFiles((prev) => [...prev, { key: ++seq.current, file: f, description: "" }])}
          />
          {files.map((f) => (
            <div key={f.key} className="flex items-center gap-2 text-xs">
              <span className="w-48 truncate font-mono">{f.file.name}</span>
              <span className="text-ink-faint">{formatBytes(f.file.size)}</span>
              <input
                aria-label={`${f.file.name} 설명`}
                placeholder="설명"
                className="bp-input py-1 text-xs"
                value={f.description}
                onChange={(e) =>
                  setFiles((prev) => prev.map((x) => (x.key === f.key ? { ...x, description: e.target.value } : x)))
                }
              />
              <button
                type="button"
                className="bp-btn-ghost px-2 py-0.5 text-xs"
                onClick={() => setFiles((prev) => prev.filter((x) => x.key !== f.key))}
              >
                제거
              </button>
            </div>
          ))}
        </section>

        {saveError && <ErrorState error={saveError} />}
        <div className="flex items-center justify-end gap-2 border-t border-border pt-3">
          {saving && <span className="mr-auto text-xs text-ink-muted">{saving}</span>}
          {hasConditionErrors && <span className="mr-auto text-xs text-crit">조건 블록 오류를 고쳐야 저장할 수 있습니다</span>}
          {!hasConditionErrors && csvBlocking && (
            <span className="mr-auto text-xs text-crit">검증에 실패한 CSV를 제거하거나 교체하세요</span>
          )}
          <button type="button" className="bp-btn-ghost" onClick={onCancel} disabled={saving !== null}>
            취소
          </button>
          <button type="submit" className="bp-btn-primary" disabled={saving !== null || hasConditionErrors || csvBlocking}>
            실험 저장
          </button>
        </div>
      </form>
    </Card>
  );
}
