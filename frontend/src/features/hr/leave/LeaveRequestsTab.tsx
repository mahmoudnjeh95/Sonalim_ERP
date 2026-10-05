import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarDays, Check, FileWarning, Pencil, Plus, X } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../../../lib/auth";
import { useI18n } from "../../../lib/i18n";
import { Button } from "../../../components/ui/button";
import { Input } from "../../../components/ui/input";
import { Label } from "../../../components/ui/label";
import { Select } from "../../../components/ui/select";
import { Checkbox } from "../../../components/ui/checkbox";
import { Badge } from "../../../components/ui/badge";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "../../../components/ui/dialog";
import { FilterTabs } from "../../../components/patterns/FilterTabs";
import { useColumnFilters, type FilterField } from "../../../lib/useColumnFilters";
import type { ColumnDef } from "../../../lib/useTableColumns";
import type { Employee } from "../api";
import { HrListTable } from "../HrListTable";
import {
  HR_KEYS, decideLeaveRequest, editLeaveRequest, listLeaveTypes, submitLeaveRequest, fetchLeaveRequests,
  type LeaveRecord, type LeaveRequestStatus, type LeaveType,
} from "../presenceApi";
import { employeeLabel, errorText, formatDay, todayIso } from "../presenceFormat";

interface RequestDraft { employeeId: string; leaveTypeId: string; startDate: string; endDate: string; halfDay: boolean; reason: string; documentRef: string }
const emptyDraft = (): RequestDraft => ({ employeeId: "", leaveTypeId: "", startDate: todayIso(), endDate: todayIso(), halfDay: false, reason: "", documentRef: "" });

const STATUS_VARIANT = { pending: "warning", approved: "success", rejected: "destructive", cancelled: "default" } as const;

