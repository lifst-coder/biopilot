import clsx from "clsx";
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import type { Schemas } from "@/api/client";
import { Badge } from "@/components";
import {
  COLUMNS,
  DEFAULT_TYPES,
  TYPE_LABELS,
  experimentOf,
  filterGraph,
  layoutGraph,
  neighbours,
  truncate,
  type KGNode,
  type KGNodeType,
} from "./graphLayout";

type KnowledgeGraph = Schemas["KnowledgeGraph"];

/** Token-based fill/stroke per node type (CSS variables from tokens.css only). */
const TYPE_STYLE: Record<KGNodeType, { fill: string; stroke: string }> = {
  experiment: { fill: "rgb(var(--bp-brand-soft))", stroke: "rgb(var(--bp-brand))" },
  condition: { fill: "rgb(var(--bp-subtle))", stroke: "rgb(var(--bp-ink-faint))" },
  analyte: { fill: "rgb(var(--bp-ok-soft))", stroke: "rgb(var(--bp-ok))" },
  sample: { fill: "rgb(var(--bp-ok-soft))", stroke: "rgb(var(--bp-ok))" },
  strain: { fill: "rgb(var(--bp-ok-soft))", stroke: "rgb(var(--bp-ok))" },
  result: { fill: "rgb(var(--bp-warn-soft))", stroke: "rgb(var(--bp-warn))" },
  critique: { fill: "rgb(var(--bp-ai-soft))", stroke: "rgb(var(--bp-ai))" },
  hypothesis: { fill: "rgb(var(--bp-ai-soft))", stroke: "rgb(var(--bp-ai))" },
  proposal: { fill: "rgb(var(--bp-ai-soft))", stroke: "rgb(var(--bp-ai))" },
  decision: { fill: "rgb(var(--bp-crit-soft))", stroke: "rgb(var(--bp-crit))" },
  note: { fill: "rgb(var(--bp-surface))", stroke: "rgb(var(--bp-ink-muted))" },
};

const NODE_W = 170;
const NODE_H = 22;
const ALL_TYPES = COLUMNS.flat();

interface Props {
  graph: KnowledgeGraph;
}

/**
 * Knowledge graph from `/api/memory/projects/{id}/knowledge-graph`.
 * Type filter chips, hover/selection highlights neighbours, clicking an experiment
 * node opens it in the Notebook (`?exp=`); other nodes list their linked experiments.
 */
