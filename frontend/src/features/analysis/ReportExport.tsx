import { useState } from "react";
import { fetchReport, saveText, type ReportFormat } from "./report";

/** Download buttons for the backend-rendered Markdown / CSV report. */
export function ReportExport({ experimentId }: { experimentId: number | null }) {
  const [busy, setBusy] = useState<ReportFormat | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function download(format: ReportFormat) {
    if (experimentId === null) return;
    setBusy(format);
    setError(null);
    try {
      const report = await fetchReport(experimentId, format);
      saveText(report.text, report.filename, report.mediaType);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="flex items-center gap-2 text-xs">
      <span className="text-ink-muted">리포트</span>
      <button type="button" className="bp-btn-ghost px-2 py-1 text-xs" disabled={experimentId === null || busy !== null} onClick={() => download("markdown")}>
        {busy === "markdown" ? "생성 중…" : "Markdown"}
      </button>
      <button type="button" className="bp-btn-ghost px-2 py-1 text-xs" disabled={experimentId === null || busy !== null} onClick={() => download("csv")}>
        {busy === "csv" ? "생성 중…" : "CSV"}
      </button>
      {error && <span role="alert" className="text-crit">{error}</span>}
    </div>
  );
}
