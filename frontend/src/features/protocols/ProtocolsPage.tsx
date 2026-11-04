import { useSearchParams } from "react-router-dom";
import { PageHeader } from "@/components";
import { PASTE_QUESTION, RUN_QUESTION, TABS } from "@/layout/tabs";
import { useActiveProject } from "@/lib/selection";
import { LineageView } from "./LineageView";
import { PasteView } from "./PasteView";
import { RunView } from "./RunView";

const QUESTION = TABS.find((t) => t.path === "/protocols")?.question ?? "";

export type ProtocolsNav = (view: "lineage" | "new" | "run", runId?: number) => void;

/**
 * Protocols tab — the researcher's daily loop: write a protocol by pasting it, follow it at
 * the bench, and see which version works. Three views, one question each:
 * - `?view=` absent: lineage ("어느 버전이 QC를 잘 통과했나?")
 * - `?view=new`: paste → extracted condition candidates → confirm → save
 * - `?view=run&run=<id>`: step-by-step execution (phone width first)
 */
export function ProtocolsPage() {
  const [params, setParams] = useSearchParams();
  const { project } = useActiveProject();
  const view = params.get("view");
  const runId = Number(params.get("run")) || null;
  const go: ProtocolsNav = (next, id) =>
    setParams((prev) => {
      const p = new URLSearchParams(prev);
      p.delete("view");
      p.delete("run");
      if (next !== "lineage") p.set("view", next);
      if (next === "run" && id) p.set("run", String(id));
      return p;
    });

  const current = view === "new" ? "new" : view === "run" && runId ? "run" : "lineage";
  const question = current === "new" ? PASTE_QUESTION : current === "run" ? RUN_QUESTION : QUESTION;
  return (
    <div className="mx-auto max-w-5xl space-y-4">
      <PageHeader
        title="Protocols"
        question={question}
        actions={
          current === "lineage" ? (
            <button type="button" className="bp-btn-primary" onClick={() => go("new")}>
              + 붙여넣어 새 프로토콜
            </button>
          ) : (
            <button type="button" className="bp-btn-ghost" onClick={() => go("lineage")}>
              ← 프로토콜 목록
            </button>
          )
        }
      />
      {project &&
        (current === "new" ? (
          <PasteView projectId={project.id} go={go} />
        ) : current === "run" && runId ? (
          <RunView runId={runId} go={go} />
        ) : (
          <LineageView projectId={project.id} go={go} />
        ))}
    </div>
  );
}
