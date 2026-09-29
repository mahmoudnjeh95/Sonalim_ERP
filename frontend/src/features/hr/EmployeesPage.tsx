import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { Plus, UserCheck, UserRound, Users } from "lucide-react";
import { useAuth } from "../../lib/auth";
import { useI18n } from "../../lib/i18n";
import { useColumnFilters } from "../../lib/useColumnFilters";
import type { ColumnDef } from "../../lib/useTableColumns";
import type { FilterCell } from "../../components/patterns/ColumnFilterRow";
import { FilterTabs } from "../../components/patterns/FilterTabs";
import { StatCard } from "../../components/patterns/StatCard";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Card, CardContent } from "../../components/ui/card";
import { EMPLOYEE_STATUSES, hrKeys, listEmployees, type EmployeeListItem, type EmployeeStatus } from "./api";
import { CONTRACT_TYPE_LABEL, EMPLOYEE_STATUS_LABEL, EMPLOYEE_STATUS_VARIANT } from "./employeeLabels";
import { formatDate } from "./employeeFormat";
import { HrListTable } from "./HrListTable";
import { EmployeeFormDialog } from "./EmployeeFormDialog";
import { ExpiryAlertsCard } from "./ExpiryAlertsCard";

type StatusFilter = "all" | EmployeeStatus;

