import { QueryClientContext } from "@tanstack/react-query";
import { useContext } from "react";
import { Link, useInRouterContext, useSearchParams } from "react-router-dom";
import { splitCodes, useExperimentIndex } from "@/lib/experimentIndex";
import { experimentSearch } from "@/lib/selection";

/** Tabs an experiment link can open (default: the Notebook record). */
export type ExperimentTab = "/notebook" | "/analysis" | "/research-ai";

/** Inline link to one experiment in its own project (`?project=&exp=`). */
export function ExperimentLink({
  id,
  projectId,
  children,
  tab = "/notebook",
  hash,
  title,
}: {
  id: number;
  projectId?: number | null;
  children: React.ReactNode;
  tab?: ExperimentTab;
  hash?: string;
  title?: string;
}) {
  // Outside a router (isolated component tests) the code is shown, not linked.
  if (!useInRouterContext()) return <span title={title}>{children}</span>;
  return (
    <Link
      to={{ pathname: tab, search: experimentSearch(id, projectId), hash }}
      title={title}
      // Dotted underline: a link not by color alone, but quiet inside sentences.
      className="font-medium text-brand underline decoration-brand/40 decoration-dotted underline-offset-2 hover:decoration-solid"
    >
      {children}
    </Link>
  );
}

/**
 * Text with every experiment code (`#024`, `#OA06`) turned into a link to that experiment —
 * in its own project, so a code from another project switches the project too. Codes that
 * match no stored experiment (e.g. result numbers) stay plain text. The text itself is
 * never changed: originals stay as recorded, only the codes become clickable.
 */
export function CodeText({ text, projectId }: { text: string | null | undefined; projectId?: number | null }) {
  const inRouter = useInRouterContext();
  const client = useContext(QueryClientContext);
  if (!text) return null;
  const parts = splitCodes(text);
  // No code, or rendered outside the app's router/query providers: the text as recorded.
  if (!inRouter || !client || parts.every((p) => typeof p === "string")) return <>{text}</>;
  return <LinkedCodes parts={parts} projectId={projectId} />;
}

function LinkedCodes({ parts, projectId }: { parts: Array<string | { code: string }>; projectId?: number | null }) {
  const index = useExperimentIndex();
  const [params] = useSearchParams();
  // Same-code experiments in two projects: the one in the given (else the active) project wins.
  const prefer = projectId ?? (Number(params.get("project")) || null);
  return (
    <>
      {parts.map((p, i) => {
        if (typeof p === "string") return p;
        const exp = index.byCode(p.code, prefer);
        if (!exp) return p.code;
        return (
          <ExperimentLink key={`${i}-${p.code}`} id={exp.id} projectId={exp.project_id} title={exp.title}>
            {p.code}
          </ExperimentLink>
        );
      })}
    </>
  );
}
