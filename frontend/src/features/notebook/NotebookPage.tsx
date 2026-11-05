import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useAllProtocolTemplates, useDiff, useExperiment } from "@/api/queries";
import { Badge, Card, Disclosure, EmptyState, ExperimentLink, QueryState } from "@/components";
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
      <h2 className="px-1 pt-4 text-sm font-semibold text-ink-muted">자세히</h2>
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
 * "날짜 · 작성자 · 부모 #018 · 복제 원본 #… · 프로토콜 …" — the parent, the clone source and the
 * protocol version are links (to that experiment, and to the version in Protocols).
 */
function RecordLine({
  exp,
  codeOf,
  protocol,
}: {
  exp: ExperimentOut;
  codeOf: (id: number) => string | null;
  protocol: string | null;
}) {
  const parts: React.ReactNode[] = [formatDate(exp.performed_on), exp.author || "작성자 미기재"];
  const link = (label: string, id: number) => (
    <>
      {label}{" "}
      <ExperimentLink id={id} projectId={exp.project_id}>
        {codeOf(id) ?? `#${id}`}
      </ExperimentLink>
    </>
  );
  parts.push(exp.parent_experiment_id ? link("부모", exp.parent_experiment_id) : "루트 실험");
  if (exp.cloned_from_experiment_id) parts.push(link("복제 원본", exp.cloned_from_experiment_id));
  if (protocol && exp.protocol_template_id) {
    parts.push(
      <Link
        to={{ pathname: "/protocols", search: `?project=${exp.project_id}`, hash: `#protocol-${exp.protocol_template_id}` }}
        className="text-brand underline decoration-brand/30 underline-offset-2 hover:decoration-brand"
        title="이 버전의 계보 · 버전별 QC 통과"
      >
        {protocol}
      </Link>,
    );
  }
  return (
    <>
      {parts.map((p, i) => (
        <span key={i}>
          {i > 0 && " · "}
          {p}
        </span>
      ))}
    </>
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
  const { data: templates } = useAllProtocolTemplates(project?.id ?? null);
  const protocolLabel = (id: number) => {
    const t = templates?.items.find((x) => x.id === id);
    return t ? `프로토콜 ${t.name} ${t.display_version}` : `프로토콜 #${id}`;
  };
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
                        <p className="mb-1 text-sm text-ink-muted">조건 템플릿 경고 (저장은 완료):</p>
                        <IssueList issues={notice.warnings} />
                      </>
                    )}
                    {notice.failures.length > 0 ? (
                      <ul className="mt-2 space-y-0.5 text-sm text-crit">
                        {notice.failures.map((f) => (
                          <li key={f}>업로드 실패 — {f} (아래 데이터셋/첨부에서 다시 올리세요)</li>
                        ))}
                      </ul>
                    ) : (
                      <p className="text-sm text-ok">모든 파일이 업로드되었습니다.</p>
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
                  subtitle={
                    <RecordLine
                      exp={exp}
                      codeOf={(id) => experiments.find((e) => e.id === id)?.code ?? null}
                      protocol={exp.protocol_template_id ? protocolLabel(exp.protocol_template_id) : null}
                    />
                  }
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
                  <p className="-mt-1 mb-4 text-sm text-ink-muted">이 화면의 질문 · {QUESTION}</p>
                  <ExperimentHeadline exp={exp} experiments={experiments} onCompare={() => setDialog("compare")} />
                  <p className="mt-4 text-sm text-ink-faint">
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
