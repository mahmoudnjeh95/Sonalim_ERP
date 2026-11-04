import { lazy, Suspense } from "react";
import { createBrowserRouter, Navigate, Outlet, type RouteObject } from "react-router-dom";
import { useAuth } from "../lib/auth";
import { AppLayout } from "./AppLayout";
import { LoginPage } from "./LoginPage";
import { RouteErrorBoundary } from "./RouteErrorBoundary";
import { BrandLoader } from "../components/patterns/BrandLoader";
import { LeadsPage } from "../features/crm/leads/LeadsPage";
import { PartnersPage } from "../features/partners/PartnersPage";
import { PartnerDetailsPage } from "../features/partners/PartnerDetailsPage";
import { OpportunitiesPage } from "../features/crm/opportunities/OpportunitiesPage";
import { PipelinePage } from "../features/crm/opportunities/PipelinePage";
import { ActivitiesPage } from "../features/crm/activities/ActivitiesPage";
import { UsersPage } from "../features/admin/users/UsersPage";
import { RolesPage } from "../features/admin/roles/RolesPage";
import { ActivityLogPage } from "../features/admin/activityLog/ActivityLogPage";
import { ProductionPage } from "../features/production/ProductionPage";
import { ProductionDashboardPage } from "../features/production/ProductionDashboardPage";
import { IaAssistantTab } from "../features/production/IaAssistantTab";
import { QualityPage } from "../features/qc/QualityPage";
import { AnalyticsPage } from "../features/analytics/AnalyticsPage";
import { MaintenancePage } from "../features/maintenance/MaintenancePage";
import { CheckpointMapEditor } from "../features/maintenance/map/CheckpointMapEditor";
import { JobPage } from "../features/maintenance/jobs/JobPage";
import { EquipmentHistoryPage } from "../features/maintenance/history/EquipmentHistoryPage";
import { EquipmentHistoryPrintPage } from "../features/maintenance/history/EquipmentHistoryPrintPage";
import { CheckWizard } from "../features/maintenance/wizard/CheckWizard";
import { WorkOrderDetailsPage } from "../features/production/WorkOrderDetailsPage";
import { WarehousePage } from "../features/warehouse/WarehousePage";
import { SalesOrdersPage } from "../features/sales/SalesOrdersPage";
import { FinanceInvoicesPage } from "../features/finance/FinanceInvoicesPage";
import { EntriesPage } from "../features/finance/EntriesPage";
import { AccountsPage } from "../features/finance/AccountsPage";
import { PostingRulesPage } from "../features/finance/PostingRulesPage";
import { TrialBalancePage } from "../features/finance/TrialBalancePage";
import { GeneralLedgerPage } from "../features/finance/GeneralLedgerPage";
import { PeriodsPage } from "../features/finance/PeriodsPage";
import { ProfilePage } from "../features/profile/ProfilePage";
import { SettingsPage } from "../features/settings/SettingsPage";
import { HrPage } from "../features/hr/HrPage";
import { EmployeesPage } from "../features/hr/EmployeesPage";
import { EmployeeFilePage } from "../features/hr/employee/EmployeeFilePage";
import { OrganisationPage } from "../features/hr/organisation/OrganisationPage";
import { SchedulesPage } from "../features/hr/schedules/SchedulesPage";
import { PresencePage } from "../features/hr/presence/PresencePage";
import { ClockImportsPage } from "../features/hr/presence/ClockImportsPage";
import { LeavePage } from "../features/hr/leave/LeavePage";
import { RunPage } from "../features/payroll/runs/RunPage";
import { RulesPage } from "../features/payroll/rules/RulesPage";
import { PurchaseOrdersPage } from "../features/procurement/PurchaseOrdersPage";
import { PurchaseInvoicesPage } from "../features/procurement/PurchaseInvoicesPage";
import { TreasuryPage } from "../features/treasury/TreasuryPage";
import { ProductsPage } from "../features/products/ProductsPage";
import { ShipmentsPage } from "../features/productsServices/ComingSoonPages";
import { RunsPage } from "../features/payroll/runs/RunsPage";
import { PayslipPage } from "../features/payroll/payslips/PayslipPage";
import { PayslipPrintPage } from "../features/payroll/print/PayslipPrintPage";
import { RunPrintPage } from "../features/payroll/print/RunPrintPage";
import { CashSheetPrintPage } from "../features/payroll/print/CashSheetPrintPage";
import { DeclarationPrintPage } from "../features/payroll/print/DeclarationPrintPage";
import { InputsPage } from "../features/payroll/inputs/InputsPage";

// Lazy-loaded: pulls in recharts, which is the single largest dependency in
// the bundle — keeping it out of the main chunk means pages that never touch
// a chart don't pay for it.
const CrmDashboardPage = lazy(() =>
  import("../features/crm/dashboard/CrmDashboardPage").then((m) => ({ default: m.CrmDashboardPage })),
);

function ProtectedRoute() {
  const { session } = useAuth();
  if (!session) {
    return <Navigate to="/login" replace />;
  }
  return (
    <AppLayout>
      <Outlet />
    </AppLayout>
  );
}

// Signed-in screens that take the whole screen, without the sidebar layout:
// the maintenance check wizard is run on a phone on the shop floor.
function ProtectedFullScreenRoute() {
  const { session } = useAuth();
  if (!session) {
    return <Navigate to="/login" replace />;
  }
  return <Outlet />;
}

