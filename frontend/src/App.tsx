import { NavLink, Route, Routes } from "react-router-dom";
import { DashboardPage } from "./pages/Dashboard/DashboardPage";
import { TestCasesPage } from "./pages/TestCases/TestCasesPage";
import { ExecutionPage } from "./pages/Execution/ExecutionPage";
import { CallFlowPage } from "./pages/CallFlow/CallFlowPage";
import { HistoryPage } from "./pages/History/HistoryPage";
import { ReportPage } from "./pages/Report/ReportPage";
import { SettingsPage } from "./pages/Settings/SettingsPage";
import "./App.css";

const NAV_ITEMS = [
  { to: "/", label: "대시보드", end: true },
  { to: "/test-cases", label: "시험 케이스 관리" },
  { to: "/execution", label: "시험 실행" },
  { to: "/history", label: "시험 이력" },
  { to: "/settings", label: "설정" },
];

export function App() {
  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="app-title">VCS 호처리 시험 자동화</div>
        <nav className="app-nav">
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) => (isActive ? "nav-link nav-link-active" : "nav-link")}
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
      </header>

      <main className="app-main">
        <Routes>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/test-cases" element={<TestCasesPage />} />
          <Route path="/execution" element={<ExecutionPage />} />
          <Route path="/execution/:runId" element={<ExecutionPage />} />
          <Route path="/call-flow/:runId" element={<CallFlowPage />} />
          <Route path="/report/:runId" element={<ReportPage />} />
          <Route path="/history" element={<HistoryPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="*" element={<div>페이지를 찾을 수 없습니다.</div>} />
        </Routes>
      </main>
    </div>
  );
}
