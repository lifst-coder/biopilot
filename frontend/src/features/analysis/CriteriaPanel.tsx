import { useEffect, useState } from "react";
import { useCreateCriteria, useProjectCriteria, useRunAnalysis } from "@/api/queries";
import { Badge, Card, DataTable, QueryState } from "@/components";
import { formatDateTime } from "@/lib/format";
import type { AcceptanceCriteria, CriteriaVersionOut } from "./types";

type NumericKey = Exclude<keyof AcceptanceCriteria, "source">;

/** Editable thresholds/settings, grouped for display. Order = form order. */
export const CRITERIA_FIELDS: { key: NumericKey; label: string; unit?: string }[] = [
  { key: "recovery_min_pct", label: "회수율 하한", unit: "%" },
  { key: "recovery_max_pct", label: "회수율 상한", unit: "%" },
  { key: "rsd_max_pct", label: "RSD 상한", unit: "%" },
  { key: "r_squared_min", label: "R² 하한" },
  { key: "back_calc_tolerance_pct", label: "역산 허용 편차", unit: "%" },
  { key: "is_response_min_pct", label: "IS 응답 하한", unit: "%" },
  { key: "is_response_max_pct", label: "IS 응답 상한", unit: "%" },
  { key: "matrix_effect_abs_max_pct", label: "|ME| 상한", unit: "%" },
  { key: "expanded_uncertainty_max_pct", label: "확장 불확도 U 상한", unit: "%" },
  { key: "ion_ratio_tolerance_pct", label: "이온비 허용", unit: "±%" },
  { key: "lod_k", label: "LOD k" },
  { key: "loq_k", label: "LOQ k" },
  { key: "lod_range_factor", label: "LOD 회귀 구간 배수" },
  { key: "grubbs_alpha", label: "Grubbs α" },
  { key: "heteroscedasticity_alpha", label: "F-검정 α" },
  { key: "comparison_alpha", label: "비교 검정 α" },
  { key: "coverage_factor", label: "포함인자 k" },
  { key: "spike_uncertainty_pct", label: "u(C_ref)", unit: "%" },
];

interface Props {
  projectId: number | null;
  experimentId: number | null;
}

function CriteriaEditor({
  active,
  projectId,
  experimentId,
}: {
  active: CriteriaVersionOut;
  projectId: number;
  experimentId: number | null;
}) {
  const [draft, setDraft] = useState<Record<NumericKey, string>>(() => toDraft(active.criteria));
  const [note, setNote] = useState("");
  const create = useCreateCriteria();
  const run = useRunAnalysis();
  useEffect(() => setDraft(toDraft(active.criteria)), [active]);

  const changed = CRITERIA_FIELDS.filter((f) => Number(draft[f.key]) !== active.criteria[f.key]);

  function submit() {
    const criteria: AcceptanceCriteria = { ...active.criteria, source: `project ${projectId}` };
    for (const f of CRITERIA_FIELDS) criteria[f.key] = Number(draft[f.key]);
    create.mutate({ projectId, body: { criteria, note } }, { onSuccess: () => setNote("") });
  }

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-2 md:grid-cols-3 xl:grid-cols-6">
        {CRITERIA_FIELDS.map((f) => (
          <label key={f.key} className="text-[11px] text-ink-muted">
            {f.label}
            {f.unit && ` (${f.unit})`}
            <input
              className="bp-input mt-0.5 py-1 text-xs"
              inputMode="decimal"
              value={draft[f.key]}
              onChange={(e) => setDraft({ ...draft, [f.key]: e.target.value })}
            />
          </label>
        ))}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <input className="bp-input max-w-sm py-1 text-xs" placeholder="변경 사유 (감사 로그에 기록)" value={note} onChange={(e) => setNote(e.target.value)} />
        <button type="button" className="bp-btn-primary px-3 py-1 text-xs" disabled={changed.length === 0 || create.isPending} onClick={submit}>
          새 기준 버전 저장 ({changed.length}개 변경)
        </button>
        <button
          type="button"
          className="bp-btn-ghost px-3 py-1 text-xs"
          disabled={experimentId === null || run.isPending}
          onClick={() => experimentId !== null && run.mutate(experimentId)}
        >
          {run.isPending ? "재분석 중…" : "현재 기준으로 재분석"}
        </button>
        {run.data && (
          <span className="text-xs text-ink-muted">
            새 결과 {run.data.created} · 재사용 {run.data.reused}
            {run.data.skipped.length > 0 && ` · 건너뜀: ${run.data.skipped.join("; ")}`}
          </span>
        )}
        {(create.error || run.error) && (
          <span role="alert" className="text-xs text-crit">
            {String((create.error ?? run.error)?.message)}
          </span>
        )}
      </div>
    </div>
  );
}

function toDraft(c: AcceptanceCriteria): Record<NumericKey, string> {
  return Object.fromEntries(CRITERIA_FIELDS.map((f) => [f.key, String(c[f.key])])) as Record<NumericKey, string>;
}

/** Project acceptance criteria: active version, history and a form for a new version. */
export function CriteriaPanel({ projectId, experimentId }: Props) {
  const criteria = useProjectCriteria(projectId);
  return (
    <Card title="QC 허용 기준" subtitle="기준 변경은 새 불변 버전으로 저장되며, 기존 결과는 그대로 남고 재분석 시 새 결과가 생성됩니다.">
      <QueryState query={criteria}>
        {(pc) => (
          <div className="space-y-3">
            <p className="text-xs">
              활성 기준 <Badge tone="brand">{pc.active.label}</Badge>{" "}
              <span className="text-ink-muted">{pc.active.criteria.source}</span>
            </p>
            <details className="text-xs">
              <summary className="cursor-pointer text-ink-muted">기준 편집</summary>
              <div className="mt-2">
                <CriteriaEditor active={pc.active} projectId={pc.project_id} experimentId={experimentId} />
              </div>
            </details>
            <details className="text-xs">
              <summary className="cursor-pointer text-ink-muted">버전 이력 ({pc.history.length})</summary>
              <DataTable
                rows={[...pc.history].reverse()}
                rowKey={(h) => h.version}
                columns={[
                  { key: "v", header: "버전", render: (h) => h.label },
                  { key: "n", header: "메모", render: (h) => h.note || "—" },
                  { key: "t", header: "생성", render: (h) => (h.created_at ? formatDateTime(h.created_at) : "기본값") },
                  { key: "r", header: "회수율 범위", render: (h) => `${h.criteria.recovery_min_pct}–${h.criteria.recovery_max_pct}%` },
                ]}
              />
            </details>
          </div>
        )}
      </QueryState>
    </Card>
  );
}