export function EmployeesPage() {
  const { session, hasPermission } = useAuth();
  const { t } = useI18n();
  const navigate = useNavigate();
  const [status, setStatus] = useState<StatusFilter>("active");
  const [dialogOpen, setDialogOpen] = useState(false);
  const { data: employees = [], isLoading } = useQuery({ queryKey: hrKeys.employees, queryFn: () => listEmployees(session!.token) });

  const filters = useColumnFilters<EmployeeListItem>([
    { key: "employee_no", kind: "text", getValue: (row) => row.employee_no },
    { key: "name", kind: "text", getValue: (row) => row.full_name },
    { key: "department", kind: "text", getValue: (row) => row.department_name },
    { key: "position", kind: "text", getValue: (row) => row.position_title ?? row.job_title },
    { key: "grade", kind: "text", getValue: (row) => row.grade_code },
    { key: "site", kind: "text", getValue: (row) => row.site },
    { key: "badge", kind: "text", getValue: (row) => row.badge_no },
    { key: "phone", kind: "text", getValue: (row) => row.phone },
  ]);
  const text = (key: string, placeholder: string): FilterCell => ({
    type: "text",
    value: filters.text[key] ?? "",
    onChange: (value) => filters.setTextValue(key, value),
    placeholder,
  });
  const rows = filters.apply(status === "all" ? employees : employees.filter((row) => row.status === status));
  const count = (value: EmployeeStatus) => (isLoading ? null : employees.filter((row) => row.status === value).length);
  const statusOptions: { value: StatusFilter; label: string }[] = [
    { value: "all", label: t("common.all") },
    ...EMPLOYEE_STATUSES.map((value) => ({ value, label: t(EMPLOYEE_STATUS_LABEL[value]) })),
  ];

  const columns: ColumnDef<EmployeeListItem>[] = [
    { key: "employee_no", header: t("hr.field.employeeNo"), defaultWidth: 120, cell: (row) => <span className="font-medium">{row.employee_no}</span>, filterCell: text("employee_no", t("hr.field.employeeNo")), sortValue: (row) => row.employee_no },
    { key: "name", header: t("hr.field.fullName"), defaultWidth: 200, cell: (row) => row.full_name, filterCell: text("name", t("hr.field.fullName")), sortValue: (row) => `${row.last_name} ${row.first_name}` },
    { key: "department", header: t("hr.field.department"), defaultWidth: 160, cell: (row) => row.department_name ?? "—", filterCell: text("department", t("hr.field.department")), sortValue: (row) => row.department_name },
    { key: "position", header: t("hr.field.position"), defaultWidth: 190, cell: (row) => row.position_title ?? row.job_title ?? "—", filterCell: text("position", t("hr.field.position")), sortValue: (row) => row.position_title },
    { key: "grade", header: t("hr.field.grade"), defaultWidth: 110, cell: (row) => row.grade_code ?? "—", filterCell: text("grade", t("hr.field.grade")), sortValue: (row) => row.grade_code },
    {
      key: "contract",
      header: t("hr.field.contract"),
      defaultWidth: 170,
      cell: (row) =>
        row.contract_type
          ? `${t(CONTRACT_TYPE_LABEL[row.contract_type])}${row.contract_end_date ? ` · ${formatDate(row.contract_end_date)}` : ""}`
          : "—",
      sortValue: (row) => row.contract_type,
    },
    { key: "site", header: t("hr.field.site"), defaultWidth: 120, cell: (row) => row.site ?? "—", filterCell: text("site", t("hr.field.site")), sortValue: (row) => row.site },
    { key: "badge", header: t("hr.field.badgeNo"), defaultWidth: 110, cell: (row) => row.badge_no ?? "—", filterCell: text("badge", t("hr.field.badgeNo")), sortValue: (row) => row.badge_no },
    { key: "phone", header: t("hr.field.phone"), defaultWidth: 130, cell: (row) => row.phone ?? "—", filterCell: text("phone", t("hr.field.phone")) },
    { key: "hire_date", header: t("hr.field.hireDate"), defaultWidth: 120, cell: (row) => formatDate(row.hire_date), sortValue: (row) => row.hire_date },
    {
      key: "status",
      header: t("hr.field.status"),
      defaultWidth: 110,
      cell: (row) => (
        <Badge variant={EMPLOYEE_STATUS_VARIANT[row.status]} dot>
          {t(EMPLOYEE_STATUS_LABEL[row.status])}
        </Badge>
      ),
      sortValue: (row) => row.status,
    },
  ];

  return (
    <div className="space-y-6">
      <motion.div
        initial={{ opacity: 0, y: -6 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.25 }}
        className="flex flex-wrap items-start justify-between gap-3"
      >
        <div>
          <h1 className="text-xl font-semibold tracking-tight">{t("hr.list.title")}</h1>
          <p className="text-sm text-muted-foreground">{t("hr.list.subtitle")}</p>
        </div>
        {hasPermission("hr.manage_employees") && (
          <Button onClick={() => setDialogOpen(true)}>
            <Plus className="h-4 w-4" />
            {t("hr.list.new")}
          </Button>
        )}
      </motion.div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <StatCard label={t("hr.list.stat.active")} value={count("active")} icon={<UserCheck className="h-5 w-5" />} accent="success" />
        <StatCard label={t("hr.list.stat.onLeave")} value={count("on_leave")} icon={<Users className="h-5 w-5" />} accent="warning" />
        <StatCard label={t("hr.list.stat.left")} value={count("terminated")} icon={<UserRound className="h-5 w-5" />} />
      </div>

      <ExpiryAlertsCard />

      <Card>
        <CardContent className="pt-6">
          <HrListTable
            tableKey="hr.employees.list"
            columns={columns}
            rows={rows}
            rowKey={(row) => row.id}
            loading={isLoading}
            loadingVariant="loader"
            bordered={false}
            emptyIcon={<Users className="h-5 w-5" />}
            emptyTitle={t("hr.list.empty.title")}
            emptyDescription={t("hr.list.empty.description")}
            toolbar={<FilterTabs value={status} onChange={setStatus} options={statusOptions} />}
            filtersActive={filters.isActive}
            onClearFilters={filters.reset}
            onRowClick={(row) => navigate(`/hr/employees/${row.id}`)}
          />
        </CardContent>
      </Card>

      <EmployeeFormDialog open={dialogOpen} onOpenChange={setDialogOpen} employee={null} onSaved={(record) => navigate(`/hr/employees/${record.id}`)} />
    </div>
  );
}
