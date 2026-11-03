import type { AnalysisResultOut } from "@/api/types";
import { formatDateTime } from "@/lib/format";

/** Provenance line shown under every analysis panel title. */
export function resultSubtitle(result: AnalysisResultOut): string {
  return `결과 #${result.id} · ${result.method_version} · 입력 데이터셋 #${result.input_dataset_ids.join(", #")} · ${formatDateTime(result.created_at)}`;
}
