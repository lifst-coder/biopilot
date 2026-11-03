import { useState } from "react";
import { useUpdateMetadata } from "@/api/queries";
import { ErrorState } from "@/components";
import { Modal } from "./Modal";
import type { ExperimentOut } from "./types";

/** Correct title/author only (audited with before/after); originals stay immutable. */
export function MetadataDialog({ exp, onClose }: { exp: ExperimentOut; onClose: () => void }) {
  const update = useUpdateMetadata();
  const [title, setTitle] = useState(exp.title);
  const [author, setAuthor] = useState(exp.author);
  const [reason, setReason] = useState("");
  const unchanged = title === exp.title && author === exp.author;
  return (
    <Modal
      title="메타데이터 수정"
      onClose={onClose}
      footer={
        <>
          <button type="button" className="bp-btn-ghost" onClick={onClose}>
            취소
          </button>
          <button
            type="button"
            className="bp-btn-primary"
            disabled={unchanged || !title.trim() || update.isPending}
            onClick={() =>
              update.mutate(
                {
                  experimentId: exp.id,
                  body: {
                    title: title === exp.title ? null : title,
                    author: author === exp.author ? null : author,
                    reason,
                  },
                },
                { onSuccess: onClose },
              )
            }
          >
            저장 (v{(exp.revision ?? 1) + 1})
          </button>
        </>
      }
    >
      <div className="space-y-3 text-xs">
        <p className="text-ink-muted">
          제목·작성자만 고칠 수 있습니다. 메모·조건·수행일 등 원본은 바뀌지 않으며, 내용 보완은 “보충 기록”을 사용하세요.
        </p>
        <label className="block text-ink-muted">
          제목
          <input className="bp-input mt-0.5" value={title} onChange={(e) => setTitle(e.target.value)} />
        </label>
        <label className="block text-ink-muted">
          작성자
          <input className="bp-input mt-0.5" value={author} onChange={(e) => setAuthor(e.target.value)} />
        </label>
        <label className="block text-ink-muted">
          수정 사유 (감사 로그에 기록)
          <input className="bp-input mt-0.5" value={reason} onChange={(e) => setReason(e.target.value)} />
        </label>
        {update.error && <ErrorState error={update.error} />}
      </div>
    </Modal>
  );
}