// Every protected leaf route gets the same errorElement so a crash on one
// page unmounts inside AppLayout's <Outlet /> (sidebar/nav stay usable)
// instead of taking down the whole app with react-router's default screen.
const protectedChildren: RouteObject[] = [
  { path: "/", element: <Navigate to="/crm" replace /> },
  {
    path: "/crm",
    element: (
      <Suspense fallback={<BrandLoader tone="light" size={32} />}>
        <CrmDashboardPage />
      </Suspense>
    ),
  },
  { path: "/crm/leads", element: <LeadsPage /> },
  { path: "/crm/partners", element: <PartnersPage /> },
  { path: "/crm/partners/:partnerId", element: <PartnerDetailsPage /> },
  { path: "/crm/opportunities", element: <OpportunitiesPage /> },
  { path: "/crm/pipeline", element: <PipelinePage /> },
  { path: "/crm/activities", element: <ActivitiesPage /> },
  { path: "/production", element: <ProductionPage /> },
  { path: "/production/dashboard", element: <ProductionDashboardPage /> },
  { path: "/production/ia-assistant", element: <IaAssistantTab /> },
  { path: "/production/work-orders/:workOrderId", element: <WorkOrderDetailsPage /> },
  { path: "/quality", element: <QualityPage /> },
  { path: "/analytics", element: <AnalyticsPage /> },
  { path: "/maintenance", element: <MaintenancePage /> },
  { path: "/maintenance/equipment/:equipmentId", element: <EquipmentHistoryPage /> },
  { path: "/maintenance/equipment/:equipmentId/print", element: <EquipmentHistoryPrintPage /> },
  { path: "/maintenance/equipment/:equipmentId/map", element: <CheckpointMapEditor /> },
  { path: "/maintenance/jobs/:jobId", element: <JobPage /> },
  { path: "/warehouse", element: <WarehousePage /> },
  { path: "/products", element: <ProductsPage /> },
  { path: "/inventories", element: <Navigate to="/warehouse?tab=cycle-counts" replace /> },
  { path: "/shipments", element: <ShipmentsPage /> },
  { path: "/procurement", element: <PurchaseOrdersPage /> },
  { path: "/procurement/invoices", element: <PurchaseInvoicesPage /> },
  { path: "/treasury", element: <TreasuryPage /> },
  { path: "/sales", element: <SalesOrdersPage /> },
  { path: "/finance", element: <FinanceInvoicesPage /> },
  { path: "/finance/entries", element: <EntriesPage /> },
  { path: "/finance/accounts", element: <AccountsPage /> },
  { path: "/finance/posting-rules", element: <PostingRulesPage /> },
  { path: "/finance/trial-balance", element: <TrialBalancePage /> },
  { path: "/finance/ledger", element: <GeneralLedgerPage /> },
  { path: "/finance/periods", element: <PeriodsPage /> },
  { path: "/admin/users", element: <UsersPage /> },
  { path: "/admin/roles", element: <RolesPage /> },
  { path: "/admin/activity-log", element: <ActivityLogPage /> },
  { path: "/profile", element: <ProfilePage /> },
  { path: "/settings", element: <SettingsPage /> },
  { path: "/hr/employees", element: <EmployeesPage /> },
  { path: "/hr/employees/:employeeId", element: <EmployeeFilePage /> },
  { path: "/hr/organisation", element: <OrganisationPage /> },
  { path: "/hr", element: <HrPage /> },
  { path: "/hr/schedules", element: <SchedulesPage /> },
  { path: "/hr/presence", element: <PresencePage /> },
  { path: "/hr/presence/imports", element: <ClockImportsPage /> },
  { path: "/hr/leave", element: <LeavePage /> },
  { path: "/payroll/runs", element: <RunsPage /> },
  { path: "/payroll/runs/:runId", element: <RunPage /> },
  { path: "/payroll/rules", element: <RulesPage /> },
  { path: "/payroll/payslips/:payslipId", element: <PayslipPage /> },
  { path: "/payroll/payslips/:payslipId/print", element: <PayslipPrintPage /> },
  { path: "/payroll/runs/:runId/print", element: <RunPrintPage /> },
  { path: "/payroll/payout-batches/:batchId/cash-sheet/print", element: <CashSheetPrintPage /> },
  { path: "/payroll/declarations/print", element: <DeclarationPrintPage /> },
  { path: "/payroll/inputs", element: <InputsPage /> },
].map((route) => ({ ...route, errorElement: <RouteErrorBoundary /> }));

const fullScreenChildren: RouteObject[] = [
  { path: "/maintenance/jobs/:jobId/run", element: <CheckWizard /> },
].map((route) => ({ ...route, errorElement: <RouteErrorBoundary /> }));

export const router = createBrowserRouter([
  {
    // Catches errors thrown outside any leaf (e.g. in ProtectedRoute/AppLayout
    // itself) and unmatched paths (404s), as a last-resort fallback.
    errorElement: <RouteErrorBoundary />,
    children: [
      { path: "/login", element: <LoginPage /> },
      {
        element: <ProtectedRoute />,
        children: protectedChildren,
      },
      {
        element: <ProtectedFullScreenRoute />,
        children: fullScreenChildren,
      },
    ],
  },
]);
