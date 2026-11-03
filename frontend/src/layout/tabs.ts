/** Tab registry. Each tab is owned by one feature folder (see CLAUDE.md 병렬 작업 규칙). */
export interface TabDef {
  path: string;
  label: string;
  description: string;
  /** The one question this screen answers — shown under the page title. */
  question: string;
}

export const TABS: TabDef[] = [
  { path: "/overview", label: "Overview", description: "프로젝트 현황", question: "이 프로젝트에서 지금 무엇을 봐야 하나?" },
  { path: "/notebook", label: "Notebook", description: "실험 원본 기록 · 비교", question: "무슨 실험이었고, 결과는 어땠나?" },
  { path: "/analysis", label: "Analysis", description: "결정론적 계산 결과", question: "이 실험의 결과를 신뢰할 수 있는가?" },
  { path: "/research-ai", label: "Research AI", description: "비판 · 가설 · 제안 · 결정", question: "왜 이런 결과가 나왔고, 다음에 무엇을 해야 하나?" },
];
