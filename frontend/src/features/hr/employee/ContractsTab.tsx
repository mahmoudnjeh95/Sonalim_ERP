import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Ban, CheckCircle2, FileText, Pencil, Plus, Split } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../../../lib/auth";
import { useI18n } from "../../../lib/i18n";
import { ApiError } from "../../../lib/api";
import { useColumnFilters } from "../../../lib/useColumnFilters";
import type { ColumnDef } from "../../../lib/useTableColumns";
import { FilterTabs } from "../../../components/patterns/FilterTabs";
import { RowActionsMenu, type RowAction } from "../../../components/patterns/RowActionsMenu";
import { Badge } from "../../../components/ui/badge";
import { Button } from "../../../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../../../components/ui/card";
import { activateContract, CONTRACT_STATUSES, hrKeys, listContracts, type Contract, type ContractStatus, type EmployeeRecord } from "../api";
import { CONTRACT_STATUS_LABEL, CONTRACT_STATUS_VARIANT, CONTRACT_TYPE_LABEL, END_REASON_LABEL, PAY_FREQUENCY_LABEL } from "../employeeLabels";
import { formatDate, formatXof } from "../employeeFormat";
import { HrTable } from "../HrTable";
import { Masked } from "../Masked";
import { ContractFormDialog, type ContractDialogMode } from "./ContractFormDialog";
import { EndContractDialog } from "./EndContractDialog";

type StatusFilter = "all" | ContractStatus;

