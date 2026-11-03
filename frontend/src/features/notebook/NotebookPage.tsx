import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useDiff, useExperiment } from "@/api/queries";
import { Badge, Card, Disclosure, EmptyState, QueryState } from "@/components";
import { TABS } from "@/layout/tabs";
import { formatDate } from "@/lib/format";
import { useActiveProject, useSelectedExperiment } from "@/lib/selection";
import { AttachmentsPanel } from "./AttachmentsPanel";
import { CompareModal } from "./CompareModal";
import { DatasetsPanel } from "./DatasetsPanel";
import { ExperimentComposer, type ComposerResult, type ComposerSource } from "./ExperimentComposer";
import { ExperimentHeadline } from "./ExperimentHeadline";
import { ExperimentList } from "./ExperimentList";
import { HistoryPanel } from "./HistoryPanel";
import { IssueList } from "./IssueList";
import { MetadataDialog } from "./MetadataDialog";
import { OriginalVsDigest } from "./OriginalVsDigest";
import { ProtocolTemplateDialog } from "./ProtocolTemplateDialog";
import type { ExperimentOut } from "./types";

type Dialog = "metadata" | "compare" | "template" | null;

const QUESTION = TABS.find((t) => t.path === "/notebook")?.question ?? "";

/** Collapsed "원본 파일 · 이력" group: datasets, attachments, version history and audit log. */
function RecordDetails({ exp }: { exp: ExperimentOut }) {
  return (
    <div className="space-y-2">
      <h2 className="px-1 pt-2 text-xs font-semibold text-ink-muted">자세히</h2>
      <Disclosure title="데이터셋 (CSV)" summary={exp.dataset_kinds.length ? exp.dataset_kinds.join(" · ") : "없음"}>
        <DatasetsPanel experimentId={exp.id} />
      </Disclosure>
      <Disclosure title="첨부" summary={`${exp.attachment_files.length + exp.attachments.length}개`}>
        <AttachmentsPanel exp={exp} />
      </Disclosure>
      <Disclosure title="버전 이력 · 감사 로그" summary={`메타데이터 v${exp.revision ?? 1}`}>
        <HistoryPanel experimentId={exp.id} />
      </Disclosure>
    </div>
  );
}

/**
 * ELN view: authoring (new / clone / from template), immutable originals next to AI
 * digests, datasets with validation and re-upload, attachments, version history and
 * audit log, and comparison with past experiments.
 */
