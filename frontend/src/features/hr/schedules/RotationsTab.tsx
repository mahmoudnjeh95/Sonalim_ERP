import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Pencil, Plus, Repeat, X } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../../../lib/auth";
import { useI18n } from "../../../lib/i18n";
import { Button } from "../../../components/ui/button";
import { Input } from "../../../components/ui/input";
import { Label } from "../../../components/ui/label";
import { Select } from "../../../components/ui/select";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "../../../components/ui/dialog";
import { FilterTabs } from "../../../components/patterns/FilterTabs";
import { useColumnFilters, type FilterField } from "../../../lib/useColumnFilters";
import type { ColumnDef } from "../../../lib/useTableColumns";
import { HrListTable } from "../HrListTable";
import { HR_KEYS, createRotation, listRotations, listSchedules, updateRotation, type RotationPattern } from "../presenceApi";
import { errorText, formatDay, mondayOf, todayIso, weekdayOf } from "../presenceFormat";

interface RotationDraft { code: string; name: string; anchorDate: string; scheduleIds: string[] }
const emptyDraft = (): RotationDraft => ({ code: "", name: "", anchorDate: mondayOf(todayIso()), scheduleIds: [""] });

export function RotationsTab() {
  const { session, hasPermission } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const rotations = useQuery({ queryKey: HR_KEYS.rotations, queryFn: () => listRotations(token) });
  const schedules = useQuery({ queryKey: HR_KEYS.schedules, queryFn: () => listSchedules(token) });
  const [activeFilter, setActiveFilter] = useState<"active" | "inactive" | "all">("active");
  const [editing, setEditing] = useState<RotationPattern | null>(null);
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<RotationDraft>(emptyDraft);
  const [formError, setFormError] = useState<string | null>(null);
  const canEdit = hasPermission("hr.admin_presence");
  const scheduleCode = (id: string) => schedules.data?.find((s) => s.id === id)?.code ?? "?";

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: HR_KEYS.rotations });
    queryClient.invalidateQueries({ queryKey: HR_KEYS.presence });
  };
  const save = useMutation({
    mutationFn: () => {
      const body = { code: draft.code.trim(), name: draft.name.trim(), anchor_date: draft.anchorDate, schedule_ids: draft.scheduleIds };
      return editing ? updateRotation(token, editing.id, body) : createRotation(token, body);
    },
    onSuccess: () => {
      refresh();
      setOpen(false);
      toast.success(t(editing ? "hr.rotations.updated" : "hr.rotations.created"));
    },
    onError: (error) => setFormError(errorText(error, t("hr.common.saveError"))),
  });
  const toggleActive = useMutation({
    mutationFn: (rotation: RotationPattern) => updateRotation(token, rotation.id, { active: !rotation.active }),
    onSuccess: refresh,
    onError: (error) => toast.error(errorText(error, t("hr.common.saveError"))),
  });

  function openDialog(rotation: RotationPattern | null) {
    setEditing(rotation);
    setDraft(rotation ? { code: rotation.code, name: rotation.name, anchorDate: rotation.anchor_date, scheduleIds: [...rotation.schedule_ids] } : emptyDraft());
    setFormError(null);
    setOpen(true);
  }
  function submit() {
    if (!draft.code.trim() || !draft.name.trim()) {
      setFormError(t("hr.schedules.error.codeName"));
      return;
    }
    if (!draft.anchorDate || weekdayOf(draft.anchorDate) !== 0) {
      setFormError(t("hr.rotations.error.monday"));
      return;
    }
    if (draft.scheduleIds.length === 0 || draft.scheduleIds.some((id) => !id)) {
      setFormError(t("hr.rotations.error.steps"));
      return;
    }
    save.mutate();
  }
  const setStep = (index: number, scheduleId: string) =>
    setDraft((current) => ({ ...current, scheduleIds: current.scheduleIds.map((id, i) => (i === index ? scheduleId : id)) }));

  const fields: FilterField<RotationPattern>[] = [
    { key: "code", kind: "text", getValue: (r) => r.code },
    { key: "name", kind: "text", getValue: (r) => r.name },
    { key: "steps", kind: "text", getValue: (r) => r.schedule_ids.map(scheduleCode).join(" ") },
  ];
  const filters = useColumnFilters(fields);
  const rows = filters.apply((rotations.data ?? []).filter((r) => activeFilter === "all" || (activeFilter === "active") === r.active));

  const columns: ColumnDef<RotationPattern>[] = [
    {
      key: "code", header: t("hr.schedules.code"), defaultWidth: 110, sortValue: (r) => r.code,
      cell: (r) => <span className="font-medium">{r.code}</span>,
      filterCell: { type: "text", placeholder: t("hr.schedules.code"), value: filters.text.code ?? "", onChange: (v) => filters.setTextValue("code", v) },
    },
    {
      key: "name", header: t("hr.schedules.name"), defaultWidth: 220, sortValue: (r) => r.name, cell: (r) => r.name,
      filterCell: { type: "text", placeholder: t("hr.schedules.name"), value: filters.text.name ?? "", onChange: (v) => filters.setTextValue("name", v) },
    },
    { key: "anchor", header: t("hr.rotations.anchor"), defaultWidth: 150, sortValue: (r) => r.anchor_date, cell: (r) => formatDay(r.anchor_date) },
    {
      key: "steps", header: t("hr.rotations.steps"), defaultWidth: 240, cell: (r) => r.schedule_ids.map(scheduleCode).join(" → "),
      filterCell: { type: "text", placeholder: t("hr.rotations.steps"), value: filters.text.steps ?? "", onChange: (v) => filters.setTextValue("steps", v) },
    },
    { key: "active", header: t("hr.common.active"), defaultWidth: 90, cell: (r) => (r.active ? t("common.yes") : t("common.no")) },
    {
      key: "actions", header: "", defaultWidth: 200, alwaysVisible: true,
      cell: (r) =>
        canEdit ? (
          <div className="flex justify-end gap-2">
            <Button size="sm" variant="outline" onClick={() => openDialog(r)}>
              <Pencil className="h-3.5 w-3.5" />
              {t("common.edit")}
            </Button>
            <Button size="sm" variant="ghost" onClick={() => toggleActive.mutate(r)}>
              {r.active ? t("hr.common.deactivate") : t("hr.common.activate")}
            </Button>
          </div>
        ) : null,
    },
  ];

  const activeSchedules = (schedules.data ?? []).filter((s) => s.active || draft.scheduleIds.includes(s.id));
  return (
    <>
      <HrListTable
        tableKey="hr.rotations"
        columns={columns}
        rows={rows}
        rowKey={(r) => r.id}
        loading={rotations.isLoading}
        emptyIcon={<Repeat className="h-5 w-5" />}
        emptyTitle={t("hr.rotations.empty.title")}
        emptyDescription={t("hr.rotations.empty.description")}
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
            {hasPermission("hr.manage_presence") && (
              <Button size="sm" onClick={() => openDialog(null)}>
                <Plus className="h-4 w-4" />
                {t("hr.rotations.new")}
              </Button>
            )}
          </>
        }
      />
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t(editing ? "hr.rotations.editTitle" : "hr.rotations.new")}</DialogTitle>
            <DialogDescription>{t("hr.rotations.dialogHelp")}</DialogDescription>
          </DialogHeader>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="rotation-code">{t("hr.schedules.code")}</Label>
              <Input id="rotation-code" value={draft.code} onChange={(e) => setDraft({ ...draft, code: e.target.value })} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="rotation-name">{t("hr.schedules.name")}</Label>
              <Input id="rotation-name" value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
            </div>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="rotation-anchor">{t("hr.rotations.anchor")}</Label>
            <Input id="rotation-anchor" type="date" value={draft.anchorDate} onChange={(e) => setDraft({ ...draft, anchorDate: e.target.value })} />
          </div>
          <div className="space-y-2">
            {draft.scheduleIds.map((scheduleId, index) => (
              <div key={index} className="flex items-center gap-2">
                <span className="w-24 text-sm text-muted-foreground">{t("hr.rotations.week")} {index + 1}</span>
                <Select value={scheduleId} onChange={(e) => setStep(index, e.target.value)} aria-label={`${t("hr.rotations.week")} ${index + 1}`}>
                  <option value="">{t("hr.rotations.pickSchedule")}</option>
                  {activeSchedules.map((s) => (
                    <option key={s.id} value={s.id}>{s.code} · {s.name}</option>
                  ))}
                </Select>
                <Button
                  size="sm"
                  variant="ghost"
                  aria-label={t("hr.rotations.remove")}
                  disabled={draft.scheduleIds.length === 1}
                  onClick={() => setDraft({ ...draft, scheduleIds: draft.scheduleIds.filter((_, i) => i !== index) })}
                >
                  <X className="h-4 w-4" />
                </Button>
              </div>
            ))}
            <Button size="sm" variant="outline" onClick={() => setDraft({ ...draft, scheduleIds: [...draft.scheduleIds, ""] })}>
              <Plus className="h-4 w-4" />
              {t("hr.rotations.addWeek")}
            </Button>
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