export function ContractsTab({ employee }: { employee: EmployeeRecord }) {
  const { session, hasPermission } = useAuth();
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<StatusFilter>("all");
  const [form, setForm] = useState<{ open: boolean; mode: ContractDialogMode; contract: Contract | null }>({ open: false, mode: "create", contract: null });
  const [ending, setEnding] = useState<Contract | null>(null);
  const { data: contracts = [], isLoading } = useQuery({
    queryKey: hrKeys.employeeContracts(employee.id),
    queryFn: () => listContracts(session!.token, employee.id),
  });
  const activate = useMutation({
    mutationFn: (contract: Contract) => activateContract(session!.token, contract.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: hrKeys.contracts });
      queryClient.invalidateQueries({ queryKey: hrKeys.employees });
      toast.success(t("hr.contracts.activated"));
    },
    onError: (error) => toast.error(t("hr.contracts.error"), { description: error instanceof ApiError ? error.message : undefined }),
  });

  const filters = useColumnFilters<Contract>([
    { key: "position", kind: "text", getValue: (row) => row.position_title },
    { key: "grade", kind: "text", getValue: (row) => row.grade_code },
    { key: "pay", kind: "range", getValue: (row) => row.base_salary },
    { key: "components", kind: "text", getValue: (row) => row.components.map((c) => c.component_code).join(" ") },
  ]);
  const rows = filters.apply(status === "all" ? contracts : contracts.filter((row) => row.status === status));
  const statusOptions: { value: StatusFilter; label: string }[] = [
    { value: "all", label: t("common.all") },
    ...CONTRACT_STATUSES.map((value) => ({ value, label: t(CONTRACT_STATUS_LABEL[value]) })),
  ];
  const canCreate = hasPermission("hr.manage_contracts") && hasPermission("hr.view_sensitive") && employee.status !== "terminated";

  const actionsFor = (row: Contract): RowAction[] => {
    const actions: RowAction[] = [];
    if (hasPermission("hr.admin_contracts")) {
      actions.push({ key: "edit", label: t("hr.contracts.action.edit"), icon: <Pencil className="h-3.5 w-3.5" />, onSelect: () => setForm({ open: true, mode: "edit", contract: row }) });
    }
    if (hasPermission("hr.manage_contracts") && row.status === "draft") {
      actions.push({ key: "activate", label: t("hr.contracts.action.activate"), icon: <CheckCircle2 className="h-3.5 w-3.5" />, onSelect: () => activate.mutate(row) });
    }
    if (hasPermission("hr.manage_contracts") && row.status === "active") {
      actions.push({ key: "amend", label: t("hr.contracts.action.amend"), icon: <Split className="h-3.5 w-3.5" />, onSelect: () => setForm({ open: true, mode: "amend", contract: row }) });
      actions.push({ key: "end", label: t("hr.contracts.action.end"), icon: <Ban className="h-3.5 w-3.5" />, tone: "destructive", onSelect: () => setEnding(row) });
    }
    return actions;
  };

  const columns: ColumnDef<Contract>[] = [
    { key: "type", header: t("hr.contracts.column.type"), defaultWidth: 150, cell: (row) => t(CONTRACT_TYPE_LABEL[row.contract_type]), sortValue: (row) => row.contract_type },
    { key: "start", header: t("hr.contracts.column.start"), defaultWidth: 115, cell: (row) => formatDate(row.start_date), sortValue: (row) => row.start_date },
    { key: "end", header: t("hr.contracts.column.end"), defaultWidth: 115, cell: (row) => formatDate(row.end_date), sortValue: (row) => row.end_date },
    { key: "trial", header: t("hr.contracts.column.trialEnd"), defaultWidth: 115, cell: (row) => formatDate(row.trial_end_date), sortValue: (row) => row.trial_end_date },
    { key: "hours", header: t("hr.contracts.column.hours"), defaultWidth: 110, cell: (row) => row.weekly_hours, sortValue: (row) => row.weekly_hours },
    {
      key: "pay",
      header: t("hr.contracts.column.pay"),
      defaultWidth: 170,
      cell: (row) =>
        row.sensitive_hidden ? (
          <Masked />
        ) : (
          <span className="tabular-nums">
            {formatXof(row.base_salary)} {t(row.pay_frequency === "daily" ? "hr.contracts.perDay" : "hr.contracts.perMonth")}
            {row.currency !== "XOF" && <span className="ml-1 text-xs text-destructive">{row.currency}</span>}
          </span>
        ),
      filterCell: {
        type: "range",
        min: filters.range.pay?.min ?? "",
        max: filters.range.pay?.max ?? "",
        onMinChange: (value) => filters.setRangeValue("pay", "min", value),
        onMaxChange: (value) => filters.setRangeValue("pay", "max", value),
      },
      sortValue: (row) => row.base_salary,
    },
    {
      key: "components",
      header: t("hr.contracts.column.components"),
      defaultWidth: 220,
      cell: (row) =>
        row.components.length === 0
          ? "—"
          : row.components.map((c) => (
              <span key={c.component_code} className="mr-2 whitespace-nowrap text-xs">
                {c.component_code}{" "}
                {row.sensitive_hidden ? "••••" : c.rate !== null ? `${c.rate} %` : formatXof(c.amount)}
              </span>
            )),
      filterCell: {
        type: "text",
        value: filters.text.components ?? "",
        onChange: (value) => filters.setTextValue("components", value),
        placeholder: t("hr.contracts.column.components"),
      },
    },
    {
      key: "position",
      header: t("hr.field.position"),
      defaultWidth: 160,
      cell: (row) => row.position_title ?? "—",
      filterCell: { type: "text", value: filters.text.position ?? "", onChange: (value) => filters.setTextValue("position", value), placeholder: t("hr.field.position") },
    },
    {
      key: "grade",
      header: t("hr.field.grade"),
      defaultWidth: 100,
      cell: (row) => row.grade_code ?? "—",
      filterCell: { type: "text", value: filters.text.grade ?? "", onChange: (value) => filters.setTextValue("grade", value), placeholder: t("hr.field.grade") },
    },
    {
      key: "status",
      header: t("hr.contracts.column.status"),
      defaultWidth: 110,
      cell: (row) => (
        <Badge variant={CONTRACT_STATUS_VARIANT[row.status]} dot>
          {t(CONTRACT_STATUS_LABEL[row.status])}
        </Badge>
      ),
      sortValue: (row) => row.status,
    },
    { key: "reason", header: t("hr.contracts.column.endReason"), defaultWidth: 170, cell: (row) => (row.end_reason ? t(END_REASON_LABEL[row.end_reason]) : "—") },
    { key: "frequency", header: t("hr.contracts.field.frequency"), defaultWidth: 110, cell: (row) => t(PAY_FREQUENCY_LABEL[row.pay_frequency]) },
    { key: "actions", header: "", defaultWidth: 70, alwaysVisible: true, cellClassName: "text-right", cell: (row) => <RowActionsMenu actions={actionsFor(row)} /> },
  ];

  return (
    <Card>
      <CardHeader className="flex-row flex-wrap items-center justify-between gap-3">
        <CardTitle className="text-base">{t("hr.contracts.title")}</CardTitle>
        {hasPermission("hr.manage_contracts") && (
          <div className="flex items-center gap-2">
            {!hasPermission("hr.view_sensitive") && <span className="text-xs text-muted-foreground">{t("hr.contracts.needsSensitive")}</span>}
            <Button disabled={!canCreate} onClick={() => setForm({ open: true, mode: "create", contract: null })}>
              <Plus className="h-4 w-4" />
              {t("hr.contracts.new")}
            </Button>
          </div>
        )}
      </CardHeader>
      <CardContent>
        <HrTable
          tableKey="hr.employee.contracts"
          columns={columns}
          rows={rows}
          rowKey={(row) => row.id}
          isLoading={isLoading}
          empty={{ icon: <FileText className="h-5 w-5" />, title: t("hr.contracts.empty.title"), description: t("hr.contracts.empty.description") }}
          toolbar={<FilterTabs value={status} onChange={setStatus} options={statusOptions} />}
          filtersActive={filters.isActive}
          onClearFilters={filters.reset}
        />
      </CardContent>
      <ContractFormDialog
        open={form.open}
        onOpenChange={(open) => setForm((current) => ({ ...current, open }))}
        employeeId={employee.id}
        mode={form.mode}
        contract={form.contract}
      />
      <EndContractDialog open={ending !== null} onOpenChange={(open) => !open && setEnding(null)} contract={ending} />
    </Card>
  );
}
