import { useEffect, useState, type ComponentType } from "react";
import { NavLink, useLocation } from "react-router-dom";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import {
  AlertOctagon,
  BookOpen,
  Boxes,
  Building2,
  CalendarCheck,
  CalendarClock,
  CalendarDays,
  ChevronDown,
  ChevronsLeft,
  ChevronsRight,
  ClipboardList,
  Cog,
  Contact,
  Factory,
  FileSpreadsheet,
  FileText,
  Fingerprint,
  FlaskConical,
  Gauge,
  GitBranch,
  ListTree,
  HeartPulse,
  History,
  KeyRound,
  LayoutDashboard,
  LineChart,
  BriefcaseBusiness,
  LogOut,
  PackageSearch,
  Recycle,
  Settings as SettingsIcon,
  ShieldCheck,
  ShoppingCart,
  Sparkles,
  Tag,
  Target,
  TrendingUp,
  Truck,
  UserCircle,
  Users,
  Wallet,
  Zap,
} from "lucide-react";
import { useAuth } from "../lib/auth";
import { useI18n, type TranslationKey } from "../lib/i18n";
import { LanguageToggle } from "../components/patterns/LanguageToggle";
import { cn } from "../lib/utils";
import { outlineIcon } from "../components/patterns/outlineIcon";
import ProductionIcon from "../assets/icons/production/line.svg?react";
import QualityIcon from "../assets/icons/quality/check.svg?react";
import MaintenanceIcon from "../assets/icons/maintenance/wrench.svg?react";
import WarehouseIcon from "../assets/icons/warehouse/warehouse.svg?react";
import ApprovalIcon from "../assets/icons/quality/approval.svg?react";
import ExtrusionIcon from "../assets/icons/production/extrusion.svg?react";
import LabIcon from "../assets/icons/quality/lab.svg?react";
import PlanningIcon from "../assets/icons/production/planning.svg?react";
import WorkOrderIcon from "../assets/icons/production/work-order.svg?react";

const COLLAPSED_STORAGE_KEY = "sonalim-erp.sidebar-collapsed";

function readStoredCollapsed(): boolean {
  try {
    return localStorage.getItem(COLLAPSED_STORAGE_KEY) === "1";
  } catch {
    return false;
  }
}

type NavIcon = ComponentType<{ className?: string }>;

/** A screen inside a page that lives behind a `?tab=` parameter -- deep-linkable, so it can be a nav entry. */
interface NavChild {
  tab: string;
  labelKey: TranslationKey;
  icon: NavIcon;
}

interface NavItem {
  to: string;
  labelKey: TranslationKey;
  icon: NavIcon;
  exact?: boolean;
  /** Hide this item unless the signed-in user holds this permission. Omit to show it to everyone. */
  permission?: string;
  /** Tabs of the page, shown as an expandable sub-list; the active one follows the URL's `?tab=`. */
  children?: NavChild[];
  /** The tab the page opens when the URL names none. */
  defaultTab?: string;
}

interface NavGroup {
  labelKey: TranslationKey;
  items: NavItem[];
}

// The analytics tabs, in the order the page lists them (Production first, then Cost & pricing).
const ANALYTICS_TABS: NavChild[] = [
  { tab: "overview", labelKey: "analytics.tabs.overview", icon: Factory },
  { tab: "yield-waste", labelKey: "analytics.tabs.yieldWaste", icon: Recycle },
  { tab: "team-performance", labelKey: "analytics.tabs.teamPerformance", icon: Users },
  { tab: "machine-performance", labelKey: "analytics.tabs.machinePerformance", icon: Cog },
  { tab: "downtime", labelKey: "analytics.tabs.downtime", icon: Gauge },
  { tab: "energy", labelKey: "analytics.tabs.energy", icon: Zap },
  { tab: "quality", labelKey: "analytics.tabs.quality", icon: ShieldCheck },
  { tab: "shift-health", labelKey: "analytics.tabs.shiftHealth", icon: HeartPulse },
  { tab: "consumption-report", labelKey: "analytics.tabs.consumptionReport", icon: PackageSearch },
  { tab: "production-recap", labelKey: "analytics.tabs.productionRecap", icon: FileSpreadsheet },
  { tab: "price-history", labelKey: "analytics.tabs.priceHistory", icon: TrendingUp },
];

