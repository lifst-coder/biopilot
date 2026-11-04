import { useState } from "react";
import { useCreateProtocolTemplate } from "@/api/queries";
import { ErrorState } from "@/components";
import { Modal } from "./Modal";
import type { ExperimentOut } from "./types";

/** Save an experiment's note + conditions as a reusable (versioned) protocol template. */
export function ProtocolTemplateDialog({ exp, onClose }: { exp: ExperimentOut; onClose: () => void }) {
  const create = useCreateProtocolTemplate();
  const [name, setName] = useState(exp.title);
  const [description, setDescription] = useState(`${exp.code} 기반`);
  const [note, setNote] = useState(exp.raw_note);
  return (
    <Modal
      title="프로토콜 템플릿으로 저장"
      onClose={onClose}
      footer={
        <>
          <button type="button" className="bp-btn-ghost" onClick={onClose}>
            취소
          </button>
          <button
            type="button"
            className="bp-btn-primary"
            disabled={!name.trim() || create.isPending}
            onClick={() =>
              create.mutate(
                {
                  projectId: exp.project_id,
                  body: {
                    name,
                    description,
                    raw_note_template: note,
                    source_experiment_id: exp.id,
                    author: exp.author,
                    version_label: "",
                  },
                },
                { onSuccess: onClose },
              )
            }
          >
            저장
          </button>
        </>
      }
    >
      <div className="space-y-3 text-xs">
        <p className="text-ink-muted">조건 블록은 {exp.code}에서 그대로 복사됩니다. 같은 이름으로 다시 저장하면 새 버전이 됩니다.</p>
        <label className="block text-ink-muted">
          이름
          <input className="bp-input mt-0.5" value={name} onChange={(e) => setName(e.target.value)} />
        </label>
        <label className="block text-ink-muted">
          설명
          <input className="bp-input mt-0.5" value={description} onChange={(e) => setDescription(e.target.value)} />
        </label>
        <label className="block text-ink-muted">
          메모 틀 (관찰 내용은 지우고 절차만 남기는 것을 권장)
          <textarea className="bp-input mt-0.5 h-40 font-mono text-xs" value={note} onChange={(e) => setNote(e.target.value)} />
        </label>
        {create.error && <ErrorState error={create.error} />}
      </div>
    </Modal>
  );
}
