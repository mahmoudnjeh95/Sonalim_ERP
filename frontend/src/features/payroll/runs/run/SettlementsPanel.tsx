import { useState, type FormEvent } from "react";
import { toast } from "sonner";
import { Plus, Trash2, UserMinus } from "lucide-react";
import { EmptyState } from "../../../../components/patterns/EmptyState";
import { Button } from "../../../../components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "../../../../components/ui/dialog";
import { Input } from "../../../../components/ui/input";
import { Label } from "../../../../components/ui/label";
import { Select } from "../../../../components/ui/select";
import { currentLocale, useI18n } from "../../../../lib/i18n";
import type { ColumnDef } from "../../../../lib/useTableColumns";
import {
  useAddFinalSettlement,
  useFinalSettlements,
  usePayrollEmployees,
  useRemoveFinalSettlement,
  type FinalSettlement,
  type PayrollRun,
} from "../../api";
import { PayrollTable } from "../../PayrollTable";

function errorText(error: unknown): string | undefined {
  return error instanceof Error ? error.message : undefined;
}

/**
 * Final settlements of an off-cycle run: one per employee whose exit date falls in the run's
 * month. Adding or removing one sends a calculated run back to draft (the server does it).
 */
export function SettlementsPanel({ run, canEdit }: { run: PayrollRun; canEdit: boolean }) {
  const { t } = useI18n();
  const offCycle = run.run_type === "off_cycle";
  const editable = canEdit && (run.status === "draft" || run.status === "calculated");
  const { data: settlements = [], isLoading } = useFinalSettlements(offCycle ? run.id : undefined);
  const add = useAddFinalSettlement(run.id);
  const remove = useRemoveFinalSettlement(run.id);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [employeeId, setEmployeeId] = useState("");
  const [leaveDays, setLeaveDays] = useState("0");
  const [noticeMonths, setNoticeMonths] = useState("0");
  // Only fetched while the dialog is open.
  const employees = usePayrollEmployees(dialogOpen ? run.period : "");

  if (!offCycle) {
    return <EmptyState icon={<UserMinus className="h-5 w-5" />} title={t("payroll.run.settlements.empty.title")} description={t("payroll.run.settlements.notOffCycle")} />;
  }

  const number = new Intl.NumberFormat(currentLocale(), { maximumFractionDigits: 2 });
  const settled = new Set(settlements.map((row) => row.employee_id));
  // The server takes only an employee whose exit date is in the run's month, once.
  const leavers = (employees.data ?? []).filter(
    (employee) => employee.termination_date?.slice(0, 7) === run.period.slice(0, 7) && !settled.has(employee.employee_id),
  );

  const openDialog = () => {
    setEmployeeId("");
    setLeaveDays("0");
    setNoticeMonths("0");
    add.reset();
    setDialogOpen(true);
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    add.mutate(
      {
        employee_id: employeeId,
        unused_leave_days: leaveDays.trim() === "" ? 0 : Number(leaveDays),
        notice_months: noticeMonths.trim() === "" ? 0 : Number(noticeMonths),
      },
      {
        onSuccess: () => {
          toast.success(t("payroll.run.settlements.added"));
          setDialogOpen(false);
        },
      },
    );
  };

  const removeSettlement = (row: FinalSettlement) =>
    remove.mutate(row.id, {
      onSuccess: () => toast.success(t("payroll.run.settlements.removed")),
      onError: (error) => toast.error(t("payroll.run.settlements.removeRefused"), { description: errorText(error) }),
    });

  const columns: ColumnDef<FinalSettlement>[] = [
    {
      key: "employee",
      header: t("payroll.run.settlements.column.employee"),
      cell: (row) => (
        <span>
          <span className="font-medium">{row.full_name}</span>
          <span className="ml-1.5 text-xs text-muted-foreground">{row.employee_no}</span>
        </span>
      ),
      defaultWidth: 260,
      sortValue: (row) => row.full_name,
    },
    {
      key: "leaveDays",
      header: t("payroll.run.settlements.column.leaveDays"),
      cell: (row) => number.format(row.unused_leave_days),
      defaultWidth: 180,
      cellClassName: "tabular-nums",
      sortValue: (row) => row.unused_leave_days,
    },
    {
      key: "noticeMonths",
      header: t("payroll.run.settlements.column.noticeMonths"),
      cell: (row) => number.format(row.notice_months),
      defaultWidth: 160,
      cellClassName: "tabular-nums",
      sortValue: (row) => row.notice_months,
    },
    ...(editable
      ? [
          {
            key: "actions",
            header: "",
            alwaysVisible: true,
            defaultWidth: 90,
            cell: (row: FinalSettlement) => (
              <Button
                size="sm"
                variant="ghost"
                className="text-destructive"
                aria-label={t("common.delete")}
                title={t("common.delete")}
                disabled={remove.isPending}
                onClick={(event) => {
                  event.stopPropagation();
                  removeSettlement(row);
                }}
              >
                <Trash2 className="h-4 w-4" />
              </Button>
            ),
          },
        ]
      : []),
  ];

  return (
    <div className="space-y-3">
      <PayrollTable
        tableKey="payroll.run.settlements"
        columns={columns}
        rows={settlements}
        rowKey={(row) => row.id}
        loading={isLoading}
        emptyTitle={t("payroll.run.settlements.empty.title")}
        emptyDescription={t("payroll.run.settlements.empty.description")}
        emptyIcon={<UserMinus className="h-5 w-5" />}
        toolbar={
          editable && (
            <Button size="sm" onClick={openDialog}>
              <Plus className="h-4 w-4" />
              {t("payroll.run.settlements.add")}
            </Button>
          )
        }
      />
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("payroll.run.settlements.add")}</DialogTitle>
            <DialogDescription>{t("payroll.run.settlements.dialogHint")}</DialogDescription>
          </DialogHeader>
          <form className="space-y-4" onSubmit={submit}>
            <div className="space-y-1.5">
              <Label htmlFor="settlement-employee">{t("payroll.run.settlements.column.employee")}</Label>
              <Select id="settlement-employee" required value={employeeId} onChange={(event) => setEmployeeId(event.target.value)} disabled={employees.isLoading}>
                <option value="" disabled>
                  {t("common.select")}
                </option>
                {leavers.map((employee) => (
                  <option key={employee.employee_id} value={employee.employee_id}>
                    {employee.full_name} ({employee.employee_no})
                  </option>
                ))}
              </Select>
              {employees.isSuccess && leavers.length === 0 && <p className="text-xs text-muted-foreground">{t("payroll.run.settlements.noLeaver")}</p>}
            </div>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div className="space-y-1.5">
                <Label htmlFor="settlement-leave-days">{t("payroll.run.settlements.column.leaveDays")}</Label>
                <Input id="settlement-leave-days" type="number" min={0} step="any" value={leaveDays} onChange={(event) => setLeaveDays(event.target.value)} />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="settlement-notice-months">{t("payroll.run.settlements.column.noticeMonths")}</Label>
                <Input id="settlement-notice-months" type="number" min={0} step="any" value={noticeMonths} onChange={(event) => setNoticeMonths(event.target.value)} />
              </div>
            </div>
            {add.isError && <p className="rounded-md border border-destructive/30 bg-destructive-soft px-3 py-2 text-sm text-destructive">{errorText(add.error)}</p>}
            <Button type="submit" className="w-full" disabled={!employeeId || add.isPending}>
              {add.isPending ? t("common.saving") : t("common.save")}
            </Button>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}
