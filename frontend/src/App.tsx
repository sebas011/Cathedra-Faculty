import { lazy, useEffect, useState } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import WorkspaceSection from "./components/WorkspaceSection";
import AppShell from "./components/AppShell";
import AdminAccess from "./components/AdminAccess";
import LoginPage from "./pages/LoginPage";
import { getCurrentUser } from "./api";
import { sessionChangedEvent } from "./api/client";
const OfficeGuidePage = lazy(() => import("./pages/OfficeGuidePage"));

const SettingsPage = lazy(() => import("./pages/SettingsPage"));
const OfficePeriodPage = lazy(() => import("./pages/OfficePeriodPage"));
const ReportsPage = lazy(() => import("./pages/ReportsPage"));
const QualificationRatesPage = lazy(() => import("./pages/QualificationRatesPage"));
const DashboardPage = lazy(() => import("./pages/DashboardPage"));
const WorkloadFormPage = lazy(() => import("./pages/WorkloadFormPage"));
const WorkloadPage = lazy(() => import("./pages/WorkloadPage"));
const CompensationRulesPage = lazy(() => import("./pages/CompensationRulesPage"));
const FacultyProfilesPage = lazy(() => import("./pages/FacultyProfilesPage"));
const BackupExportPage = lazy(() => import("./pages/BackupExportPage"));
const ActivityPage = lazy(() => import("./pages/ActivityPage"));
const AccountSecurityPage = lazy(() => import("./pages/AccountSecurityPage"));
const ExpensesPage = lazy(() => import("./pages/ExpensesPage"));
const FacultyProfileDetailPage = lazy(() => import("./pages/FacultyProfileDetailPage"));
const WorkloadDetailPage = lazy(() => import("./pages/WorkloadDetailPage"));
const ApprovalRecordPage = lazy(() => import("./pages/ApprovalRecordPage"));
const ApprovedWorkloadSummaryPage = lazy(() => import("./pages/ApprovedWorkloadSummaryPage"));
const HistoricalAllocationReviewPage = lazy(() => import("./pages/HistoricalAllocationReviewPage"));
const SystemReadinessPage = lazy(() => import("./pages/SystemReadinessPage"));
const SemesterCloseoutPage = lazy(() => import("./pages/SemesterCloseoutPage"));
const VerificationPage = lazy(() => import("./pages/VerificationPage"));
const AcademicCalendarPage = lazy(() => import("./pages/AcademicCalendarPage"));
const SavedProjectionsPage = lazy(() => import("./pages/SavedProjectionsPage"));

function ProtectedShell() {
  const [user, setUser] = useState(getCurrentUser);
  const location = useLocation();
  useEffect(() => {
    const syncSession = () => setUser(getCurrentUser());
    window.addEventListener(sessionChangedEvent, syncSession);
    window.addEventListener("storage", syncSession);
    return () => {
      window.removeEventListener(sessionChangedEvent, syncSession);
      window.removeEventListener("storage", syncSession);
    };
  }, []);
  if (!user) return <Navigate to="/login" replace />;
  if (user.must_change_password && location.pathname !== "/settings/accounts") return <Navigate to="/settings/accounts" replace />;
  return <AppShell />;
}
function LegacyPage({ to }: { to: string }) { const { search, hash } = useLocation(); return <Navigate to={`${to}${search}${hash}`} replace />; }

export default function App() {
  return <Routes>
    <Route path="/login" element={<LoginPage />} />
    <Route element={<ProtectedShell />}>
      <Route path="/" element={<DashboardPage />} />
      <Route path="/settings" element={<WorkspaceSection section="settings" />}>
        <Route index element={<SettingsPage />} />
          <Route path="compensation" element={<CompensationRulesPage />} />
          <Route path="qualification-rates" element={<QualificationRatesPage />} />
          <Route path="office-period" element={<OfficePeriodPage />} />
        <Route path="accounts" element={<AccountSecurityPage />} />
      </Route>
      <Route path="/reports" element={<WorkspaceSection section="reports" />}>
        <Route index element={<ReportsPage />} />
        <Route path="workload" element={<ApprovedWorkloadSummaryPage />} />
        <Route path="historical-allocations" element={<HistoricalAllocationReviewPage />} />
        <Route path="projection" element={<AdminAccess><ExpensesPage key="projection-report" planning /></AdminAccess>} />
        <Route path="saved-estimates" element={<SavedProjectionsPage />} />
        <Route path="saved-estimates/:id" element={<SavedProjectionsPage />} />
      </Route>
      <Route path="/workload" element={<WorkloadPage />} />
      <Route path="/compensation-rules" element={<LegacyPage to="/settings/compensation" />} />
      <Route path="/workload/approved-summary" element={<LegacyPage to="/reports/workload" />} />
      <Route path="/faculty-profiles" element={<FacultyProfilesPage />} />
      <Route path="/faculty-profiles/:id" element={<FacultyProfileDetailPage />} />
      <Route path="/backup-export" element={<BackupExportPage />} />
      <Route path="/system-readiness" element={<SystemReadinessPage />} />
      <Route path="/verification" element={<VerificationPage />} />
      <Route path="/calendar" element={<AcademicCalendarPage />} />
      <Route path="/semester-closeout" element={<SemesterCloseoutPage />} />
      <Route path="/activity" element={<ActivityPage />} />
      <Route path="/account-security" element={<LegacyPage to="/settings/accounts" />} />
      <Route path="/office-guide" element={<OfficeGuidePage />} />
      <Route path="/workload/new" element={<WorkloadFormPage />} />
      <Route path="/workload/:id" element={<WorkloadDetailPage />} />
      <Route path="/workload/:id/details" element={<WorkloadDetailPage />} />
      <Route path="/workload/:id/approval-record" element={<ApprovalRecordPage />} />
      <Route path="/workload/:id/edit" element={<WorkloadFormPage />} />
      <Route path="/expenses" element={<AdminAccess><ExpensesPage key="faculty-expenses" /></AdminAccess>} />
      <Route path="/projection-planning" element={<LegacyPage to="/reports/projection" />} />
    </Route>
    <Route path="*" element={<Navigate to="/" replace />} />
  </Routes>;
}
