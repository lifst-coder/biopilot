import { Badge } from "@/components";

interface Issue {
  level: "error" | "warning";
  message: string;
  row?: number | null;
  column?: string | null;
  key?: string;
}

/** Server-side validation findings (CSV or condition template), errors first. */
export function IssueList({ issues, empty }: { issues: Issue[]; empty?: string }) {
  if (issues.length === 0) {
    return empty ? <p className="text-xs text-ok">{empty}</p> : null;
  }
  const sorted = [...issues].sort((a, b) => (a.level === b.level ? 0 : a.level === "error" ? -1 : 1));
  return (
    <ul className="space-y-1" aria-label="검증 결과">
      {sorted.map((i, idx) => (
        <li key={idx} className="flex items-start gap-2 text-xs">
          <Badge tone={i.level === "error" ? "crit" : "warn"}>{i.level === "error" ? "오류" : "경고"}</Badge>
          <span>
            {i.row ? <span className="font-mono text-ink-muted">{i.row}행 </span> : null}
            {i.message}
          </span>
        </li>
      ))}
    </ul>
  );
}
