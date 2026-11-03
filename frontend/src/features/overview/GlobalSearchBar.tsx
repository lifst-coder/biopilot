import { useEffect, useId, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useMemorySearch, useRecall } from "@/api/queries";
import { Badge } from "@/components";
import { Highlighted } from "./highlight";

const FIELD_LABELS: Record<string, string> = {
  title: "제목",
  raw_note: "원본 메모",
  condition_block: "조건",
  digest: "정리본",
  critique: "비판",
  knowledge_note: "지식 노트",
  dataset: "데이터셋",
};

const FACET_LABELS: Record<string, string> = {
  strain: "균주",
  sample: "시료",
  condition: "조건",
  analyte: "분석물",
  keyword: "키워드",
};

/** Debounce a value (search-as-you-type without a request per keystroke). */
export function useDebounced<T>(value: T, ms = 250): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

/**
 * Project-wide search over research memory (`/api/memory/.../search` + `/recall`).
 * Shows matched facets (균주·시료·조건·분석물) and ranked hits; selecting a hit opens
 * the experiment in the Notebook.
 */
export function GlobalSearchBar({ projectId }: { projectId: number | null }) {
  const [text, setText] = useState("");
  const q = useDebounced(text);
  const search = useMemorySearch(projectId, q);
  const recall = useRecall(projectId, q);
  const navigate = useNavigate();
  const listId = useId();
  const hits = search.data ?? [];
  const open = q.trim().length > 0;

  return (
    <div className="relative">
      <label className="sr-only" htmlFor={`${listId}-input`}>
        연구 기억 검색
      </label>
      <input
        id={`${listId}-input`}
        type="search"
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Escape") setText("");
        }}
        placeholder="균주·시료·조건·분석물 검색 (예: GCB, carbendazim, 추출 시간)"
        className="w-full rounded-md border border-border bg-surface px-3 py-2 text-sm placeholder:text-ink-faint focus:border-brand focus:outline-none"
        aria-controls={open ? listId : undefined}
        aria-expanded={open}
        role="combobox"
        aria-autocomplete="list"
      />
      {open && (
        <div className="mt-2 rounded-md border border-border bg-surface p-3 text-sm shadow-sm">
          {recall.data && recall.data.terms.length > 0 && (
            <div className="mb-2 flex flex-wrap items-center gap-1" aria-label="해석된 검색어">
              {recall.data.terms.map((t) => (
                <Badge key={t.term} tone={t.facet === "keyword" ? "neutral" : "brand"}>
                  {FACET_LABELS[t.facet] ?? t.facet}: {t.term}
                </Badge>
              ))}
              {recall.data.protocols.length > 0 && (
                <span className="ml-1 text-ink-faint">프로토콜 변형 {recall.data.protocols.length}개</span>
              )}
            </div>
          )}
          {recall.data && recall.data.experiments.length > 0 && (
            <div className="mb-2">
              <p className="px-1 pb-1 font-medium text-ink-muted">관련 실험</p>
              <ul aria-label="관련 실험" className="space-y-0.5">
                {recall.data.experiments.slice(0, 5).map((x) => {
                  const top = x.reasons[0];
                  return (
                    <li key={x.experiment.id}>
                      <button
                        type="button"
                        className="flex w-full items-start gap-2 rounded px-1.5 py-1 text-left hover:bg-subtle focus:bg-subtle focus:outline-none"
                        onClick={() => navigate({ pathname: "/notebook", search: `?exp=${x.experiment.id}` })}
                      >
                        <span className="shrink-0 font-medium text-brand">{x.experiment.code}</span>
                        <span className="min-w-0 text-ink-muted">
                          {x.experiment.title}
                          {top && (
                            <span className="ml-2 text-ink-faint">
                              · <Highlighted text={top.snippet} spans={top.highlights} />
                            </span>
                          )}
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            </div>
          )}
          <p className="px-1 pb-1 font-medium text-ink-muted">본문 일치</p>
          {search.isLoading && <p className="px-1 py-2 text-ink-faint">검색 중…</p>}
          {search.isError && <p className="px-1 py-2 text-crit">검색 실패: {String(search.error)}</p>}
          {search.isSuccess && hits.length === 0 && (
            <p className="px-1 py-2 text-ink-faint">일치하는 기록이 없습니다.</p>
          )}
          <ul id={listId} role="listbox" aria-label="검색 결과" className="max-h-72 space-y-0.5 overflow-y-auto">
            {hits.map((h, i) => (
              <li key={`${h.experiment_id}-${h.field}-${h.source?.ref_type}-${h.source?.ref_id}-${i}`} role="option" aria-selected={false}>
                <button
                  type="button"
                  className="flex w-full items-start gap-2 rounded px-1.5 py-1 text-left hover:bg-subtle focus:bg-subtle focus:outline-none"
                  onClick={() => navigate({ pathname: "/notebook", search: `?exp=${h.experiment_id}` })}
                >
                  <span className="shrink-0 font-medium text-brand">{h.code}</span>
                  <span className="shrink-0 text-ink-faint">{FIELD_LABELS[h.field] ?? h.field}</span>
                  <span className="min-w-0 text-ink-muted">
                    <Highlighted text={h.snippet} spans={h.highlights} />
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