export function KnowledgeGraphView({ graph }: Props) {
  const navigate = useNavigate();
  const [types, setTypes] = useState<Set<KGNodeType>>(() => new Set(DEFAULT_TYPES));
  const [selected, setSelected] = useState<string | null>(null);
  const [hover, setHover] = useState<string | null>(null);

  const visible = useMemo(() => filterGraph(graph.nodes, graph.edges, types), [graph, types]);
  const layout = useMemo(() => layoutGraph(visible.nodes), [visible.nodes]);
  const byId = useMemo(() => new Map(graph.nodes.map((n) => [n.id, n])), [graph.nodes]);
  const active = hover ?? selected;
  const near = useMemo(() => (active ? neighbours(active, visible.edges) : null), [active, visible.edges]);
  const selectedNode = selected ? byId.get(selected) ?? null : null;
  const linkedExperiments = useMemo(() => {
    if (!selectedNode) return [];
    const ids = neighbours(selectedNode.id, graph.edges);
    return [...ids]
      .map((id) => byId.get(id))
      .filter((n): n is KGNode => !!n && n.type === "experiment" && n.id !== selectedNode.id);
  }, [selectedNode, graph.edges, byId]);

  const openExperiment = (id: number) => navigate({ pathname: "/notebook", search: `?exp=${id}` });
  const activate = (node: KGNode) => {
    if (node.type === "experiment") {
      const exp = experimentOf(node);
      if (exp != null) openExperiment(exp);
      return;
    }
    setSelected((cur) => (cur === node.id ? null : node.id));
  };
  const toggle = (t: KGNodeType) =>
    setTypes((cur) => {
      const next = new Set(cur);
      if (next.has(t)) next.delete(t);
      else next.add(t);
      return next;
    });

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label="노드 유형 필터">
        {ALL_TYPES.filter((t) => (graph.counts[t] ?? 0) > 0).map((t) => (
          <button
            key={t}
            type="button"
            aria-pressed={types.has(t)}
            onClick={() => toggle(t)}
            className={clsx(
              "rounded-full border px-2.5 py-0.5 text-[11px]",
              types.has(t) ? "border-brand bg-brand-soft text-brand-strong" : "border-border text-ink-faint",
            )}
          >
            {TYPE_LABELS[t]} {graph.counts[t]}
          </button>
        ))}
        <span className="ml-auto text-[11px] text-ink-faint">
          갱신: {graph.refresh.mode === "incremental" ? "증분" : graph.refresh.mode === "full" ? "전체" : "캐시"} · 이벤트 #
          {graph.refresh.last_event_id}
        </span>
      </div>

      {visible.nodes.length === 0 ? (
        <p className="py-6 text-center text-xs text-ink-faint">표시할 노드가 없습니다. 필터를 선택하세요.</p>
      ) : (
        <div className="overflow-x-auto rounded-md border border-border bg-canvas">
          <svg
            width={layout.width}
            height={layout.height}
            role="img"
            aria-label={`지식 그래프: 노드 ${visible.nodes.length}개, 엣지 ${visible.edges.length}개`}
          >
            <g>
              {visible.edges.map((e) => {
                const a = layout.positions.get(e.source);
                const b = layout.positions.get(e.target);
                if (!a || !b) return null;
                const lit = near ? near.has(e.source) && near.has(e.target) : false;
                const mid = (a.x + b.x) / 2;
                return (
                  <path
                    key={`${e.source}-${e.target}-${e.relation}`}
                    d={`M${a.x},${a.y} C${mid},${a.y} ${mid},${b.y} ${b.x},${b.y}`}
                    fill="none"
                    stroke={lit ? "rgb(var(--bp-brand))" : "rgb(var(--bp-border))"}
                    strokeWidth={lit ? 1.6 : 1}
                    strokeDasharray={e.relation === "shares_conditions" ? "3 3" : undefined}
                    opacity={near && !lit ? 0.35 : 1}
                    data-relation={e.relation}
                  >
                    <title>{e.relation}</title>
                  </path>
                );
              })}
            </g>
            <g>
              {visible.nodes.map((n) => {
                const p = layout.positions.get(n.id);
                if (!p) return null;
                const style = TYPE_STYLE[n.type];
                const dim = near ? !near.has(n.id) : false;
                return (
                  <g
                    key={n.id}
                    transform={`translate(${p.x - NODE_W / 2},${p.y - NODE_H / 2})`}
                    role="button"
                    tabIndex={0}
                    aria-label={`${TYPE_LABELS[n.type]}: ${n.label}`}
                    data-node-id={n.id}
                    className="cursor-pointer focus:outline-none"
                    opacity={dim ? 0.35 : 1}
                    onClick={() => activate(n)}
                    onKeyDown={(ev) => {
                      if (ev.key === "Enter" || ev.key === " ") {
                        ev.preventDefault();
                        activate(n);
                      }
                    }}
                    onMouseEnter={() => setHover(n.id)}
                    onMouseLeave={() => setHover(null)}
                    onFocus={() => setHover(n.id)}
                    onBlur={() => setHover(null)}
                  >
                    <title>{n.label}</title>
                    <rect
                      width={NODE_W}
                      height={NODE_H}
                      rx={NODE_H / 2}
                      fill={style.fill}
                      stroke={selected === n.id ? "rgb(var(--bp-ink))" : style.stroke}
                      strokeWidth={selected === n.id ? 2 : 1}
                    />
                    <text x={NODE_W / 2} y={NODE_H / 2 + 4} textAnchor="middle" fontSize={11} fill="rgb(var(--bp-ink))">
                      {truncate(n.label, 15)}
                    </text>
                  </g>
                );
              })}
            </g>
          </svg>
        </div>
      )}

      {selectedNode && (
        <div className="rounded-md border border-border p-3 text-xs" aria-live="polite">
          <div className="mb-1 flex items-center gap-2">
            <Badge tone="brand">{TYPE_LABELS[selectedNode.type]}</Badge>
            <span className="font-medium text-ink">{selectedNode.label}</span>
          </div>
          {selectedNode.ref_type && (
            <p className="text-ink-faint">
              출처: {selectedNode.ref_type} #{selectedNode.ref_id}
            </p>
          )}
          <div className="mt-2 flex flex-wrap gap-1.5">
            {linkedExperiments.length === 0 && selectedNode.experiment_id == null && (
              <span className="text-ink-faint">연결된 실험 없음</span>
            )}
            {linkedExperiments.map((n) => (
              <button
                key={n.id}
                type="button"
                className="rounded border border-brand px-2 py-0.5 text-brand hover:bg-brand-soft"
                onClick={() => n.ref_id != null && openExperiment(n.ref_id)}
              >
                {truncate(n.label, 30)} 열기
              </button>
            ))}
            {linkedExperiments.length === 0 && selectedNode.experiment_id != null && (
              <button
                type="button"
                className="rounded border border-brand px-2 py-0.5 text-brand hover:bg-brand-soft"
                onClick={() => openExperiment(selectedNode.experiment_id!)}
              >
                실험 열기
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