// The production page's tabs, in the order its in-page TabsList shows them.
const PRODUCTION_TABS: NavChild[] = [
  { tab: "work-orders", labelKey: "production.tabs.workOrders", icon: outlineIcon(WorkOrderIcon) },
  { tab: "planning", labelKey: "production.tabs.planning", icon: outlineIcon(PlanningIcon) },
  { tab: "shift-report", labelKey: "production.tabs.shiftReport", icon: ClipboardList },
  { tab: "day-sheet", labelKey: "production.tabs.daySheet", icon: FileSpreadsheet },
  { tab: "validation", labelKey: "production.tabs.validation", icon: outlineIcon(ApprovalIcon) },
  { tab: "recipes", labelKey: "production.tabs.recipes", icon: outlineIcon(LabIcon) },
  { tab: "regrind", labelKey: "production.tabs.regrind", icon: Recycle },
  { tab: "work-centers", labelKey: "production.tabs.workCenters", icon: Factory },
  { tab: "molds", labelKey: "production.tabs.molds", icon: outlineIcon(ExtrusionIcon) },
  { tab: "packaging-boms", labelKey: "production.tabs.packagingBoms", icon: Boxes },
  { tab: "classifications", labelKey: "production.tabs.classifications", icon: Tag },
  { tab: "settings", labelKey: "production.tabs.settings", icon: SettingsIcon },
];

const QUALITY_TABS: NavChild[] = [
  { tab: "dashboard", labelKey: "qc.tabs.dashboard", icon: LayoutDashboard },
  { tab: "reports", labelKey: "qc.tabs.qualityReports", icon: FlaskConical },
  { tab: "non-conformities", labelKey: "qc.tabs.nonConformities", icon: AlertOctagon },
  { tab: "lot-dlc", labelKey: "qc.tabs.lotDlc", icon: CalendarClock },
];

const NAV_GROUPS: NavGroup[] = [
  {
    labelKey: "nav.hr",
    items: [
      { to: "/hr/employees", labelKey: "nav.hrEmployees", icon: Users, permission: "hr.view_employees" },
      { to: "/hr/organisation", labelKey: "nav.hrOrganisation", icon: Building2 },
      { to: "/hr", labelKey: "nav.hrLegacy", icon: BriefcaseBusiness, exact: true },
      { to: "/hr/presence", labelKey: "nav.hrPresence", icon: CalendarCheck, exact: true, permission: "hr.view_presence" },
      { to: "/hr/presence/imports", labelKey: "nav.hrClockImports", icon: Fingerprint, permission: "hr.view_presence" },
      { to: "/hr/leave", labelKey: "nav.hrLeave", icon: CalendarDays, permission: "hr.view_leave" },
      { to: "/hr/schedules", labelKey: "nav.hrSchedules", icon: CalendarClock, permission: "hr.view_presence" },
    ],
  },
  {
    labelKey: "nav.crm",
    items: [
      { to: "/crm", labelKey: "nav.dashboard", icon: LayoutDashboard, exact: true },
      { to: "/crm/leads", labelKey: "nav.leads", icon: Contact },
      { to: "/crm/partners", labelKey: "nav.partners", icon: Building2 },
      { to: "/crm/opportunities", labelKey: "nav.opportunities", icon: Target },
      { to: "/crm/activities", labelKey: "nav.activities", icon: CalendarDays },
      { to: "/crm/pipeline", labelKey: "nav.pipeline", icon: Target },
    ],
  },
  {
    labelKey: "nav.operations",
    items: [
      { to: "/production/dashboard", labelKey: "nav.dashboard", icon: LayoutDashboard },
      { to: "/production", labelKey: "nav.production", icon: ProductionIcon, children: PRODUCTION_TABS, defaultTab: "work-orders" },
      { to: "/production/ia-assistant", labelKey: "nav.iaAssistant", icon: Sparkles, permission: "production.use_ia_assistant" },
    ],
  },
  {
    labelKey: "nav.quality",
    items: [{ to: "/quality", labelKey: "nav.quality", icon: QualityIcon, children: QUALITY_TABS, defaultTab: "dashboard" }],
  },
  {
    labelKey: "nav.analytics",
    items: [{ to: "/analytics", labelKey: "nav.analytics", icon: LineChart, children: ANALYTICS_TABS, defaultTab: "overview" }],
  },
  {
    labelKey: "nav.maintenance",
    items: [{ to: "/maintenance", labelKey: "nav.maintenance", icon: MaintenanceIcon }],
  },
  {
    labelKey: "nav.productsServices",
    items: [
      { to: "/warehouse", labelKey: "nav.warehouse", icon: WarehouseIcon },
      { to: "/products", labelKey: "nav.products", icon: PackageSearch },
      { to: "/inventories", labelKey: "nav.inventories", icon: ClipboardList },
      { to: "/shipments", labelKey: "nav.shipments", icon: Truck },
      { to: "/procurement", labelKey: "nav.purchaseOrders", icon: FileText },
    ],
  },
  {
    labelKey: "nav.commerce",
    items: [
      { to: "/sales", labelKey: "nav.sales", icon: ShoppingCart },
      { to: "/finance", labelKey: "nav.finance", icon: Wallet, exact: true },
    ],
  },
  {
    labelKey: "nav.accounting",
    items: [
      { to: "/finance/entries", labelKey: "nav.ledgerEntries", icon: BookOpen, permission: "finance.view_ledger" },
      { to: "/finance/accounts", labelKey: "nav.chartOfAccounts", icon: ListTree, permission: "finance.view_ledger" },
      { to: "/finance/posting-rules", labelKey: "nav.postingRules", icon: GitBranch, permission: "finance.view_ledger" },
    ],
  },
  {
    labelKey: "nav.administration",
    items: [
      { to: "/admin/users", labelKey: "nav.users", icon: ShieldCheck },
      { to: "/admin/roles", labelKey: "nav.roles", icon: KeyRound },
      { to: "/admin/activity-log", labelKey: "nav.activityLog", icon: History, permission: "core.view_audit_log" },
    ],
  },
];

