import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarClock, Pencil, Plus } from "lucide-react";
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
import { HrListTable } from "../HrListTable";
import { HR_KEYS, createLeaveType, listLeaveTypes, updateLeaveType, type LeaveType } from "../presenceApi";
import { errorText } from "../presenceFormat";

interface TypeDraft {
  code: string; nameEn: string; nameFr: string; paid: boolean; accrual: string; maxCarryOver: string;
  countsDays: "calendar" | "working"; requiresDocument: boolean; presenceStatus: "leave" | "sick"; confirmed: boolean;
}
const emptyDraft = (): TypeDraft => ({
  code: "", nameEn: "", nameFr: "", paid: true, accrual: "0", maxCarryOver: "", countsDays: "calendar",
  requiresDocument: false, presenceStatus: "leave", confirmed: false,
});

export function LeaveTypesTab() {
  const { session, hasPermission } = useAuth();
  const { language, t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const types = useQuery({ queryKey: HR_KEYS.leaveTypes, queryFn: () => listLeaveTypes(token) });
  const [activeFilter, setActiveFilter] = useState<"active" | "inactive" | "all">("active");
  const [editing, setEditing] = useState<LeaveType | null>(null);
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<TypeDraft>(emptyDraft);
  const [formError, setFormError] = useState<string | null>(null);
  const canEdit = hasPermission("hr.admin_leave");
  const nameOf = (t2: LeaveType) => (language === "fr" ? t2.name_fr : t2.name_en);

  const save = useMutation({
    mutationFn: () => {
      const accrual = Number(draft.accrual || 0);
      const cap = draft.maxCarryOver.trim() === "" ? null : Number(draft.maxCarryOver);
      const body = {
        name_en: draft.nameEn.trim(), name_fr: draft.nameFr.trim(), paid: draft.paid, accrual_days_per_month: accrual,
        max_carry_over: cap, counts_days: draft.countsDays, requires_document: draft.requiresDocument,
        presence_status: draft.presenceStatus, confirmed: draft.confirmed,
      };
      return editing
        ? updateLeaveType(token, editing.id, { ...body, clear_max_carry_over: cap === null })
        : createLeaveType(token, { code: draft.code.trim(), ...body });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: HR_KEYS.leaveTypes });
      setOpen(false);
      toast.success(t(editing ? "hr.leaveTypes.updated" : "hr.leaveTypes.created"));
    },
    onError: (error) => setFormError(errorText(error, t("hr.common.saveError"))),
  });
  const toggleActive = useMutation({
    mutationFn: (type: LeaveType) => updateLeaveType(token, type.id, { active: !type.active }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: HR_KEYS.leaveTypes }),
    onError: (error) => toast.error(errorText(error, t("hr.common.saveError"))),
  });

  function openDialog(type: LeaveType | null) {
    setEditing(type);
    setDraft(
      type
        ? {
            code: type.code, nameEn: type.name_en, nameFr: type.name_fr, paid: type.paid, accrual: String(type.accrual_days_per_month),
            maxCarryOver: type.max_carry_over === null ? "" : String(type.max_carry_over), countsDays: type.counts_days,
            requiresDocument: type.requires_document, presenceStatus: type.presence_status, confirmed: type.confirmed,
          }
        : emptyDraft(),
    );
    setFormError(null);
    setOpen(true);
  }
  function submit() {
    const accrual = Number(draft.accrual || 0);
    const cap = draft.maxCarryOver.trim() === "" ? 0 : Number(draft.maxCarryOver);
    if (!draft.nameEn.trim() || !draft.nameFr.trim() || (!editing && !draft.code.trim()) || Number.isNaN(accrual) || accrual < 0 || Number.isNaN(cap) || cap < 0) {
      setFormError(t("hr.leaveTypes.error.required"));
      return;
    }
    save.mutate();
  }

  const fields: FilterField<LeaveType>[] = [
    { key: "code", kind: "text", getValue: (r) => r.code },
    { key: "name", kind: "text", getValue: nameOf },
  ];
  const filters = useColumnFilters(fields);
  const rows = filters.apply((types.data ?? []).filter((r) => activeFilter === "all" || (activeFilter === "active") === r.active));

  const columns: ColumnDef<LeaveType>[] = [
    {
      key: "code", header: t("hr.schedules.code"), defaultWidth: 130, sortValue: (r) => r.code, cell: (r) => <span className="font-medium">{r.code}</span>,
      filterCell: { type: "text", placeholder: t("hr.schedules.code"), value: filters.text.code ?? "", onChange: (v) => filters.setTextValue("code", v) },
    },
    {
      key: "name", header: t("hr.schedules.name"), defaultWidth: 220, sortValue: nameOf, cell: nameOf,
      filterCell: { type: "text", placeholder: t("hr.schedules.name"), value: filters.text.name ?? "", onChange: (v) => filters.setTextValue("name", v) },
    },
    { key: "paid", header: t("hr.holidays.paid"), defaultWidth: 90, cell: (r) => (r.paid ? t("common.yes") : t("common.no")) },
    { key: "accrual", header: t("hr.leaveTypes.accrual"), defaultWidth: 150, cellClassName: "tabular-nums", sortValue: (r) => r.accrual_days_per_month, cell: (r) => r.accrual_days_per_month },
    { key: "cap", header: t("hr.leaveTypes.cap"), defaultWidth: 130, cellClassName: "tabular-nums", cell: (r) => r.max_carry_over ?? t("hr.leaveTypes.noCap") },
    { key: "counts", header: t("hr.leaveTypes.counts"), defaultWidth: 130, cell: (r) => t(r.counts_days === "working" ? "hr.leaveTypes.counts.working" : "hr.leaveTypes.counts.calendar") },
    { key: "document", header: t("hr.leaveTypes.document"), defaultWidth: 100, cell: (r) => (r.requires_document ? t("common.yes") : t("common.no")) },
    { key: "check", header: t("hr.holidays.status"), defaultWidth: 130, cell: (r) => <Badge variant={r.confirmed ? "success" : "warning"}>{t(r.confirmed ? "hr.common.confirmed" : "hr.common.toConfirm")}</Badge> },
    {
      key: "actions", header: "", defaultWidth: 200, alwaysVisible: true,
      cell: (r) =>
        canEdit ? (
          <div className="flex justify-end gap-2">
            <Button size="sm" variant="outline" onClick={() => openDialog(r)}>
              <Pencil className="h-3.5 w-3.5" />
              {t("common.edit")}
            </Button>
            <Button size="sm" variant="ghost" onClick={() => toggleActive.mutate(r)}>{r.active ? t("hr.common.deactivate") : t("hr.common.activate")}</Button>
          </div>
        ) : null,
    },
  ];

  return (
    <>
      <HrListTable
        tableKey="hr.leaveTypes"
        columns={columns}
        rows={rows}
        rowKey={(r) => r.id}
        loading={types.isLoading}
        emptyIcon={<CalendarClock className="h-5 w-5" />}
        emptyTitle={t("hr.leaveTypes.empty.title")}
        emptyDescription={t("hr.leaveTypes.empty.description")}
        filtersActive={filters.isActive}
        onClearFilters={filters.reset}
        toolbar={
          <>
            <FilterTabs
              value={activeFilter}
              onChange={setActiveFilter}
              options={[
                { value: "active", label: t("hr.common.activeOnly") },
                { value: "inactive", label: t("hr.common.inactiveOnly") },
                { value: "all", label: t("common.all") },
              ]}
            />
            {hasPermission("hr.manage_leave") && (
              <Button size="sm" onClick={() => openDialog(null)}>
                <Plus className="h-4 w-4" />
                {t("hr.leaveTypes.new")}
              </Button>
            )}
          </>
        }
      />
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-xl">
          <DialogHeader>
            <DialogTitle>{t(editing ? "hr.leaveTypes.editTitle" : "hr.leaveTypes.new")}</DialogTitle>
            <DialogDescription>{t("hr.leaveTypes.dialogHelp")}</DialogDescription>
          </DialogHeader>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="type-code">{t("hr.schedules.code")}</Label>
              <Input id="type-code" disabled={editing !== null} value={draft.code} onChange={(e) => setDraft({ ...draft, code: e.target.value })} />
            </div>
            <div />
            <div className="space-y-1.5">
              <Label htmlFor="type-name-en">{t("hr.leaveTypes.nameEn")}</Label>
              <Input id="type-name-en" value={draft.nameEn} onChange={(e) => setDraft({ ...draft, nameEn: e.target.value })} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="type-name-fr">{t("hr.leaveTypes.nameFr")}</Label>
              <Input id="type-name-fr" value={draft.nameFr} onChange={(e) => setDraft({ ...draft, nameFr: e.target.value })} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="type-accrual">{t("hr.leaveTypes.accrual")}</Label>
              <Input id="type-accrual" type="number" min={0} step="0.01" value={draft.accrual} onChange={(e) => setDraft({ ...draft, accrual: e.target.value })} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="type-cap">{t("hr.leaveTypes.cap")}</Label>
              <Input id="type-cap" type="number" min={0} step="0.01" placeholder={t("hr.leaveTypes.noCap")} value={draft.maxCarryOver} onChange={(e) => setDraft({ ...draft, maxCarryOver: e.target.value })} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="type-counts">{t("hr.leaveTypes.counts")}</Label>
              <Select id="type-counts" value={draft.countsDays} onChange={(e) => setDraft({ ...draft, countsDays: e.target.value as TypeDraft["countsDays"] })}>
                <option value="calendar">{t("hr.leaveTypes.counts.calendar")}</option>
                <option value="working">{t("hr.leaveTypes.counts.working")}</option>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="type-presence">{t("hr.leaveTypes.presenceStatus")}</Label>
              <Select id="type-presence" value={draft.presenceStatus} onChange={(e) => setDraft({ ...draft, presenceStatus: e.target.value as TypeDraft["presenceStatus"] })}>
                <option value="leave">{t("hr.presenceStatus.leave")}</option>
                <option value="sick">{t("hr.presenceStatus.sick")}</option>
              </Select>
            </div>
          </div>
          <label className="flex items-center gap-2 text-sm">
            <Checkbox checked={draft.paid} onCheckedChange={(value) => setDraft({ ...draft, paid: value === true })} />
            {t("hr.leaveTypes.paidLabel")}
          </label>
          <label className="flex items-center gap-2 text-sm">
            <Checkbox checked={draft.requiresDocument} onCheckedChange={(value) => setDraft({ ...draft, requiresDocument: value === true })} />
            {t("hr.leaveTypes.requiresDocumentLabel")}
          </label>
          <label className="flex items-center gap-2 text-sm">
            <Checkbox checked={draft.confirmed} onCheckedChange={(value) => setDraft({ ...draft, confirmed: value === true })} />
            {t("hr.common.confirmed")}
          </label>
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
