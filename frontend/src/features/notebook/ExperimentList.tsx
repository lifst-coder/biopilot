import clsx from "clsx";
import { useState } from "react";
import type { ExperimentSummary } from "@/api/types";
import { Badge, Card } from "@/components";
import { DATASET_KINDS, type DatasetKind } from "./types";

interface Props {
  experiments: ExperimentSummary[];
  selectedId: number | null;
  onSelect: (id: number) => void;
  onNew: () => void;
}

/** Experiment list with quick filters (text, dataset kind) and the "new experiment" entry. */
export function ExperimentList({ experiments, selectedId, onSelect, onNew }: Props) {
  const [query, setQuery] = useState("");
  const [kind, setKind] = useState<DatasetKind | "">("");
  const q = query.trim().toLowerCase();
  const rows = experiments.filter(
    (e) =>
      (!q || `${e.code} ${e.title} ${e.author}`.toLowerCase().includes(q)) &&
      (!kind || (e.dataset_kinds ?? []).includes(kind)),
  );
  return (
    <Card
      title="실험 목록"
      className="h-fit"
      actions={
        <button type="button" className="bp-btn-primary px-2 py-1 text-xs" onClick={onNew}>
          + 새 실험
        </button>
      }
    >
      <div className="mb-2 space-y-1">
        <input
          aria-label="실험 검색"
          className="bp-input py-1 text-xs"
          placeholder="코드·제목·작성자"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <select
          aria-label="데이터셋 종류 필터"
          className="bp-input py-1 text-xs"
          value={kind}
          onChange={(e) => setKind(e.target.value as DatasetKind | "")}
        >
          <option value="">모든 데이터셋 종류</option>
          {DATASET_KINDS.map((k) => (
            <option key={k.value} value={k.value}>
              {k.label}
            </option>
          ))}
        </select>
      </div>
      <ul className="max-h-72 space-y-1 overflow-y-auto lg:max-h-none lg:overflow-visible" aria-label="실험">
        {rows.map((e) => (
          <li key={e.id}>
            <button
              type="button"
              onClick={() => onSelect(e.id)}
              aria-current={e.id === selectedId}
              className={clsx(
                "w-full rounded-md px-2 py-1.5 text-left text-sm",
                e.id === selectedId ? "bg-brand-soft text-brand-strong" : "hover:bg-subtle",
              )}
            >
              <div className="flex items-center justify-between gap-1">
                <span className="font-medium">{e.code}</span>
                <span className="flex gap-0.5">
                  {(e.dataset_kinds ?? []).map((k) => (
                    <Badge key={k}>{k.slice(0, 3)}</Badge>
                  ))}
                </span>
              </div>
              <div className="truncate text-ink-muted">{e.title}</div>
            </button>
          </li>
        ))}
        {rows.length === 0 && <li className="py-2 text-center text-sm text-ink-faint">일치하는 실험 없음</li>}
      </ul>
      <p className="mt-2 text-xs text-ink-faint">
        {rows.length}/{experiments.length}개
      </p>
    </Card>
  );
}