function isItemActive(item: NavItem, pathname: string): boolean {
  return item.exact ? pathname === item.to : pathname.startsWith(item.to);
}

export function Sidebar() {
  const { session, logout, hasPermission } = useAuth();
  const { t, language, setLanguage } = useI18n();
  const location = useLocation();
  const reduceMotion = useReducedMotion();
  const [collapsed, setCollapsed] = useState(() => readStoredCollapsed());
  // Which expandable items the person opened or closed by hand; an item on the
  // current page is open unless they closed it, and closes again on leaving.
  const [toggled, setToggled] = useState<Record<string, boolean>>({});
  const currentTab = new URLSearchParams(location.search).get("tab");

  useEffect(() => {
    try {
      localStorage.setItem(COLLAPSED_STORAGE_KEY, collapsed ? "1" : "0");
    } catch {
      // private browsing / storage blocked — collapsed state just won't persist
    }
  }, [collapsed]);

  useEffect(() => {
    setToggled({});
  }, [location.pathname]);

  const linkClass = (active: boolean) =>
    cn(
      "relative flex items-center gap-2.5 rounded-md py-1.5 text-sm font-medium text-muted-foreground transition-colors hover:text-foreground",
      collapsed ? "justify-center px-1.5" : "px-2.5",
      active && "text-primary",
    );

  return (
    <aside
      className={cn(
        "flex h-full shrink-0 flex-col border-r border-border bg-background transition-[width] duration-200",
        collapsed ? "w-16" : "w-64",
      )}
    >
      <div className={cn("flex items-center gap-2.5 py-5", collapsed ? "justify-center px-2" : "px-5")}>
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-primary to-accent text-sm font-bold text-primary-foreground shadow-glow">
          SE
        </div>
        {!collapsed && (
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-semibold leading-tight">Sonalim ERP</p>
            <p className="truncate text-[11px] leading-tight text-muted-foreground">{session?.tenantId ?? "—"}</p>
          </div>
        )}
        {!collapsed && <LanguageToggle language={language} onChange={setLanguage} />}
      </div>

      <nav className="scrollbar-none flex-1 space-y-5 overflow-y-auto overflow-x-hidden px-3 pb-4">
        {NAV_GROUPS.map((group) => {
          const visibleItems = group.items.filter((item) => !item.permission || hasPermission(item.permission));
          if (visibleItems.length === 0) return null;
          // Longest matching path wins, not "first matching, unconditionally" --
          // two items sharing a base path (e.g. /production and
          // /production/ia-assistant) would otherwise both light up on the more
          // specific one's page, since it also starts with the shorter path.
          const activeItem = [...visibleItems].sort((a, b) => b.to.length - a.to.length).find((it) => isItemActive(it, location.pathname));
          return (
            <div key={group.labelKey}>
              {!collapsed && (
                <p className="px-2.5 pb-1.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground/70">{t(group.labelKey)}</p>
              )}
              <div className="space-y-0.5">
                {visibleItems.map((item) => {
                  const active = item === activeItem;
                  const expandable = !collapsed && !!item.children?.length;
                  const expanded = expandable && (toggled[item.to] ?? active);
                  const activeTab = active ? (currentTab ?? item.defaultTab ?? null) : null;
                  return (
                    <div key={item.to}>
                      <div className="relative flex items-center">
                        <NavLink to={item.to} title={collapsed ? t(item.labelKey) : undefined} className={cn(linkClass(active), "min-w-0 flex-1")}>
                          {active && (
                            <motion.span
                              layoutId="sidebar-active"
                              className="absolute inset-0 rounded-md bg-primary/10"
                              transition={{ type: "spring", stiffness: 500, damping: 40 }}
                            />
                          )}
                          <item.icon className={cn("relative h-4 w-4 shrink-0", active && "text-primary")} />
                          {!collapsed && <span className="relative truncate">{t(item.labelKey)}</span>}
                        </NavLink>
                        {expandable && (
                          <button
                            type="button"
                            aria-expanded={expanded}
                            aria-label={t(expanded ? "nav.collapseSection" : "nav.expandSection")}
                            onClick={() => setToggled((prev) => ({ ...prev, [item.to]: !expanded }))}
                            className="relative z-10 mr-1 shrink-0 rounded-md p-1 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                          >
                            <motion.span
                              className="block"
                              animate={{ rotate: expanded ? 0 : -90 }}
                              transition={{ duration: reduceMotion ? 0 : 0.18 }}
                            >
                              <ChevronDown className="h-3.5 w-3.5" />
                            </motion.span>
                          </button>
                        )}
                      </div>

                      <AnimatePresence initial={false}>
                        {expanded && item.children && (
                          <motion.ul
                            key="children"
                            initial={reduceMotion ? false : { height: 0, opacity: 0 }}
                            animate={{ height: "auto", opacity: 1 }}
                            exit={reduceMotion ? undefined : { height: 0, opacity: 0 }}
                            transition={{ duration: 0.2, ease: [0.2, 0.8, 0.2, 1] }}
                            className="relative ml-[1.15rem] overflow-hidden border-l border-border pl-2"
                          >
                            {item.children.map((child) => {
                              const childActive = active && activeTab === child.tab;
                              return (
                                <li key={child.tab} className="py-px">
                                  <NavLink
                                    to={`${item.to}?tab=${child.tab}`}
                                    className={cn(
                                      "relative flex items-center gap-2 rounded-md px-2 py-1 text-[13px] text-muted-foreground transition-colors hover:text-foreground",
                                      childActive && "font-medium text-primary",
                                    )}
                                  >
                                    {childActive && (
                                      <motion.span
                                        layoutId={`sidebar-sub-${item.to}`}
                                        className="absolute inset-0 rounded-md bg-primary/[0.07]"
                                        transition={{ type: "spring", stiffness: 500, damping: 40 }}
                                      />
                                    )}
                                    <child.icon className={cn("relative h-3.5 w-3.5 shrink-0", childActive ? "text-primary" : "text-muted-foreground/70")} />
                                    <span className="relative truncate">{t(child.labelKey)}</span>
                                  </NavLink>
                                </li>
                              );
                            })}
                          </motion.ul>
                        )}
                      </AnimatePresence>
                    </div>
                  );
                })}
              </div>
            </div>
          );
        })}
      </nav>

      <div className="border-t border-border p-3">
        <NavLink to="/settings" title={collapsed ? t("nav.settings") : undefined} className={cn(linkClass(location.pathname.startsWith("/settings")), "mb-1")}>
          {location.pathname.startsWith("/settings") && (
            <motion.span
              layoutId="sidebar-active"
              className="absolute inset-0 rounded-md bg-primary/10"
              transition={{ type: "spring", stiffness: 500, damping: 40 }}
            />
          )}
          <SettingsIcon className={cn("relative h-4 w-4 shrink-0", location.pathname.startsWith("/settings") && "text-primary")} />
          {!collapsed && <span className="relative truncate">{t("nav.settings")}</span>}
        </NavLink>

        <div className={cn("flex items-center gap-2.5 rounded-md py-2", collapsed ? "justify-center px-1.5" : "px-2.5")}>
          <UserCircle className="h-7 w-7 shrink-0 text-muted-foreground" />
          {!collapsed && (
            <div className="min-w-0 flex-1">
              <p className="truncate text-xs font-medium">{session?.email ?? session?.userId ?? "—"}</p>
              <p className="truncate text-[11px] text-muted-foreground">{t("nav.signedIn")}</p>
            </div>
          )}
          <button
            onClick={logout}
            aria-label={t("nav.signOut")}
            title={collapsed ? t("nav.signOut") : undefined}
            className="shrink-0 rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-destructive"
          >
            <LogOut className="h-4 w-4" />
          </button>
        </div>

        <button
          onClick={() => setCollapsed((prev) => !prev)}
          aria-label={collapsed ? t("nav.expandSidebar") : t("nav.collapseSidebar")}
          title={collapsed ? t("nav.expandSidebar") : t("nav.collapseSidebar")}
          className={cn(
            "mt-1 flex w-full items-center gap-2.5 rounded-md py-1.5 text-sm font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground",
            collapsed ? "justify-center px-1.5" : "px-2.5",
          )}
        >
          {collapsed ? <ChevronsRight className="h-4 w-4 shrink-0" /> : <ChevronsLeft className="h-4 w-4 shrink-0" />}
          {!collapsed && <span>{t("nav.collapseSidebar")}</span>}
        </button>
      </div>
    </aside>
  );
}
