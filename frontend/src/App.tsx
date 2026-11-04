import { lazy, Suspense } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { LoadingState } from "@/components";
import { AppShell } from "@/layout/AppShell";

// One lazy chunk per tab: tabs are owned by different sessions and load independently.
const OverviewPage = lazy(() =>
  import("@/features/overview/OverviewPage").then((m) => ({ default: m.OverviewPage })),
);
const NotebookPage = lazy(() =>
  import("@/features/notebook/NotebookPage").then((m) => ({ default: m.NotebookPage })),
);
const ProtocolsPage = lazy(() =>
  import("@/features/protocols/ProtocolsPage").then((m) => ({ default: m.ProtocolsPage })),
);
const AnalysisPage = lazy(() =>
  import("@/features/analysis/AnalysisPage").then((m) => ({ default: m.AnalysisPage })),
);
const ResearchAIPage = lazy(() =>
  import("@/features/research-ai/ResearchAIPage").then((m) => ({ default: m.ResearchAIPage })),
);

const RecordsPage = lazy(() =>
  import("@/features/records/RecordsPage").then((m) => ({ default: m.RecordsPage })),
);

export function App() {
  return (
    <Suspense fallback={<LoadingState />}>
      <Routes>
        <Route element={<AppShell />}>
          <Route index element={<Navigate to="/overview" replace />} />
          <Route path="/overview" element={<OverviewPage />} />
          <Route path="/notebook" element={<NotebookPage />} />
          <Route path="/protocols" element={<ProtocolsPage />} />
          <Route path="/analysis" element={<AnalysisPage />} />
          <Route path="/research-ai" element={<ResearchAIPage />} />
          <Route path="/records" element={<RecordsPage />} />
          <Route path="*" element={<Navigate to="/overview" replace />} />
        </Route>
      </Routes>
    </Suspense>
  );
}
