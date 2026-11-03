import { useState } from "react";
import { useAddAddendum } from "@/api/queries";
import { ErrorState } from "@/components";
import { formatDateTime } from "@/lib/format";
import type { ExperimentOut } from "./types";

/** Supplementary notes appended after the fact (the original note is never edited). */
export function AddendumSection({ exp }: { exp: ExperimentOut }) {
  const add = useAddAddendum();
  const [note, setNote] = useState("");
  const [author, setAuthor] = useState("");
  const [open, setOpen] = useState(false);
  return (
    <div className="mt-3">
      <div className="mb-1 flex items-center justify-between">
        <h3 className="text-xs font-semibold text-ink-muted">보충 기록 ({exp.addenda?.length ?? 0})</h3>
        <button type="button" className="bp-btn-ghost px-2 py-0.5 text-xs" onClick={() => setOpen(!open)}>
          {open ? "닫기" : "보충 기록 추가"}
        </button>
      </div>
      <ul className="space-y-1">
        {(exp.addenda ?? []).map((a) => (
          <li key={a.id} className="rounded-md border-l-2 border-warn bg-warn-soft/40 px-2 py-1 text-xs">
            <p className="whitespace-pre-wrap">{a.note}</p>
            <p className="text-[11px] text-ink-faint">
              {a.author || "작성자 미기재"} · {formatDateTime(a.created_at)}
            </p>
          </li>
        ))}
      </ul>
      {open && (
        <form
          className="mt-2 space-y-2"
          onSubmit={(e) => {
            e.preventDefault();
            add.mutate(
              { experimentId: exp.id, note, author },
              {
                onSuccess: () => {
                  setNote("");
                  setOpen(false);
                },
              },
            );
          }}
        >
          <textarea
            aria-label="보충 기록 내용"
            className="bp-input h-20 text-xs"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="예: 시료 S-03 크로마토그램 재확인 결과 …"
          />
          <div className="flex items-center gap-2">
            <input aria-label="보충 기록 작성자" className="bp-input py-1 text-xs" placeholder="작성자" value={author} onChange={(e) => setAuthor(e.target.value)} />
            <button type="submit" className="bp-btn-primary px-3 py-1 text-xs" disabled={!note.trim() || add.isPending}>
              추가
            </button>
          </div>
          {add.error && <ErrorState error={add.error} />}
        </form>
      )}
    </div>
  );
}
