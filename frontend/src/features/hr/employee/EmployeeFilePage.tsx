import { useState, type ComponentType } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import { ArrowLeft, Ban, CalendarDays, FileStack, FileText, Pencil, Receipt, UserRound, Users, Wallet } from "lucide-react";
import { useAuth } from "../../../lib/auth";
import { useI18n, type TranslationKey } from "../../../lib/i18n";
import { AppLoader } from "../../../components/patterns/AppLoader";
import { EmptyState } from "../../../components/patterns/EmptyState";
import { StickyTabBar } from "../../../components/patterns/StickyTabBar";
import { Badge } from "../../../components/ui/badge";
import { Button } from "../../../components/ui/button";
import { Tabs, TabsList, TabsTrigger } from "../../../components/ui/tabs";
import { getEmployee, hrKeys, type EmployeeRecord } from "../api";
import { EMPLOYEE_STATUS_LABEL, EMPLOYEE_STATUS_VARIANT } from "../employeeLabels";
import { EmployeeFormDialog } from "../EmployeeFormDialog";
import { ContractsTab } from "./ContractsTab";
import { DocumentsTab } from "./DocumentsTab";
import { FamilyTab } from "./FamilyTab";
import { IdentityTab } from "./IdentityTab";
import { LeaveTab } from "./LeaveTab";
import { PaymentTab } from "./PaymentTab";
import { PayslipsTab } from "./PayslipsTab";
import { TerminateDialog } from "./TerminateDialog";

type TabValue = "identity" | "family" | "contracts" | "payment" | "documents" | "leave" | "payslips";

interface TabDef {
  value: TabValue;
  labelKey: TranslationKey;
  icon: ComponentType<{ className?: string }>;
  permission: string;
}

const TABS: TabDef[] = [
  { value: "identity", labelKey: "hr.file.tab.identity", icon: UserRound, permission: "hr.view_employees" },
  { value: "family", labelKey: "hr.file.tab.family", icon: Users, permission: "hr.view_employees" },
  { value: "contracts", labelKey: "hr.file.tab.contracts", icon: FileText, permission: "hr.view_contracts" },
  { value: "payment", labelKey: "hr.file.tab.payment", icon: Wallet, permission: "hr.view_employees" },
  { value: "documents", labelKey: "hr.file.tab.documents", icon: FileStack, permission: "hr.view_employees" },
  { value: "leave", labelKey: "hr.file.tab.leave", icon: CalendarDays, permission: "hr.view_leave" },
  { value: "payslips", labelKey: "hr.file.tab.payslips", icon: Receipt, permission: "hr.view_employees" },
];

function TabBody({ tab, employee }: { tab: TabValue; employee: EmployeeRecord }) {
  switch (tab) {
    case "identity":
      return <IdentityTab employee={employee} />;
    case "family":
      return <FamilyTab employee={employee} />;
    case "contracts":
      return <ContractsTab employee={employee} />;
    case "payment":
      return <PaymentTab employee={employee} />;
    case "documents":
      return <DocumentsTab employee={employee} />;
    case "leave":
      return <LeaveTab employee={employee} />;
    case "payslips":
      return <PayslipsTab />;
    default:
      return null;
  }
}

export function EmployeeFilePage() {
  const { employeeId } = useParams();
  const { session, hasPermission } = useAuth();
  const { t } = useI18n();
  const [searchParams, setSearchParams] = useSearchParams();
  const [editOpen, setEditOpen] = useState(false);
  const [terminateOpen, setTerminateOpen] = useState(false);
  const { data: employee, isLoading, isError } = useQuery({
    queryKey: hrKeys.employee(employeeId!),
    queryFn: () => getEmployee(session!.token, employeeId!),
  });

  // The tab lives in the URL so an alert link can land straight on it.
  const tabs = TABS.filter((entry) => hasPermission(entry.permission));
  const requested = searchParams.get("tab");
  const tab: TabValue = tabs.find((entry) => entry.value === requested)?.value ?? "identity";
  const setTab = (value: TabValue) => setSearchParams({ tab: value }, { replace: true });

  if (isLoading) return <AppLoader label={t("hr.file.loading")} className="min-h-[220px]" />;
  if (isError || !employee) {
    return (
      <EmptyState
        icon={<UserRound className="h-5 w-5" />}
        title={t("hr.file.notFound.title")}
        description={t("hr.file.notFound.description")}
        action={
          <Button variant="outline" asChild>
            <Link to="/hr/employees">{t("hr.file.back")}</Link>
          </Button>
        }
      />
    );
  }

  return (
    <div className="space-y-6">
      <motion.div
        initial={{ opacity: 0, y: -6 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.25 }}
        className="flex flex-wrap items-start justify-between gap-3"
      >
        <div className="flex items-start gap-3">
          <Button variant="ghost" size="sm" asChild>
            <Link to="/hr/employees">
              <ArrowLeft className="h-4 w-4" />
              {t("hr.file.back")}
            </Link>
          </Button>
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-xl font-semibold tracking-tight">{employee.full_name}</h1>
              <Badge variant={EMPLOYEE_STATUS_VARIANT[employee.status]} dot>
                {t(EMPLOYEE_STATUS_LABEL[employee.status])}
              </Badge>
            </div>
            <p className="text-sm text-muted-foreground">
              {[employee.employee_no, employee.position_title ?? employee.job_title, employee.department_name].filter(Boolean).join(" · ")}
            </p>
          </div>
        </div>
        <div className="flex gap-2">
          {hasPermission("hr.admin_employees") && (
            <Button variant="outline" onClick={() => setEditOpen(true)}>
              <Pencil className="h-4 w-4" />
              {t("hr.file.edit")}
            </Button>
          )}
          {hasPermission("hr.manage_employees") && employee.status !== "terminated" && (
            <Button variant="outline" onClick={() => setTerminateOpen(true)}>
              <Ban className="h-4 w-4" />
              {t("hr.terminate.action")}
            </Button>
          )}
        </div>
      </motion.div>

      <StickyTabBar>
        <Tabs value={tab} onValueChange={(value) => setTab(value as TabValue)}>
          <TabsList>
            {tabs.map((entry) => (
              <TabsTrigger key={entry.value} value={entry.value} active={tab === entry.value} layoutId="hr-employee-file-tab">
                <span className="flex items-center gap-1.5">
                  <entry.icon className="h-4 w-4" />
                  {t(entry.labelKey)}
                </span>
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
      </StickyTabBar>

      <AnimatePresence mode="wait">
        <motion.div key={tab} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }} transition={{ duration: 0.2 }}>
          <TabBody tab={tab} employee={employee} />
        </motion.div>
      </AnimatePresence>

      <EmployeeFormDialog open={editOpen} onOpenChange={setEditOpen} employee={employee} />
      <TerminateDialog open={terminateOpen} onOpenChange={setTerminateOpen} employee={employee} />
    </div>
  );
}
