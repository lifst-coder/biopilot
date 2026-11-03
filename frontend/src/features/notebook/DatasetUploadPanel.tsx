import { useState } from "react";
import {
  useImportDataset,
  useImportFormats,
  usePreviewImport,
  useUploadDataset,
  useValidateDatasetUpload,
} from "@/api/queries";
import { ErrorState } from "@/components";
import { FileDropzone } from "./FileDropzone";
import { DATASET_KINDS, type DatasetKind, type DatasetOut } from "./types";
import { ValidationReport } from "./ValidationReport";

interface Props {
  experimentId: number;
  /** Re-upload: the new dataset supersedes this one (kind is fixed). */
  supersedes?: DatasetOut | null;
  onDone?: (dataset: DatasetOut) => void;
}

/**
 * CSV upload for an existing experiment: pick kind → choose/drop file → server dry-run
 * (encoding, columns, numbers, preview) → upload. Second mode converts instrument
 * (wide) exports; the original file is stored as an attachment by the server.
 */
export function DatasetUploadPanel({ experimentId, supersedes = null, onDone }: Props) {
  const [mode, setMode] = useState<"csv" | "import">("csv");
  const [kind, setKind] = useState<DatasetKind>((supersedes?.kind as DatasetKind | undefined) ?? "calibration");
  const [file, setFile] = useState<File | null>(null);
  const [format, setFormat] = useState("wide_analyte_columns");
  const validate = useValidateDatasetUpload();
  const upload = useUploadDataset();
  const formats = useImportFormats();
  const preview = usePreviewImport();
  const importDs = useImportDataset();

  const form = (f: File, extra: Record<string, string> = {}) => {
    const data = new FormData();
    data.append("file", f, f.name);
    data.append("kind", kind);
    if (supersedes) data.append("supersedes_dataset_id", String(supersedes.id));
    for (const [k, v] of Object.entries(extra)) data.append(k, v);
    return data;
  };

  const choose = (f: File) => {
    setFile(f);
    upload.reset();
    importDs.reset();
    if (mode === "csv") validate.mutate(form(f));
    else preview.mutate(form(f, { format }));
  };

  const report = mode === "csv" ? validate.data : preview.data?.validation;
  const submitting = upload.isPending || importDs.isPending;
  const submitError = upload.error ?? importDs.error;

  const submit = () => {
    if (!file) return;
    const done = (d: DatasetOut) => {
      setFile(null);
      validate.reset();
      preview.reset();
      onDone?.(d);
    };
    if (mode === "csv") upload.mutate({ experimentId, form: form(file) }, { onSuccess: done });
    else importDs.mutate({ experimentId, form: form(file, { format }) }, { onSuccess: done });
  };

  return (
    <div className="space-y-3">
      {supersedes && (
        <p className="rounded-md bg-warn-soft px-2 py-1 text-xs text-warn">
          재업로드: <span className="font-mono">{supersedes.filename}</span> (#{supersedes.id})을 대체하는 새 데이터셋을
          만듭니다. 기존 파일은 그대로 보관됩니다.
        </p>
      )}
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <div role="tablist" className="flex gap-1">
          {(["csv", "import"] as const).map((m) => (
            <button
              key={m}
              type="button"
              role="tab"
              aria-selected={mode === m}
              className={mode === m ? "bp-btn-primary px-2 py-1 text-xs" : "bp-btn-ghost px-2 py-1 text-xs"}
              onClick={() => {
                setMode(m);
                setFile(null);
                validate.reset();
                preview.reset();
              }}
            >
              {m === "csv" ? "계약 형식 CSV" : "장비 내보내기 변환"}
            </button>
          ))}
        </div>
        <label className="flex items-center gap-1">
          종류
          <select
            aria-label="데이터셋 종류"
            className="bp-input w-auto py-1 text-xs"
            value={kind}
            disabled={supersedes !== null}
            onChange={(e) => {
              setKind(e.target.value as DatasetKind);
              setFile(null);
              validate.reset();
              preview.reset();
            }}
          >
            {DATASET_KINDS.filter((k) => mode === "csv" || ["calibration", "recovery", "matrix_effect"].includes(k.value)).map(
              (k) => (
                <option key={k.value} value={k.value}>
                  {k.label}
                </option>
              ),
            )}
          </select>
        </label>
        {mode === "import" && (
          <label className="flex items-center gap-1">
            형식
            <select
              aria-label="장비 형식"
              className="bp-input w-auto py-1 text-xs"
              value={format}
              onChange={(e) => {
                setFormat(e.target.value);
                setFile(null);
                preview.reset();
              }}
            >
              {(formats.data ?? []).map((f) => (
                <option key={f.name} value={f.name}>
                  {f.label}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>
      {mode === "import" && formats.data && (
        <p className="text-[11px] text-ink-faint">
          예시 헤더: <span className="font-mono">{formats.data.find((f) => f.name === format)?.example_header.join(", ")}</span>
        </p>
      )}

      <FileDropzone
        label={file ? `${file.name} — 다른 파일을 놓거나 클릭해 교체` : "CSV 파일을 끌어다 놓거나 클릭해서 선택 (UTF-8 / CP949, 최대 5 MB)"}
        accept=".csv,text/csv,.txt"
        onFile={choose}
        disabled={submitting}
      />

      {(validate.isPending || preview.isPending) && <p className="text-xs text-ink-faint">서버에서 검증 중…</p>}
      {validate.error && <ErrorState error={validate.error} />}
      {preview.error && <ErrorState error={preview.error} />}
      {mode === "import" && preview.data && (
        <p className="text-xs text-ink-muted">
          원본 {preview.data.source_rows}행 → 분석물 {preview.data.analytes.length}종 ({preview.data.analytes.join(", ")})
        </p>
      )}
      {report && <ValidationReport report={report} />}
      {submitError && <ErrorState error={submitError} />}

      <div className="flex justify-end">
        <button type="button" className="bp-btn-primary text-xs" disabled={!file || !report?.ok || submitting} onClick={submit}>
          {submitting ? "업로드 중…" : supersedes ? "재업로드" : "업로드"}
        </button>
      </div>
    </div>
  );
}
