/** Tab registry. Each tab is owned by one feature folder (see CLAUDE.md 병렬 작업 규칙). */
export interface TabDef {
  path: string;
  label: string;
  description: string;
}

export const TABS: TabDef[] = [
  { path: "/overview", label: "Overview", description: "프로젝트 현황" },
  { path: "/notebook", label: "Notebook", description: "실험 원본 기록 · 비교" },
  { path: "/analysis", label: "Analysis", description: "결정론적 계산 결과" },
  { path: "/research-ai", label: "Research AI", description: "비판 · 가설 · 제안 · 결정" },
];
