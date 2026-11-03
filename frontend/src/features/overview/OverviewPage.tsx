import { Link, useLocation } from "react-router-dom";
import { useAudit, useCompare, useCriteria, useProposals, useTimeline, useTrend } from "@/api/queries";
import { Badge, Card, DataTable, QueryState, StatTile } from "@/components";
import { formatDate, formatDateTime, formatPValue, formatWithUnit } from "@/lib/format";
import { useActiveProject } from "@/lib/selection";
import { RecoveryTrendChart } from "./RecoveryTrendChart";

/** Project status at a glance. Every number comes from an API response. */
export function OverviewPage() {
  const { project } = useActiveProject();
  const projectId = project?.id ?? null;
  const trend = useTrend(projectId);
  const timeline = useTimeline(projectId);
  const audit = useAudit(projectId, 12);
  const { data: criteria } = useCriteria();
  const { data: proposals = [] } = useProposals(projectId);
  const { search } = useLocation();

  const points = trend.data ?? [];
  const withRecovery = points.filter((p) => p.recovery_mean_pct !== null);
  const baseline = withRecovery[0] ?? null;
  const latest = withRecovery[withRecovery.length - 1] ?? null;
  const { data: cmp } = useCompare(baseline?.experiment_id ?? null, latest?.experiment_id ?? null);
  const pending = proposals.filter((p) => p.status === "pending").length;
  const inRange =
    latest?.recovery_mean_pct != null && criteria
      ? latest.recovery_mean_pct >= criteria.recovery_min_pct &&
        latest.recovery_mean_pct <= criteria.recovery_max_pct
      : null;

  if (!project) return <p className="text-xs text-ink-faint">프로젝트를 불러오는 중…</p>;
  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-lg font-semibold">{project.name}</h1>
        <p className="mt-1 max-w-3xl text-xs text-ink-muted">{project.objective}</p>
      </div>

      <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
        <StatTile label="기록된 실험" value={project.experiment_count} />
        <StatTile
          label={`최근 평균 회수율${latest ? ` (${latest.code})` : ""}`}
          value={formatWithUnit(latest?.recovery_mean_pct, "%")}
          tone={inRange === null ? "default" : inRange ? "ok" : "crit"}
          hint={criteria && `기준 ${criteria.recovery_min_pct}–${criteria.recovery_max_pct}% (${criteria.source})`}
        />
        <StatTile
          label={baseline && latest ? `${baseline.code} 대비 변화` : "기준 대비 변화"}
          value={formatWithUnit(cmp?.recovery_delta_pct_points, "%p")}
          hint={cmp?.recovery_t_test ? `Welch ${formatPValue(cmp.recovery_t_test.p_value)}` : undefined}
          tone={(cmp?.recovery_delta_pct_points ?? 0) < 0 ? "warn" : "default"}
        />
        <StatTile label="결정 대기 제안" value={pending} hint="Research AI 탭에서 결정" />
      </div>

      <Card title="회수율 추이" subtitle="실험별 평균 회수율 (저장된 분석 결과)">
        <QueryState query={trend}>
          {(data) => <RecoveryTrendChart points={data} criteria={criteria ?? null} />}
        </QueryState>
      </Card>

      <div className="grid gap-4 xl:grid-cols-2">
        <Card title="실험 타임라인" subtitle="부모 실험 대비 변경된 조건">
          <QueryState query={timeline}>
            {(rows) => (
              <DataTable
                rows={rows}
                rowKey={(r) => r.experiment_id}
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
                  { key: "title", header: "제목", render: (r) => r.title },
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
        <Card title="감사 로그" subtitle="모든 변경은 AuditEvent로 기록됩니다">
          <QueryState query={audit}>
            {(events) => (
              <DataTable
                rows={events}
                rowKey={(e) => e.id}
                columns={[
                  { key: "t", header: "시각", render: (e) => formatDateTime(e.occurred_at) },
                  { key: "actor", header: "주체", render: (e) => <Badge tone={e.actor.startsWith("ai") ? "ai" : "neutral"}>{e.actor}</Badge> },
                  { key: "action", header: "행위", render: (e) => e.action },
                  { key: "entity", header: "대상", render: (e) => `${e.entity_type} #${e.entity_id}` },
                ]}
              />
            )}
          </QueryState>
        </Card>
      </div>
      <p className="text-[11px] text-ink-faint">
        <Link to={{ pathname: "/analysis", search }} className="hover:underline">
          자세한 수치는 Analysis 탭 →
        </Link>
      </p>
    </div>
  );
}
