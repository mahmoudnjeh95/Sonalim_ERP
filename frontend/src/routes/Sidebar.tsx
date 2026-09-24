import { useEffect, useState, type ComponentType } from "react";
import { NavLink, useLocation } from "react-router-dom";
import { motion } from "framer-motion";
import {
  Building2,
  CalendarDays,
  ChevronsLeft,
  ChevronsRight,
  ClipboardList,
  Contact,
  FileText,
  History,
  KeyRound,
  LayoutDashboard,
  LineChart,
  BriefcaseBusiness,
  LogOut,
  PackageSearch,
  Settings as SettingsIcon,
  ShieldCheck,
  ShoppingCart,
  Sparkles,
  Target,
  Truck,
  UserCircle,
  Wallet } from "lucide-react";
import { useAuth } from "../lib/auth";
import { useI18n, type Language } from "../lib/i18n";
import { cn } from "../lib/utils";
import ProductionIcon from "../assets/icons/production/line.svg?react";
import QualityIcon from "../assets/icons/quality/check.svg?react";
import MaintenanceIcon from "../assets/icons/maintenance/wrench.svg?react";
import WarehouseIcon from "../assets/icons/warehouse/warehouse.svg?react";

const COLLAPSED_STORAGE_KEY = "sonalim-erp.sidebar-collapsed";

function readStoredCollapsed(): boolean {
  try {
    return localStorage.getItem(COLLAPSED_STORAGE_KEY) === "1";
  } catch {
    return false;
  }
}

interface NavItem {
  to: string;
  labelKey:
    | "nav.dashboard"
    | "nav.leads"
    | "nav.partners"
    | "nav.opportunities"
    | "nav.activities"
      | "nav.pipeline"
    | "nav.production"
    | "nav.iaAssistant"
    | "nav.quality"
    | "nav.analytics"
    | "nav.maintenance"
    | "nav.warehouse"
    | "nav.products"
    | "nav.inventories"
    | "nav.shipments"
    | "nav.purchaseOrders"
    | "nav.sales"
    | "nav.finance"
    | "nav.users"
    | "nav.roles"
    | "nav.activityLog"
    | "nav.hr";
  icon: ComponentType<{ className?: string }>;
  exact?: boolean;
  /** Hide this item unless the signed-in user holds this permission. Omit to show it to everyone. */
  permission?: string;
}

interface NavGroup {
  labelKey:
    | "nav.crm"
    | "nav.operations"
    | "nav.quality"
    | "nav.analytics"
    | "nav.maintenance"
    | "nav.productsServices"
    | "nav.commerce"
    | "nav.administration"
    | "nav.hr";
  items: NavItem[];
}

const NAV_GROUPS: NavGroup[] = [
  {
    labelKey: "nav.hr",
    items: [{ to: "/hr", labelKey: "nav.hr", icon: BriefcaseBusiness }],
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
      { to: "/production", labelKey: "nav.production", icon: ProductionIcon },
      { to: "/production/ia-assistant", labelKey: "nav.iaAssistant", icon: Sparkles, permission: "production.use_ia_assistant" },
    ],
  },
  {
    labelKey: "nav.quality",
    items: [{ to: "/quality", labelKey: "nav.quality", icon: QualityIcon }],
  },
  {
    labelKey: "nav.analytics",
    items: [{ to: "/analytics", labelKey: "nav.analytics", icon: LineChart }],
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
      { to: "/finance", labelKey: "nav.finance", icon: Wallet },
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

export function Sidebar() {
  const { session, logout, hasPermission } = useAuth();
  const { t, language, setLanguage } = useI18n();
  const location = useLocation();
  const [collapsed, setCollapsed] = useState(() => readStoredCollapsed());

  useEffect(() => {
    try {
      localStorage.setItem(COLLAPSED_STORAGE_KEY, collapsed ? "1" : "0");
    } catch {
      // private browsing / storage blocked — collapsed state just won't persist
    }
  }, [collapsed]);

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
          const activeItem = [...visibleItems]
            .sort((a, b) => b.to.length - a.to.length)
            .find((it) => (it.exact ? location.pathname === it.to : location.pathname.startsWith(it.to)));
          return (
          <div key={group.labelKey}>
            {!collapsed && (
              <p className="px-2.5 pb-1.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground/70">
                {t(group.labelKey)}
              </p>
            )}
            <div className="space-y-0.5">
              {visibleItems.map((item) => {
                const active = item === activeItem;
                return (
                  <NavLink
                    key={item.to}
                    to={item.to}
                    title={collapsed ? t(item.labelKey) : undefined}
                    className={cn(
                      "relative flex items-center gap-2.5 rounded-md py-1.5 text-sm font-medium text-muted-foreground transition-colors hover:text-foreground",
                      collapsed ? "justify-center px-1.5" : "px-2.5",
                    )}
                  >
                    {active && (
                      <motion.span
                        layoutId="sidebar-active"
                        className="absolute inset-0 rounded-md bg-primary/10"
                        transition={{ type: "spring", stiffness: 500, damping: 40 }}
                      />
                    )}
                    <item.icon className={cn("relative h-4 w-4 shrink-0", active && "text-primary")} />
                    {!collapsed && <span className={cn("relative truncate", active && "text-primary")}>{t(item.labelKey)}</span>}
                  </NavLink>
                );
              })}
            </div>
          </div>
          );
        })}
      </nav>

      <div className="border-t border-border p-3">
        <NavLink
          to="/settings"
          title={collapsed ? t("nav.settings") : undefined}
          className={cn(
            "relative mb-1 flex items-center gap-2.5 rounded-md py-1.5 text-sm font-medium text-muted-foreground transition-colors hover:text-foreground",
            collapsed ? "justify-center px-1.5" : "px-2.5",
          )}
        >
          {location.pathname.startsWith("/settings") && (
            <motion.span
              layoutId="sidebar-active"
              className="absolute inset-0 rounded-md bg-primary/10"
              transition={{ type: "spring", stiffness: 500, damping: 40 }}
            />
          )}
          <SettingsIcon className={cn("relative h-4 w-4 shrink-0", location.pathname.startsWith("/settings") && "text-primary")} />
          {!collapsed && (
            <span className={cn("relative truncate", location.pathname.startsWith("/settings") && "text-primary")}>
              {t("nav.settings")}
            </span>
          )}
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

function LanguageToggle({ language, onChange }: { language: Language; onChange: (language: Language) => void }) {
  return (
    <div className="relative flex shrink-0 rounded-md bg-muted p-0.5 text-[10px] font-semibold uppercase">
      {(["en", "fr"] as const).map((code) => (
        <button
          key={code}
          onClick={() => onChange(code)}
          className={cn(
            "relative z-10 rounded px-1.5 py-1 transition-colors",
            language === code ? "text-primary-foreground" : "text-muted-foreground hover:text-foreground",
          )}
        >
          {language === code && (
            <motion.span
              layoutId="lang-toggle"
              className="absolute inset-0 -z-10 rounded bg-primary"
              transition={{ type: "spring", stiffness: 500, damping: 40 }}
            />
          )}
          {code}
        </button>
      ))}
    </div>
  );
}
