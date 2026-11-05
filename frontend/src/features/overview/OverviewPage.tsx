import { useEffect } from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import {
  useAudit,
  useCriteria,
  useExperiments,
  useHypotheses,
  useKnowledgeGraph,
  useProposals,
  useTimeline,
  useTrend,
} from "@/api/queries";
import { Badge, Card, CodeText, DataTable, Disclosure, PageHeader, QueryState } from "@/components";
import { TABS } from "@/layout/tabs";
import { formatDate, formatDateTime } from "@/lib/format";
import { experimentSearch, useActiveProject } from "@/lib/selection";
import { FocusCard, pickFocus } from "./FocusCard";
import { GlobalSearchBar } from "./GlobalSearchBar";
import { KnowledgeGraphView } from "./KnowledgeGraphView";
import { RecoveryTrendChart } from "./RecoveryTrendChart";

const QUESTION = TABS.find((t) => t.path === "/overview")?.question ?? "";

/**
 * Project overview, ordered by "이 프로젝트에서 지금 무엇을 봐야 하나": one focus experiment
 * (what is wrong, the open question, where to go), search, the recovery trend and the
 * timeline; the knowledge graph and the audit log are collapsed below. Every number comes
 * from an API response.
 */
export function OverviewPage() {
  const { project } = useActiveProject();
  const projectId = project?.id ?? null;
  const trend = useTrend(projectId);
  const timeline = useTimeline(projectId);
  const audit = useAudit(projectId, 12);
  const { data: criteria } = useCriteria();
  const { data: proposals = [] } = useProposals(projectId);
  const { data: hypotheses = [] } = useHypotheses(projectId);
  const { data: experiments = [] } = useExperiments(projectId);
  const { search, hash } = useLocation();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  // `?exp=` came with the link (context line date → "#timeline"): mark that row.
  const marked = Number(params.get("exp")) || null;
  const timelineReady = timeline.isSuccess;
  useEffect(() => {
    if (hash === "#timeline" && timelineReady) document.getElementById("timeline")?.scrollIntoView({ block: "start" });
  }, [hash, timelineReady]);
  const knowledge = useKnowledgeGraph(projectId);

  const unresolved = new Set<number>([
    ...proposals.filter((p) => p.status === "pending").flatMap((p) => (p.experiment_id != null ? [p.experiment_id] : [])),
    ...hypotheses
      .filter((h) => h.status === "proposed" || h.status === "open")
      .flatMap((h) => (h.experiment_id != null ? [h.experiment_id] : [])),
  ]);
  const focus = pickFocus(trend.data ?? [], criteria ?? null, unresolved);
  const pending = proposals.filter((p) => p.status === "pending").length;
  const openHypotheses = hypotheses.filter((h) => h.status === "proposed" || h.status === "open").length;

  if (!project) return <p className="text-sm text-ink-faint">프로젝트를 불러오는 중…</p>;
  return (
    <div className="space-y-4">
      <PageHeader title={project.name} question={QUESTION} />

      {project.experiment_count === 0 && (
        <section className="rounded-card border border-border bg-surface px-5 py-4">
          <p className="bp-prose">
            이 프로젝트에는 아직 실험이 없습니다 — 첫 실험을 기록하면 여기에 지금 봐야 할 실험과 회수율 추이가 나옵니다.
          </p>
          <div className="mt-2 flex flex-wrap gap-2 text-sm">
            <Link to={{ pathname: "/notebook", search }} className="bp-btn-primary px-3 py-1.5">
              + 새 실험 기록 → Notebook
            </Link>
            <Link to={{ pathname: "/protocols", search }} className="bp-btn-ghost px-3 py-1.5">
              프로토콜 붙여넣어 시작 → Protocols
            </Link>
          </div>
        </section>
      )}

      {focus && (
        <FocusCard
          focus={focus}
          experiments={experiments}
          criteria={criteria ?? null}
          proposals={proposals}
          hypotheses={hypotheses}
        />
      )}

      <GlobalSearchBar projectId={projectId} />

      <p className="flex flex-wrap gap-x-5 gap-y-1.5 px-1 text-sm text-ink-muted">
        <span>
          기록된 실험 <b className="text-ink">{project.experiment_count}</b>
        </span>
        <span>
          결정 대기 제안 <b className={pending ? "text-warn" : "text-ink"}>{pending}</b>
        </span>
        <span>
          미해결 가설 <b className={openHypotheses ? "text-warn" : "text-ink"}>{openHypotheses}</b>
        </span>
        {project.objective && <span className="text-ink-faint">목표: {project.objective}</span>}
      </p>

      <Card title="회수율 추이" subtitle="실험별 평균 회수율 (저장된 분석 결과) · 초록 띠 = 허용 기준 · 점을 누르면 그 실험 기록">
        <QueryState query={trend}>
          {(data) => (
            <RecoveryTrendChart
              points={data}
              criteria={criteria ?? null}
              onSelect={(id) => navigate({ pathname: "/notebook", search: experimentSearch(id, projectId) })}
            />
          )}
        </QueryState>
      </Card>

      <div id="timeline" className="scroll-mt-4">
        <Card title="실험 타임라인" subtitle="부모 실험 대비 변경된 조건">
          <QueryState query={timeline}>
            {(rows) => (
              <DataTable
                rows={rows}
                rowKey={(r) => r.experiment_id}
                empty="아직 기록된 실험이 없습니다 — Notebook의 ‘+ 새 실험’으로 시작하세요."
                rowClassName={(r) =>
                  r.experiment_id === marked
                    ? "bg-brand-soft/70 font-medium"
                    : focus && r.experiment_id === focus.experiment_id
                      ? "bg-warn-soft/40"
                      : undefined
                }
                columns={[
                  {
                    key: "code",
                    header: "실험",
                    render: (r) => (
                      <Link
                        className="font-medium text-brand hover:underline"
                        to={{ pathname: "/notebook", search: `?exp=${r.experiment_id}` }}
                      >
                        {r.code}
                      </Link>
                    ),
                  },
                  { key: "title", header: "제목", render: (r) => <CodeText text={r.title} projectId={projectId} /> },
                  { key: "date", header: "일자", render: (r) => formatDate(r.performed_on) },
                  {
                    key: "changes",
                    header: "변경",
                    render: (r) =>
                      r.changed_keys_vs_parent.length ? (
                        <div className="flex flex-wrap gap-1">
                          {r.changed_keys_vs_parent.map((k) => (
                            <Badge key={k} tone="warn">
                              {k}
                            </Badge>
                          ))}
                        </div>
                      ) : (
                        <span className="text-ink-faint">기준</span>
                      ),
                  },
                ]}
              />
            )}
          </QueryState>
        </Card>
      </div>

      <div className="space-y-2">
        <h2 className="px-1 pt-4 text-sm font-semibold text-ink-muted">자세히</h2>
        <Disclosure
          lazy
          title="연구 지식 그래프"
          summary={knowledge.data ? `노드 ${knowledge.data.nodes.length} · 연결 ${knowledge.data.edges.length}` : undefined}
        >
          <p className="mb-2 text-sm text-ink-muted">
            실험 · 조건 · 분석물/시료 · 결과 · 가설 · 결정 (Memory, 감사 로그 기반 증분 갱신). 실험 노드를 누르면 열립니다.
          </p>
          <QueryState query={knowledge}>{(g) => <KnowledgeGraphView graph={g} />}</QueryState>
        </Disclosure>
        <Disclosure title="감사 로그" summary="모든 변경은 AuditEvent로 기록됩니다 · 최근 12건">
          <QueryState query={audit}>
            {(events) => (
              <DataTable
                rows={events}
                rowKey={(e) => e.id}
                columns={[
                  { key: "t", header: "시각", render: (e) => formatDateTime(e.occurred_at) },
                  {
                    key: "actor",
                    header: "주체",
                    render: (e) => <Badge tone={e.actor.startsWith("ai") ? "ai" : "neutral"}>{e.actor}</Badge>,
                  },
                  { key: "action", header: "행위", render: (e) => e.action },
                  { key: "entity", header: "대상", render: (e) => `${e.entity_type} #${e.entity_id}` },
                ]}
              />
            )}
          </QueryState>
        </Disclosure>
      </div>
      <p className="text-sm text-ink-muted">
        <Link to={{ pathname: "/analysis", search }} className="hover:underline">
          자세한 수치는 Analysis 탭 →
        </Link>
      </p>
    </div>
  );
}
