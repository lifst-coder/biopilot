/**
 * Deterministic column layout for the Memory knowledge graph.
 * Pure presentation geometry — no data values are computed here.
 */
import type { Schemas } from "@/api/client";

export type KGNode = Schemas["KGNode"];
export type KGEdge = Schemas["KGEdge"];
export type KGNodeType = KGNode["type"];

/** Left → right reading order: conditions → experiments → entities → results → reasoning. */
export const COLUMNS: KGNodeType[][] = [
  ["condition"],
  ["experiment"],
  ["analyte", "sample", "strain"],
  ["result", "critique", "note"],
  ["hypothesis", "proposal", "decision"],
];

export const TYPE_LABELS: Record<KGNodeType, string> = {
  experiment: "실험",
  condition: "조건",
  analyte: "분석물",
  sample: "시료",
  strain: "균주",
  result: "결과",
  critique: "비판",
  hypothesis: "가설",
  proposal: "제안",
  decision: "결정",
  note: "지식 노트",
};

/** Node types shown by default (conditions are numerous, so they start hidden). */
export const DEFAULT_TYPES: KGNodeType[] = [
  "experiment",
  "analyte",
  "sample",
  "strain",
  "result",
  "critique",
  "hypothesis",
  "proposal",
  "decision",
  "note",
];

export interface Point {
  x: number;
  y: number;
}

export interface Layout {
  positions: Map<string, Point>;
  width: number;
  height: number;
}

const sortKey = (n: KGNode) =>
  `${COLUMNS.findIndex((c) => c.includes(n.type))}|${n.type}|${n.label}|${n.id}`;

/** Place visible nodes in type columns, sorted by label, evenly spaced. */
export function layoutGraph(
  nodes: KGNode[],
  { columnWidth = 190, rowHeight = 30, padding = 24 } = {},
): Layout {
  const used = COLUMNS.filter((col) => nodes.some((n) => col.includes(n.type)));
  const positions = new Map<string, Point>();
  let maxRows = 0;
  used.forEach((col, ci) => {
    const members = nodes.filter((n) => col.includes(n.type)).sort((a, b) => sortKey(a).localeCompare(sortKey(b)));
    maxRows = Math.max(maxRows, members.length);
    members.forEach((n, ri) => {
      positions.set(n.id, { x: padding + ci * columnWidth + columnWidth / 2, y: padding + ri * rowHeight + rowHeight / 2 });
    });
  });
  // vertically centre short columns
  const height = padding * 2 + Math.max(1, maxRows) * rowHeight;
  used.forEach((col) => {
    const members = nodes.filter((n) => col.includes(n.type));
    const offset = ((maxRows - members.length) * rowHeight) / 2;
    members.forEach((n) => {
      const p = positions.get(n.id);
      if (p) positions.set(n.id, { x: p.x, y: p.y + offset });
    });
  });
  return { positions, width: padding * 2 + Math.max(1, used.length) * columnWidth, height };
}

/** Nodes of the given types and the edges whose both ends are visible. */
export function filterGraph(nodes: KGNode[], edges: KGEdge[], types: Set<KGNodeType>) {
  const visible = nodes.filter((n) => types.has(n.type));
  const ids = new Set(visible.map((n) => n.id));
  return { nodes: visible, edges: edges.filter((e) => ids.has(e.source) && ids.has(e.target)) };
}

/** Ids adjacent to `id` (either direction), including itself. */
export function neighbours(id: string, edges: KGEdge[]): Set<string> {
  const out = new Set([id]);
  for (const e of edges) {
    if (e.source === id) out.add(e.target);
    if (e.target === id) out.add(e.source);
  }
  return out;
}

/** Experiment id a node opens: its own ref for experiment nodes, else its experiment link. */
export function experimentOf(node: KGNode): number | null {
  if (node.type === "experiment") return node.ref_id ?? null;
  return node.experiment_id ?? null;
}

export function truncate(text: string, max = 22): string {
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}
