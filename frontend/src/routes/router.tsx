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
import { WorkOrderDetailsPage } from "../features/production/WorkOrderDetailsPage";
import { WarehousePage } from "../features/warehouse/WarehousePage";
import { SalesOrdersPage } from "../features/sales/SalesOrdersPage";
import { FinanceInvoicesPage } from "../features/finance/FinanceInvoicesPage";
import { SettingsPage } from "../features/settings/SettingsPage";
import { HrPage } from "../features/hr/HrPage";
import { PurchaseOrdersPage } from "../features/procurement/PurchaseOrdersPage";
import { PurchaseInvoicesPage } from "../features/procurement/PurchaseInvoicesPage";
import { TreasuryPage } from "../features/treasury/TreasuryPage";
import { ProductsPage } from "../features/products/ProductsPage";
import { InventoriesPage, ShipmentsPage } from "../features/productsServices/ComingSoonPages";

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
  { path: "/warehouse", element: <WarehousePage /> },
  { path: "/products", element: <ProductsPage /> },
  { path: "/inventories", element: <InventoriesPage /> },
  { path: "/shipments", element: <ShipmentsPage /> },
  { path: "/procurement", element: <PurchaseOrdersPage /> },
  { path: "/procurement/invoices", element: <PurchaseInvoicesPage /> },
  { path: "/treasury", element: <TreasuryPage /> },
  { path: "/sales", element: <SalesOrdersPage /> },
  { path: "/finance", element: <FinanceInvoicesPage /> },
  { path: "/admin/users", element: <UsersPage /> },
  { path: "/admin/roles", element: <RolesPage /> },
  { path: "/admin/activity-log", element: <ActivityLogPage /> },
  { path: "/settings", element: <SettingsPage /> },
  { path: "/hr", element: <HrPage /> },
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
    ],
  },
]);
