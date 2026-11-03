/** Report export: the backend renders stored results; the browser only saves the file. */
import { api } from "@/api/client";

export type ReportFormat = "markdown" | "csv";

/** Filename from `Content-Disposition`, falling back to a generic name. */
export function filenameFrom(disposition: string | null, format: ReportFormat): string {
  const match = disposition?.match(/filename="?([^";]+)"?/);
  return match?.[1] ?? `analysis-report.${format === "csv" ? "csv" : "md"}`;
}

/** Fetch the report text for an experiment (throws on non-2xx). */
export async function fetchReport(
  experimentId: number,
  format: ReportFormat,
): Promise<{ text: string; filename: string; mediaType: string }> {
  const { data, error, response } = await api.GET("/api/analysis/experiments/{experiment_id}/report", {
    params: { path: { experiment_id: experimentId }, query: { format } },
    parseAs: "text",
  });
  if (error !== undefined || data === undefined) {
    throw new Error(`리포트를 받지 못했습니다 (HTTP ${response.status})`);
  }
  return {
    text: data,
    filename: filenameFrom(response.headers.get("content-disposition"), format),
    mediaType: response.headers.get("content-type") ?? "text/plain",
  };
}

/** Offer `text` as a file download. */
export function saveText(text: string, filename: string, mediaType: string): void {
  const url = URL.createObjectURL(new Blob([text], { type: mediaType }));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}
