import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Pencil, Plus, UserCog } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../../../lib/auth";
import { useI18n } from "../../../lib/i18n";
import { Button } from "../../../components/ui/button";
import { Input } from "../../../components/ui/input";
import { Label } from "../../../components/ui/label";
import { Select } from "../../../components/ui/select";
import { Badge } from "../../../components/ui/badge";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "../../../components/ui/dialog";
import { FilterTabs } from "../../../components/patterns/FilterTabs";
import { useColumnFilters, type FilterField } from "../../../lib/useColumnFilters";
import type { ColumnDef } from "../../../lib/useTableColumns";
import { listEmployees } from "../api";
import { HrListTable } from "../HrListTable";
import {
  HR_KEYS, createAssignment, listAssignments, listRotations, listSchedules, updateAssignment, type ScheduleAssignment,
} from "../presenceApi";
import { employeeLabel, errorText, formatDay, todayIso } from "../presenceFormat";

type Kind = "schedule" | "rotation";
interface AssignmentDraft { employeeId: string; kind: Kind; scheduleId: string; rotationId: string; offset: string; validFrom: string; validTo: string }
const emptyDraft = (): AssignmentDraft => ({ employeeId: "", kind: "schedule", scheduleId: "", rotationId: "", offset: "0", validFrom: todayIso(), validTo: "" });