export function LeaveRequestsTab({ employees }: { employees: Employee[] }) {
  const { session, hasPermission } = useAuth();
  const { language: uiLanguage, t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const requests = useQuery({ queryKey: HR_KEYS.leaveRequests, queryFn: () => fetchLeaveRequests(token) });
  const types = useQuery({ queryKey: HR_KEYS.leaveTypes, queryFn: () => listLeaveTypes(token) });
  const [statusFilter, setStatusFilter] = useState<"all" | LeaveRequestStatus>("pending");
  const [editing, setEditing] = useState<LeaveRecord | null>(null);
  const [assigningType, setAssigningType] = useState<LeaveRecord | null>(null);
  const [pickedType, setPickedType] = useState("");
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<RequestDraft>(emptyDraft);
  const [formError, setFormError] = useState<string | null>(null);
  const canManage = hasPermission("hr.manage_leave");
  const canAdmin = hasPermission("hr.admin_leave");
  const typeName = (r: LeaveRecord) => (r.leave_type_id ? (uiLanguage === "fr" ? r.leave_type_name_fr : r.leave_type_name_en) ?? r.leave_type_code : `${r.legacy_leave_type} (${t("hr.leaveRequests.legacy")})`);

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: HR_KEYS.leaveRequests });
    queryClient.invalidateQueries({ queryKey: HR_KEYS.leaveBalances });
    queryClient.invalidateQueries({ queryKey: HR_KEYS.presence });
  };
  const save = useMutation({
    mutationFn: () => {
      const body = {
        leave_type_id: draft.leaveTypeId, start_date: draft.startDate, end_date: draft.halfDay ? draft.startDate : draft.endDate,
        half_day: draft.halfDay, reason: draft.reason.trim() || null, document_ref: draft.documentRef.trim() || null,
      };
      return editing ? editLeaveRequest(token, editing.id, body) : submitLeaveRequest(token, { ...body, employee_id: draft.employeeId });
    },
    onSuccess: () => {
      refresh();
      setOpen(false);
      toast.success(t(editing ? "hr.leaveRequests.updated" : "hr.leaveRequests.created"));
    },
    onError: (error) => setFormError(errorText(error, t("hr.common.saveError"))),
  });
  const decide = useMutation({
    mutationFn: (input: { id: string; decision: "approve" | "reject" | "cancel" }) => decideLeaveRequest(token, input.id, input.decision),
    onSuccess: (_, input) => {
      refresh();
      toast.success(t(`hr.leaveRequests.decision.${input.decision}` as const));
    },
    onError: (error) => toast.error(errorText(error, t("hr.common.saveError"))),
  });
  const assignType = useMutation({
    mutationFn: () => editLeaveRequest(token, assigningType!.id, { leave_type_id: pickedType, start_date: assigningType!.start_date, end_date: assigningType!.end_date, half_day: false, reason: assigningType!.reason, document_ref: assigningType!.document_ref }),
    onSuccess: () => {
      refresh();
      setAssigningType(null);
      toast.success(t("hr.leaveRequests.typeAssigned"));
    },
    onError: (error) => toast.error(errorText(error, t("hr.common.saveError"))),
  });

  function openDialog(request: LeaveRecord | null) {
    setEditing(request);
    setDraft(
      request
        ? {
            employeeId: request.employee_id, leaveTypeId: request.leave_type_id ?? "", startDate: request.start_date, endDate: request.end_date,
            halfDay: request.half_day, reason: request.reason ?? "", documentRef: request.document_ref ?? "",
          }
        : emptyDraft(),
    );
    setFormError(null);
    setOpen(true);
  }
  function submit() {
    if (!draft.employeeId || !draft.leaveTypeId || !draft.startDate || (!draft.halfDay && draft.endDate < draft.startDate)) {
      setFormError(t("hr.leaveRequests.error.required"));
      return;
    }
    save.mutate();
  }

  const fields: FilterField<LeaveRecord>[] = [
    { key: "employee", kind: "text", getValue: (r) => `${r.employee_no} ${r.full_name}` },
    { key: "type", kind: "text", getValue: typeName },
  ];
  const filters = useColumnFilters(fields);
  const rows = filters.apply((requests.data ?? []).filter((r) => statusFilter === "all" || r.status === statusFilter));
  const activeTypes = (types.data ?? []).filter((r: LeaveType) => r.active || r.id === draft.leaveTypeId);

  const columns: ColumnDef<LeaveRecord>[] = [
    {
      key: "employee", header: t("hr.common.employee"), defaultWidth: 220, sortValue: (r) => r.employee_no, cell: (r) => <span className="font-medium">{r.employee_no} · {r.full_name}</span>,
      filterCell: { type: "text", placeholder: t("hr.common.employee"), value: filters.text.employee ?? "", onChange: (v) => filters.setTextValue("employee", v) },
    },
    {
      key: "type", header: t("hr.leaveRequests.type"), defaultWidth: 180,
      cell: (r) =>
        r.leave_type_id ? typeName(r) : (
          <span className="inline-flex items-center gap-2">
            <Badge variant="warning">{typeName(r)}</Badge>
            {canAdmin && (
              <Button size="sm" variant="outline" onClick={() => { setAssigningType(r); setPickedType(""); }}>
                {t("hr.leaveRequests.assignType")}
              </Button>
            )}
          </span>
        ),
      filterCell: { type: "text", placeholder: t("hr.leaveRequests.type"), value: filters.text.type ?? "", onChange: (v) => filters.setTextValue("type", v) },
    },
    { key: "dates", header: t("hr.leaveRequests.dates"), defaultWidth: 220, sortValue: (r) => r.start_date, cell: (r) => (r.half_day ? `${formatDay(r.start_date)} (${t("hr.leaveRequests.halfDayShort")})` : `${formatDay(r.start_date)} → ${formatDay(r.end_date)}`) },
    { key: "days", header: t("hr.leaveRequests.days"), defaultWidth: 90, cellClassName: "tabular-nums", cell: (r) => r.days ?? "—" },
    { key: "status", header: t("hr.presence.status"), defaultWidth: 130, cell: (r) => <Badge variant={STATUS_VARIANT[r.status]}>{t(`hr.leaveRequests.status.${r.status}` as const)}</Badge> },
    {
      key: "document", header: t("hr.leaveTypes.document"), defaultWidth: 100,
      cell: (r) => (r.document_ref ? <Check className="h-4 w-4 text-success" /> : <FileWarning className="h-4 w-4 text-muted-foreground" />),
    },
    {
      key: "actions", header: "", defaultWidth: 260, alwaysVisible: true,
      cell: (r) => (
        <div className="flex justify-end gap-2">
          {canAdmin && (r.status === "pending" || r.status === "approved") && (
            <Button size="sm" variant="outline" onClick={() => openDialog(r)}>
              <Pencil className="h-3.5 w-3.5" />
              {t("common.edit")}
            </Button>
          )}
          {canManage && r.status === "pending" && (
            <>
              <Button size="sm" onClick={() => decide.mutate({ id: r.id, decision: "approve" })}>
                <Check className="h-3.5 w-3.5" />
                {t("hr.leaveRequests.approve")}
              </Button>
              <Button size="sm" variant="outline" onClick={() => decide.mutate({ id: r.id, decision: "reject" })}>
                <X className="h-3.5 w-3.5" />
                {t("hr.leaveRequests.reject")}
              </Button>
            </>
          )}
          {canManage && r.status === "approved" && (
            <Button size="sm" variant="ghost" onClick={() => decide.mutate({ id: r.id, decision: "cancel" })}>{t("hr.leaveRequests.cancel")}</Button>
          )}
        </div>
      ),
    },
  ];

  return (
    <>
      <HrListTable
        tableKey="hr.leaveRequests"
        columns={columns}
        rows={rows}
        rowKey={(r) => r.id}
        loading={requests.isLoading}
        emptyIcon={<CalendarDays className="h-5 w-5" />}
        emptyTitle={t("hr.leaveRequests.empty.title")}
        emptyDescription={t("hr.leaveRequests.empty.description")}
        filtersActive={filters.isActive}
        onClearFilters={filters.reset}
        toolbar={
          <>
            <FilterTabs
              value={statusFilter}
              onChange={setStatusFilter}
              options={[
                { value: "pending", label: t("hr.leaveRequests.status.pending") },
                { value: "approved", label: t("hr.leaveRequests.status.approved") },
                { value: "rejected", label: t("hr.leaveRequests.status.rejected") },
                { value: "cancelled", label: t("hr.leaveRequests.status.cancelled") },
                { value: "all", label: t("common.all") },
              ]}
            />
            {canManage && (
              <Button size="sm" onClick={() => openDialog(null)}>
                <Plus className="h-4 w-4" />
                {t("hr.leaveRequests.new")}
              </Button>
            )}
          </>
        }
      />
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t(editing ? "hr.leaveRequests.editTitle" : "hr.leaveRequests.new")}</DialogTitle>
            <DialogDescription>{t("hr.leaveRequests.dialogHelp")}</DialogDescription>
          </DialogHeader>
          {!editing && (
            <div className="space-y-1.5">
              <Label htmlFor="request-employee">{t("hr.common.employee")}</Label>
              <Select id="request-employee" value={draft.employeeId} onChange={(e) => setDraft({ ...draft, employeeId: e.target.value })}>
                <option value="">—</option>
                {employees.map((employee) => (
                  <option key={employee.id} value={employee.id}>{employeeLabel(employee)}</option>
                ))}
              </Select>
            </div>
          )}
          <div className="space-y-1.5">
            <Label htmlFor="request-type">{t("hr.leaveRequests.type")}</Label>
            <Select id="request-type" value={draft.leaveTypeId} onChange={(e) => setDraft({ ...draft, leaveTypeId: e.target.value })}>
              <option value="">—</option>
              {activeTypes.map((leaveType) => (
                <option key={leaveType.id} value={leaveType.id}>{uiLanguage === "fr" ? leaveType.name_fr : leaveType.name_en}</option>
              ))}
            </Select>
          </div>
          <label className="flex items-center gap-2 text-sm">
            <Checkbox checked={draft.halfDay} onCheckedChange={(value) => setDraft({ ...draft, halfDay: value === true })} />
            {t("hr.leaveRequests.halfDay")}
          </label>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="request-start">{t("hr.common.from")}</Label>
              <Input id="request-start" type="date" value={draft.startDate} onChange={(e) => setDraft({ ...draft, startDate: e.target.value })} />
            </div>
            {!draft.halfDay && (
              <div className="space-y-1.5">
                <Label htmlFor="request-end">{t("hr.common.to")}</Label>
                <Input id="request-end" type="date" value={draft.endDate} onChange={(e) => setDraft({ ...draft, endDate: e.target.value })} />
              </div>
            )}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="request-reason">{t("hr.leaveRequests.reason")}</Label>
            <Input id="request-reason" value={draft.reason} onChange={(e) => setDraft({ ...draft, reason: e.target.value })} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="request-document">{t("hr.leaveRequests.document")}</Label>
            <Input id="request-document" placeholder={t("hr.leaveRequests.documentPlaceholder")} value={draft.documentRef} onChange={(e) => setDraft({ ...draft, documentRef: e.target.value })} />
          </div>
          {formError && <p className="text-sm text-destructive">{formError}</p>}
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setOpen(false)}>{t("common.cancel")}</Button>
            <Button onClick={submit} disabled={save.isPending}>{save.isPending ? t("common.saving") : t("common.save")}</Button>
          </div>
        </DialogContent>
      </Dialog>
      <Dialog open={assigningType !== null} onOpenChange={(value) => !value && setAssigningType(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("hr.leaveRequests.assignTypeTitle")}</DialogTitle>
            <DialogDescription>{t("hr.leaveRequests.assignTypeHelp")}</DialogDescription>
          </DialogHeader>
          <Select aria-label={t("hr.leaveRequests.type")} value={pickedType} onChange={(e) => setPickedType(e.target.value)}>
            <option value="">—</option>
            {(types.data ?? []).filter((r) => r.active).map((leaveType) => (
              <option key={leaveType.id} value={leaveType.id}>{uiLanguage === "fr" ? leaveType.name_fr : leaveType.name_en}</option>
            ))}
          </Select>
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setAssigningType(null)}>{t("common.cancel")}</Button>
            <Button onClick={() => assignType.mutate()} disabled={!pickedType || assignType.isPending}>{t("common.save")}</Button>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
