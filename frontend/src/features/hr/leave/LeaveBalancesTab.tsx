import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { PiggyBank, Plus } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../../../lib/auth";
import { useI18n } from "../../../lib/i18n";
import { Button } from "../../../components/ui/button";
import { Input } from "../../../components/ui/input";
import { Label } from "../../../components/ui/label";
import { Select } from "../../../components/ui/select";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "../../../components/ui/dialog";
import { useColumnFilters, type FilterField } from "../../../lib/useColumnFilters";
import type { ColumnDef } from "../../../lib/useTableColumns";
import type { Employee } from "../api";
import { HrListTable } from "../HrListTable";
import { HR_KEYS, adjustLeaveBalance, listLeaveBalances, listLeaveTypes, type LeaveBalance } from "../presenceApi";
import { employeeLabel, errorText, todayIso } from "../presenceFormat";

interface AdjustDraft { employeeId: string; leaveTypeId: string; delta: string; reason: string }
const emptyDraft = (): AdjustDraft => ({ employeeId: "", leaveTypeId: "", delta: "", reason: "" });

export function LeaveBalancesTab({ employees }: { employees: Employee[] }) {
  const { session, hasPermission } = useAuth();
  const { language, t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const [year, setYear] = useState(Number(todayIso().slice(0, 4)));
  const balances = useQuery({ queryKey: [...HR_KEYS.leaveBalances, year], queryFn: () => listLeaveBalances(token, year) });
  const types = useQuery({ queryKey: HR_KEYS.leaveTypes, queryFn: () => listLeaveTypes(token) });
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<AdjustDraft>(emptyDraft);
  const [formError, setFormError] = useState<string | null>(null);
  const canAdjust = hasPermission("hr.admin_leave");

  const adjust = useMutation({
    mutationFn: () => adjustLeaveBalance(token, { employee_id: draft.employeeId, leave_type_id: draft.leaveTypeId, year, delta: Number(draft.delta), reason: draft.reason.trim() }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: HR_KEYS.leaveBalances });
      setOpen(false);
      setDraft(emptyDraft());
      toast.success(t("hr.leaveBalances.adjusted"));
    },
    onError: (error) => setFormError(errorText(error, t("hr.common.saveError"))),
  });
  function submit() {
    const delta = Number(draft.delta);
    if (!draft.employeeId || !draft.leaveTypeId || draft.delta.trim() === "" || Number.isNaN(delta) || delta === 0 || !draft.reason.trim()) {
      setFormError(t("hr.leaveBalances.error.required"));
      return;
    }
    adjust.mutate();
  }

  const trackedTypes = (types.data ?? []).filter((leaveType) => leaveType.accrual_days_per_month > 0 || leaveType.id === draft.leaveTypeId);
  const fields: FilterField<LeaveBalance>[] = [
    { key: "employee", kind: "text", getValue: (b) => `${b.employee_no} ${b.full_name}` },
    { key: "type", kind: "text", getValue: (b) => b.leave_type_code },
    { key: "available", kind: "range", getValue: (b) => b.available },
  ];
  const filters = useColumnFilters(fields);
  const rows = filters.apply((balances.data ?? []).filter((b) => b.tracks_balance));

  const columns: ColumnDef<LeaveBalance>[] = [
    {
      key: "employee", header: t("hr.common.employee"), defaultWidth: 220, sortValue: (b) => b.employee_no, cell: (b) => <span className="font-medium">{b.employee_no} · {b.full_name}</span>,
      filterCell: { type: "text", placeholder: t("hr.common.employee"), value: filters.text.employee ?? "", onChange: (v) => filters.setTextValue("employee", v) },
    },
    {
      key: "type", header: t("hr.leaveRequests.type"), defaultWidth: 140, sortValue: (b) => b.leave_type_code, cell: (b) => b.leave_type_code,
      filterCell: { type: "text", placeholder: t("hr.leaveRequests.type"), value: filters.text.type ?? "", onChange: (v) => filters.setTextValue("type", v) },
    },
    { key: "carried", header: t("hr.leaveBalances.carried"), defaultWidth: 120, cellClassName: "tabular-nums", cell: (b) => b.carried_over },
    { key: "accrued", header: t("hr.leaveBalances.accrued"), defaultWidth: 120, cellClassName: "tabular-nums", cell: (b) => b.accrued },
    { key: "taken", header: t("hr.leaveBalances.taken"), defaultWidth: 120, cellClassName: "tabular-nums", cell: (b) => b.taken },
    { key: "adjusted", header: t("hr.leaveBalances.adjustedColumn"), defaultWidth: 120, cellClassName: "tabular-nums", cell: (b) => b.adjusted },
    {
      key: "available", header: t("hr.leaveBalances.available"), defaultWidth: 130, cellClassName: "tabular-nums font-medium", sortValue: (b) => b.available, cell: (b) => b.available,
      filterCell: { type: "range", min: filters.range.available?.min ?? "", max: filters.range.available?.max ?? "", onMinChange: (v) => filters.setRangeValue("available", "min", v), onMaxChange: (v) => filters.setRangeValue("available", "max", v) },
    },
  ];

  return (
    <>
      <HrListTable
        tableKey="hr.leaveBalances"
        columns={columns}
        rows={rows}
        rowKey={(b) => `${b.employee_id}|${b.leave_type_id}`}
        loading={balances.isLoading}
        emptyIcon={<PiggyBank className="h-5 w-5" />}
        emptyTitle={t("hr.leaveBalances.empty.title")}
        emptyDescription={t("hr.leaveBalances.empty.description")}
        filtersActive={filters.isActive}
        onClearFilters={filters.reset}
        toolbar={
          <>
            <Input type="number" className="w-24" aria-label={t("hr.common.year")} value={year} onChange={(e) => setYear(Number(e.target.value) || year)} />
            {canAdjust && (
              <Button size="sm" onClick={() => { setDraft(emptyDraft()); setFormError(null); setOpen(true); }}>
                <Plus className="h-4 w-4" />
                {t("hr.leaveBalances.adjust")}
              </Button>
            )}
          </>
        }
      />
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("hr.leaveBalances.adjustTitle")}</DialogTitle>
            <DialogDescription>{t("hr.leaveBalances.adjustHelp")}</DialogDescription>
          </DialogHeader>
          <div className="space-y-1.5">
            <Label htmlFor="adjust-employee">{t("hr.common.employee")}</Label>
            <Select id="adjust-employee" value={draft.employeeId} onChange={(e) => setDraft({ ...draft, employeeId: e.target.value })}>
              <option value="">—</option>
              {employees.map((employee) => (
                <option key={employee.id} value={employee.id}>{employeeLabel(employee)}</option>
              ))}
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="adjust-type">{t("hr.leaveRequests.type")}</Label>
            <Select id="adjust-type" value={draft.leaveTypeId} onChange={(e) => setDraft({ ...draft, leaveTypeId: e.target.value })}>
              <option value="">—</option>
              {trackedTypes.map((leaveType) => (
                <option key={leaveType.id} value={leaveType.id}>{leaveType.code} · {language === "fr" ? leaveType.name_fr : leaveType.name_en}</option>
              ))}
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="adjust-delta">{t("hr.leaveBalances.delta")}</Label>
            <Input id="adjust-delta" type="number" step="0.5" value={draft.delta} onChange={(e) => setDraft({ ...draft, delta: e.target.value })} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="adjust-reason">{t("hr.leaveBalances.reason")}</Label>
            <Input id="adjust-reason" value={draft.reason} onChange={(e) => setDraft({ ...draft, reason: e.target.value })} />
          </div>
          {formError && <p className="text-sm text-destructive">{formError}</p>}
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setOpen(false)}>{t("common.cancel")}</Button>
            <Button onClick={submit} disabled={adjust.isPending}>{adjust.isPending ? t("common.saving") : t("common.save")}</Button>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
