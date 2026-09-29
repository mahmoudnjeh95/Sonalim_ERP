import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { CalendarDays } from "lucide-react";
import { useAuth } from "../../../lib/auth";
import { useI18n, type TranslationKey } from "../../../lib/i18n";
import { useColumnFilters } from "../../../lib/useColumnFilters";
import type { ColumnDef } from "../../../lib/useTableColumns";
import { FilterTabs } from "../../../components/patterns/FilterTabs";
import { Badge } from "../../../components/ui/badge";
import { Button } from "../../../components/ui/button";
import { Card, CardContent } from "../../../components/ui/card";
import { hrKeys, listLeaveRequests, type EmployeeRecord, type LeaveRequest } from "../api";
import { formatDate } from "../employeeFormat";
import { HrTable } from "../HrTable";

type LeaveStatus = LeaveRequest["status"];
const LEAVE_STATUSES: LeaveStatus[] = ["pending", "approved", "rejected", "cancelled"];
const LEAVE_STATUS_LABEL: Record<LeaveStatus, TranslationKey> = {
  pending: "hr.file.leave.status.pending",
  approved: "hr.file.leave.status.approved",
  rejected: "hr.file.leave.status.rejected",
  cancelled: "hr.file.leave.status.cancelled",
};

export function LeaveTab({ employee }: { employee: EmployeeRecord }) {
  const { session } = useAuth();
  const { t } = useI18n();
  const [status, setStatus] = useState<"all" | LeaveStatus>("all");
  const { data = [], isLoading } = useQuery({ queryKey: hrKeys.leave, queryFn: () => listLeaveRequests(session!.token) });
  const mine = data.filter((row) => row.employee_id === employee.id);
  const filters = useColumnFilters<LeaveRequest>([
    { key: "type", kind: "text", getValue: (row) => row.leave_type },
    { key: "reason", kind: "text", getValue: (row) => row.reason },
  ]);
  const rows = filters.apply(status === "all" ? mine : mine.filter((row) => row.status === status));
  const statusOptions: { value: "all" | LeaveStatus; label: string }[] = [
    { value: "all", label: t("common.all") },
    ...LEAVE_STATUSES.map((value) => ({ value, label: t(LEAVE_STATUS_LABEL[value]) })),
  ];
  const columns: ColumnDef<LeaveRequest>[] = [
    {
      key: "type",
      header: t("hr.file.leave.type"),
      defaultWidth: 150,
      cell: (row) => row.leave_type,
      filterCell: { type: "text", value: filters.text.type ?? "", onChange: (value) => filters.setTextValue("type", value), placeholder: t("hr.file.leave.type") },
      sortValue: (row) => row.leave_type,
    },
    { key: "start", header: t("hr.file.leave.start"), defaultWidth: 120, cell: (row) => formatDate(row.start_date), sortValue: (row) => row.start_date },
    { key: "end", header: t("hr.file.leave.end"), defaultWidth: 120, cell: (row) => formatDate(row.end_date), sortValue: (row) => row.end_date },
    {
      key: "reason",
      header: t("hr.file.leave.reason"),
      defaultWidth: 240,
      cell: (row) => row.reason ?? "—",
      filterCell: { type: "text", value: filters.text.reason ?? "", onChange: (value) => filters.setTextValue("reason", value), placeholder: t("hr.file.leave.reason") },
    },
    { key: "status", header: t("hr.field.status"), defaultWidth: 120, cell: (row) => <Badge>{t(LEAVE_STATUS_LABEL[row.status])}</Badge>, sortValue: (row) => row.status },
  ];

  return (
    <Card>
      <CardContent className="space-y-3 pt-6">
        <div className="flex flex-wrap items-center justify-between gap-2 text-sm text-muted-foreground">
          <span>{t("hr.file.leave.hint")}</span>
          <Button size="sm" variant="outline" asChild>
            <Link to="/hr">{t("hr.file.leave.open")}</Link>
          </Button>
        </div>
        <HrTable
          tableKey="hr.employee.leave"
          columns={columns}
          rows={rows}
          rowKey={(row) => row.id}
          isLoading={isLoading}
          empty={{ icon: <CalendarDays className="h-5 w-5" />, title: t("hr.file.leave.empty.title"), description: t("hr.file.leave.empty.description") }}
          toolbar={<FilterTabs value={status} onChange={setStatus} options={statusOptions} />}
          filtersActive={filters.isActive}
          onClearFilters={filters.reset}
        />
      </CardContent>
    </Card>
  );
}