export function AssignmentsTab() {
  const { session, hasPermission } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const assignments = useQuery({ queryKey: HR_KEYS.assignments, queryFn: () => listAssignments(token) });
  const employees = useQuery({ queryKey: HR_KEYS.employees, queryFn: () => listEmployees(token) });
  const schedules = useQuery({ queryKey: HR_KEYS.schedules, queryFn: () => listSchedules(token) });
  const rotations = useQuery({ queryKey: HR_KEYS.rotations, queryFn: () => listRotations(token) });
  const [kindFilter, setKindFilter] = useState<"all" | Kind>("all");
  const [editing, setEditing] = useState<ScheduleAssignment | null>(null);
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<AssignmentDraft>(emptyDraft);
  const [formError, setFormError] = useState<string | null>(null);
  const canEdit = hasPermission("hr.admin_presence");

  const save = useMutation({
    mutationFn: () => {
      const plan = {
        schedule_id: draft.kind === "schedule" ? draft.scheduleId : null,
        rotation_pattern_id: draft.kind === "rotation" ? draft.rotationId : null,
        rotation_offset_weeks: draft.kind === "rotation" ? Number(draft.offset || 0) : 0,
        valid_from: draft.validFrom,
        valid_to: draft.validTo || null,
      };
      return editing
        ? updateAssignment(token, editing.id, { ...plan, clear_valid_to: !draft.validTo })
        : createAssignment(token, { ...plan, employee_id: draft.employeeId });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: HR_KEYS.assignments });
      queryClient.invalidateQueries({ queryKey: HR_KEYS.presence });
      setOpen(false);
      toast.success(t(editing ? "hr.assignments.updated" : "hr.assignments.created"));
    },
    onError: (error) => setFormError(errorText(error, t("hr.common.saveError"))),
  });

  function openDialog(assignment: ScheduleAssignment | null) {
    setEditing(assignment);
    setDraft(
      assignment
        ? {
            employeeId: assignment.employee_id,
            kind: assignment.rotation_pattern_id ? "rotation" : "schedule",
            scheduleId: assignment.schedule_id ?? "",
            rotationId: assignment.rotation_pattern_id ?? "",
            offset: String(assignment.rotation_offset_weeks),
            validFrom: assignment.valid_from,
            validTo: assignment.valid_to ?? "",
          }
        : emptyDraft(),
    );
    setFormError(null);
    setOpen(true);
  }
  function submit() {
    const target = draft.kind === "schedule" ? draft.scheduleId : draft.rotationId;
    const offset = Number(draft.offset || 0);
    if (!draft.employeeId || !target || !draft.validFrom || !Number.isInteger(offset) || offset < 0) {
      setFormError(t("hr.assignments.error.required"));
      return;
    }
    save.mutate();
  }

  const planOf = (a: ScheduleAssignment) => a.schedule_code ?? a.rotation_code ?? "?";
  const fields: FilterField<ScheduleAssignment>[] = [
    { key: "employee", kind: "text", getValue: (a) => `${a.employee_no} ${a.full_name}` },
    { key: "plan", kind: "text", getValue: planOf },
    { key: "offset", kind: "range", getValue: (a) => a.rotation_offset_weeks },
  ];
  const filters = useColumnFilters(fields);
  const rows = filters.apply(
    (assignments.data ?? []).filter((a) => kindFilter === "all" || (kindFilter === "rotation") === (a.rotation_pattern_id !== null)),
  );

  const columns: ColumnDef<ScheduleAssignment>[] = [
    {
      key: "employee", header: t("hr.common.employee"), defaultWidth: 240, sortValue: (a) => a.employee_no,
      cell: (a) => <span className="font-medium">{a.employee_no} · {a.full_name}</span>,
      filterCell: { type: "text", placeholder: t("hr.common.employee"), value: filters.text.employee ?? "", onChange: (v) => filters.setTextValue("employee", v) },
    },
    {
      key: "plan", header: t("hr.assignments.plan"), defaultWidth: 200, sortValue: planOf,
      cell: (a) => (
        <span className="inline-flex items-center gap-2">
          {planOf(a)}
          <Badge variant={a.rotation_pattern_id ? "accent" : "default"}>
            {t(a.rotation_pattern_id ? "hr.assignments.kind.rotation" : "hr.assignments.kind.schedule")}
          </Badge>
        </span>
      ),
      filterCell: { type: "text", placeholder: t("hr.assignments.plan"), value: filters.text.plan ?? "", onChange: (v) => filters.setTextValue("plan", v) },
    },
    {
      key: "offset", header: t("hr.assignments.offset"), defaultWidth: 150, cellClassName: "tabular-nums", sortValue: (a) => a.rotation_offset_weeks,
      cell: (a) => (a.rotation_pattern_id ? a.rotation_offset_weeks : "—"),
      filterCell: {
        type: "range", min: filters.range.offset?.min ?? "", max: filters.range.offset?.max ?? "",
        onMinChange: (v) => filters.setRangeValue("offset", "min", v), onMaxChange: (v) => filters.setRangeValue("offset", "max", v),
      },
    },
    { key: "from", header: t("hr.common.from"), defaultWidth: 140, sortValue: (a) => a.valid_from, cell: (a) => formatDay(a.valid_from) },
    { key: "to", header: t("hr.common.to"), defaultWidth: 140, sortValue: (a) => a.valid_to ?? "9999", cell: (a) => (a.valid_to ? formatDay(a.valid_to) : t("hr.assignments.openEnded")) },
    {
      key: "actions", header: "", defaultWidth: 120, alwaysVisible: true,
      cell: (a) =>
        canEdit ? (
          <Button size="sm" variant="outline" onClick={() => openDialog(a)}>
            <Pencil className="h-3.5 w-3.5" />
            {t("common.edit")}
          </Button>
        ) : null,
    },
  ];

  return (
    <>
      <HrListTable
        tableKey="hr.scheduleAssignments"
        columns={columns}
        rows={rows}
        rowKey={(a) => a.id}
        loading={assignments.isLoading}
        emptyIcon={<UserCog className="h-5 w-5" />}
        emptyTitle={t("hr.assignments.empty.title")}
        emptyDescription={t("hr.assignments.empty.description")}
        filtersActive={filters.isActive}
        onClearFilters={filters.reset}
        toolbar={
          <>
            <FilterTabs
              value={kindFilter}
              onChange={setKindFilter}
              options={[
                { value: "all", label: t("common.all") },
                { value: "schedule", label: t("hr.assignments.kind.schedule") },
                { value: "rotation", label: t("hr.assignments.kind.rotation") },
              ]}
            />
            {hasPermission("hr.manage_presence") && (
              <Button size="sm" onClick={() => openDialog(null)}>
                <Plus className="h-4 w-4" />
                {t("hr.assignments.new")}
              </Button>
            )}
          </>
        }
      />
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t(editing ? "hr.assignments.editTitle" : "hr.assignments.new")}</DialogTitle>
            <DialogDescription>{t("hr.assignments.dialogHelp")}</DialogDescription>
          </DialogHeader>
          <div className="space-y-1.5">
            <Label htmlFor="assignment-employee">{t("hr.common.employee")}</Label>
            <Select id="assignment-employee" value={draft.employeeId} disabled={editing !== null} onChange={(e) => setDraft({ ...draft, employeeId: e.target.value })}>
              <option value="">—</option>
              {(employees.data ?? []).map((employee) => (
                <option key={employee.id} value={employee.id}>{employeeLabel(employee)}</option>
              ))}
            </Select>
          </div>
          <FilterTabs
            value={draft.kind}
            onChange={(kind) => setDraft({ ...draft, kind })}
            options={[
              { value: "schedule", label: t("hr.assignments.kind.schedule") },
              { value: "rotation", label: t("hr.assignments.kind.rotation") },
            ]}
          />
          {draft.kind === "schedule" ? (
            <Select value={draft.scheduleId} aria-label={t("hr.assignments.kind.schedule")} onChange={(e) => setDraft({ ...draft, scheduleId: e.target.value })}>
              <option value="">{t("hr.rotations.pickSchedule")}</option>
              {(schedules.data ?? []).filter((s) => s.active || s.id === draft.scheduleId).map((s) => (
                <option key={s.id} value={s.id}>{s.code} · {s.name}</option>
              ))}
            </Select>
          ) : (
            <div className="grid grid-cols-2 gap-3">
              <Select value={draft.rotationId} aria-label={t("hr.assignments.kind.rotation")} onChange={(e) => setDraft({ ...draft, rotationId: e.target.value })}>
                <option value="">—</option>
                {(rotations.data ?? []).filter((r) => r.active || r.id === draft.rotationId).map((r) => (
                  <option key={r.id} value={r.id}>{r.code} · {r.name}</option>
                ))}
              </Select>
              <div className="space-y-1.5">
                <Label htmlFor="assignment-offset">{t("hr.assignments.offset")}</Label>
                <Input id="assignment-offset" type="number" min={0} value={draft.offset} onChange={(e) => setDraft({ ...draft, offset: e.target.value })} />
              </div>
            </div>
          )}
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="assignment-from">{t("hr.common.from")}</Label>
              <Input id="assignment-from" type="date" value={draft.validFrom} onChange={(e) => setDraft({ ...draft, validFrom: e.target.value })} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="assignment-to">{t("hr.common.to")}</Label>
              <Input id="assignment-to" type="date" value={draft.validTo} onChange={(e) => setDraft({ ...draft, validTo: e.target.value })} />
            </div>
          </div>
          {formError && <p className="text-sm text-destructive">{formError}</p>}
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setOpen(false)}>{t("common.cancel")}</Button>
            <Button onClick={submit} disabled={save.isPending}>{save.isPending ? t("common.saving") : t("common.save")}</Button>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