export function NotebookPage() {
  const { project } = useActiveProject();
  const { experiments, selectedId, select } = useSelectedExperiment();
  const experiment = useExperiment(selectedId);
  const [composer, setComposer] = useState<ComposerSource | null>(null);
  const [dialog, setDialogState] = useState<Dialog>(null);
  const [notice, setNotice] = useState<ComposerResult | null>(null);
  const [params, setParams] = useSearchParams();
  // `?compare=<id>` (guide bar "② 비교" step) opens the comparison with that baseline.
  const compareParam = Number(params.get("compare")) || null;
  const current = experiments.find((e) => e.id === selectedId) ?? null;
  const { data: diff } = useDiff(current?.parent_experiment_id ?? null, selectedId);
  const changedKeys = new Set((diff?.condition_changes ?? []).map((c) => c.key));
  const activeDialog: Dialog = compareParam !== null && compareParam !== selectedId ? "compare" : dialog;
  const setDialog = (next: Dialog) => {
    setDialogState(next);
    if (next === null && params.has("compare")) {
      setParams(
        (prev) => {
          const p = new URLSearchParams(prev);
          p.delete("compare");
          return p;
        },
        { replace: true },
      );
    }
  };

  const onCreated = (result: ComposerResult) => {
    setComposer(null);
    setNotice(result);
    select(result.experimentId);
  };

  return (
    <div className="grid gap-4 lg:grid-cols-[16rem_1fr]">
      <ExperimentList
        experiments={experiments}
        selectedId={composer ? null : selectedId}
        onSelect={(id) => {
          setComposer(null);
          setNotice(null);
          select(id);
        }}
        onNew={() => setComposer({ kind: "blank" })}
      />

      <div className="min-w-0 space-y-4">
        {composer && project ? (
          <ExperimentComposer
            key={JSON.stringify(composer)}
            projectId={project.id}
            experiments={experiments}
            source={composer}
            onCancel={() => setComposer(null)}
            onCreated={onCreated}
          />
        ) : selectedId === null ? (
          <Card>
            <EmptyState>실험이 없습니다. “+ 새 실험”으로 시작하세요.</EmptyState>
          </Card>
        ) : (
          <QueryState query={experiment}>
            {(exp) => (
              <>
                {notice && notice.experimentId === exp.id && (
                  <Card title="실험이 저장되었습니다" actions={<button type="button" className="bp-btn-ghost px-2 py-0.5 text-xs" onClick={() => setNotice(null)}>닫기</button>}>
                    {notice.warnings.length > 0 && (
                      <>
                        <p className="mb-1 text-xs text-ink-muted">조건 템플릿 경고 (저장은 완료):</p>
                        <IssueList issues={notice.warnings} />
                      </>
                    )}
                    {notice.failures.length > 0 ? (
                      <ul className="mt-2 space-y-0.5 text-xs text-crit">
                        {notice.failures.map((f) => (
                          <li key={f}>업로드 실패 — {f} (아래 데이터셋/첨부에서 다시 올리세요)</li>
                        ))}
                      </ul>
                    ) : (
                      <p className="text-xs text-ok">모든 파일이 업로드되었습니다.</p>
                    )}
                  </Card>
                )}
                <Card
                  title={
                    <span className="flex items-center gap-2">
                      {exp.code} · {exp.title}
                      {(exp.revision ?? 1) > 1 && <Badge tone="warn">메타데이터 v{exp.revision}</Badge>}
                    </span>
                  }
                  subtitle={[
                    formatDate(exp.performed_on),
                    exp.author || "작성자 미기재",
                    exp.parent_experiment_id
                      ? `부모 ${experiments.find((e) => e.id === exp.parent_experiment_id)?.code ?? ""}`
                      : "루트 실험",
                    exp.cloned_from_experiment_id
                      ? `복제 원본 ${experiments.find((e) => e.id === exp.cloned_from_experiment_id)?.code ?? ""}`
                      : null,
                    exp.protocol_template_id ? `템플릿 #${exp.protocol_template_id}` : null,
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                  actions={
                    <div className="flex flex-wrap gap-1">
                      <button type="button" className="bp-btn-ghost px-2 py-1 text-xs" onClick={() => setDialog("compare")}>
                        과거 실험과 비교
                      </button>
                      <button
                        type="button"
                        className="bp-btn-ghost px-2 py-1 text-xs"
                        onClick={() => setComposer({ kind: "clone", experimentId: exp.id })}
                      >
                        복제
                      </button>
                      <button type="button" className="bp-btn-ghost px-2 py-1 text-xs" onClick={() => setDialog("template")}>
                        프로토콜로 저장
                      </button>
                      <button type="button" className="bp-btn-ghost px-2 py-1 text-xs" onClick={() => setDialog("metadata")}>
                        메타데이터 수정
                      </button>
                    </div>
                  }
                >
                  <p className="-mt-1 mb-3 text-[11px] text-ink-faint">이 화면의 질문 · {QUESTION}</p>
                  <ExperimentHeadline exp={exp} experiments={experiments} onCompare={() => setDialog("compare")} />
                  <p className="mt-3 text-[11px] text-ink-faint">
                    원본 메모·조건 블록·CSV는 저장 후 변경되지 않습니다. 정정은 보충 기록·재업로드·메타데이터 수정(제목/작성자)으로
                    새 레코드를 남깁니다.
                  </p>
                </Card>

                <OriginalVsDigest exp={exp} changedKeys={changedKeys} />
                <RecordDetails exp={exp} />

                {activeDialog === "metadata" && <MetadataDialog exp={exp} onClose={() => setDialog(null)} />}
                {activeDialog === "template" && <ProtocolTemplateDialog exp={exp} onClose={() => setDialog(null)} />}
                {activeDialog === "compare" && (
                  <CompareModal
                    experiments={experiments}
                    current={exp.id}
                    defaultBaseline={compareParam ?? exp.parent_experiment_id ?? null}
                    onClose={() => setDialog(null)}
                  />
                )}
              </>
            )}
          </QueryState>
        )}
      </div>
    </div>
  );
}
