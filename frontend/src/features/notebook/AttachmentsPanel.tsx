import { useState } from "react";
import { useUploadAttachment } from "@/api/queries";
import { Card, EmptyState, ErrorState } from "@/components";
import { FileDropzone } from "./FileDropzone";
import { formatBytes, type ExperimentOut } from "./types";

/** Declared attachment metadata + stored binaries (content-addressed, download only). */
export function AttachmentsPanel({ exp }: { exp: ExperimentOut }) {
  const upload = useUploadAttachment();
  const [description, setDescription] = useState("");
  const files = exp.attachment_files ?? [];
  return (
    <Card title="첨부" subtitle="파일은 sha256 이름으로 저장 · 동일 파일 재업로드 시 중복 저장 없음 · 삭제 없음">
      {exp.attachments.length === 0 && files.length === 0 && <EmptyState>첨부 없음</EmptyState>}
      {exp.attachments.length > 0 && (
        <ul className="mb-2 space-y-0.5 text-xs">
          {exp.attachments.map((a) => (
            <li key={a.name}>
              <span className="font-mono">{a.name}</span> <span className="text-ink-faint">{a.description} (메타데이터만)</span>
            </li>
          ))}
        </ul>
      )}
      {files.length > 0 && (
        <ul className="mb-2 space-y-0.5 text-xs">
          {files.map((f) => (
            <li key={f.id} className="flex flex-wrap items-center gap-2">
              <a className="font-mono text-brand underline" href={`${import.meta.env.VITE_API_BASE_URL ?? ""}${f.download_url}`} download={f.name}>
                {f.name}
              </a>
              <span className="text-ink-faint">
                {formatBytes(f.size_bytes)} · sha256 {f.sha256.slice(0, 12)}… {f.description && `· ${f.description}`}
              </span>
            </li>
          ))}
        </ul>
      )}
      <div className="flex items-center gap-2">
        <input
          aria-label="첨부 설명"
          className="bp-input w-56 py-1 text-xs"
          placeholder="설명 (선택)"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
        <div className="flex-1">
          <FileDropzone
            label={upload.isPending ? "업로드 중…" : "첨부 파일을 끌어다 놓거나 클릭 (최대 20 MB)"}
            disabled={upload.isPending}
            onFile={(file) => {
              const form = new FormData();
              form.append("file", file, file.name);
              form.append("description", description);
              upload.mutate({ experimentId: exp.id, form }, { onSuccess: () => setDescription("") });
            }}
          />
        </div>
      </div>
      {upload.error && <ErrorState error={upload.error} />}
    </Card>
  );
}
