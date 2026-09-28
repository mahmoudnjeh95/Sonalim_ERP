import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Fingerprint, Pencil, Plus } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../../../lib/auth";
import { useI18n } from "../../../lib/i18n";
import { Button } from "../../../components/ui/button";
import { Input } from "../../../components/ui/input";
import { Label } from "../../../components/ui/label";
import { Select } from "../../../components/ui/select";
import { Checkbox } from "../../../components/ui/checkbox";
import { Card, CardContent, CardHeader, CardTitle } from "../../../components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "../../../components/ui/dialog";
import { FilterTabs } from "../../../components/patterns/FilterTabs";
import { useColumnFilters, type FilterField } from "../../../lib/useColumnFilters";
import type { ColumnDef } from "../../../lib/useTableColumns";
import { HrListTable } from "../HrListTable";
import { HR_KEYS, createClockProfile, listClockProfiles, updateClockProfile, type ClockProfile, type ClockProfileInput } from "../presenceApi";
import { errorText } from "../presenceFormat";

interface ProfileDraft {
  code: string; name: string; delimiter: string; hasHeader: boolean; badgeColumn: string; timestampColumn: string;
  timeColumn: string; timestampFormat: string; directionColumn: string; inValues: string; outValues: string;
}
const DELIMITERS = [";", ",", "\t", "|"];
const emptyDraft = (): ProfileDraft => ({
  code: "", name: "", delimiter: ";", hasHeader: true, badgeColumn: "", timestampColumn: "", timeColumn: "",
  timestampFormat: "", directionColumn: "", inValues: "", outValues: "",
});
const splitValues = (text: string) => text.split(",").map((value) => value.trim()).filter(Boolean);

function toInput(draft: ProfileDraft): ClockProfileInput {
  return {
    code: draft.code.trim(), name: draft.name.trim(), delimiter: draft.delimiter, has_header: draft.hasHeader,
    badge_column: draft.badgeColumn.trim(), timestamp_column: draft.timestampColumn.trim(), time_column: draft.timeColumn.trim() || null,
    timestamp_format: draft.timestampFormat.trim(), direction_column: draft.directionColumn.trim() || null,
    in_values: splitValues(draft.inValues), out_values: splitValues(draft.outValues),
  };
}

export function ClockProfilesCard() {
  const { session, hasPermission } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const profiles = useQuery({ queryKey: HR_KEYS.clockProfiles, queryFn: () => listClockProfiles(token) });
  const [activeFilter, setActiveFilter] = useState<"active" | "inactive" | "all">("active");
  const [editing, setEditing] = useState<ClockProfile | null>(null);
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<ProfileDraft>(emptyDraft);
  const [formError, setFormError] = useState<string | null>(null);
  const canEdit = hasPermission("hr.admin_presence");

  const save = useMutation({
    mutationFn: () => {
      const input = toInput(draft);
      if (!editing) return createClockProfile(token, input);
      const { code: _code, ...changes } = input;
      // An empty optional column is sent as "" so the server clears it.
      return updateClockProfile(token, editing.id, { ...changes, time_column: changes.time_column ?? "", direction_column: changes.direction_column ?? "" });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: HR_KEYS.clockProfiles });
      setOpen(false);
      toast.success(t(editing ? "hr.clock.profiles.updated" : "hr.clock.profiles.created"));
    },
    onError: (error) => setFormError(errorText(error, t("hr.common.saveError"))),
  });
  const toggleActive = useMutation({
    mutationFn: (profile: ClockProfile) => updateClockProfile(token, profile.id, { active: !profile.active }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: HR_KEYS.clockProfiles }),
    onError: (error) => toast.error(errorText(error, t("hr.common.saveError"))),
  });

  function openDialog(profile: ClockProfile | null) {
    setEditing(profile);
    setDraft(
      profile
        ? {
            code: profile.code, name: profile.name, delimiter: profile.delimiter, hasHeader: profile.has_header,
            badgeColumn: profile.badge_column, timestampColumn: profile.timestamp_column, timeColumn: profile.time_column ?? "",
            timestampFormat: profile.timestamp_format, directionColumn: profile.direction_column ?? "",
            inValues: profile.in_values.join(", "), outValues: profile.out_values.join(", "),
          }
        : emptyDraft(),
    );
    setFormError(null);
    setOpen(true);
  }
  function submit() {
    if (!draft.code.trim() || !draft.name.trim() || !draft.badgeColumn.trim() || !draft.timestampColumn.trim() || !draft.timestampFormat.includes("%")) {
      setFormError(t("hr.clock.profiles.error.required"));
      return;
    }
    save.mutate();
  }

  const fields: FilterField<ClockProfile>[] = [
    { key: "code", kind: "text", getValue: (p) => p.code },
    { key: "name", kind: "text", getValue: (p) => p.name },
  ];
  const filters = useColumnFilters(fields);
  const rows = filters.apply((profiles.data ?? []).filter((p) => activeFilter === "all" || (activeFilter === "active") === p.active));
  const delimiterLabel = (value: string) => (value === "\t" ? t("hr.clock.profiles.tab") : value);
  const columns: ColumnDef<ClockProfile>[] = [
    {
      key: "code", header: t("hr.schedules.code"), defaultWidth: 110, sortValue: (p) => p.code, cell: (p) => <span className="font-medium">{p.code}</span>,
      filterCell: { type: "text", placeholder: t("hr.schedules.code"), value: filters.text.code ?? "", onChange: (v) => filters.setTextValue("code", v) },
    },
    {
      key: "name", header: t("hr.schedules.name"), defaultWidth: 200, sortValue: (p) => p.name, cell: (p) => p.name,
      filterCell: { type: "text", placeholder: t("hr.schedules.name"), value: filters.text.name ?? "", onChange: (v) => filters.setTextValue("name", v) },
    },
    { key: "delimiter", header: t("hr.clock.profiles.delimiter"), defaultWidth: 100, cell: (p) => <code>{delimiterLabel(p.delimiter)}</code> },
    {
      key: "columns", header: t("hr.clock.profiles.columns"), defaultWidth: 280,
      cell: (p) => <code className="text-xs">{[p.badge_column, p.timestamp_column, p.time_column, p.direction_column].filter(Boolean).join(" · ")}</code>,
    },
    { key: "format", header: t("hr.clock.profiles.format"), defaultWidth: 160, cell: (p) => <code className="text-xs">{p.timestamp_format}</code> },
    {
      key: "actions", header: "", defaultWidth: 200, alwaysVisible: true,
      cell: (p) =>
        canEdit ? (
          <div className="flex justify-end gap-2">
            <Button size="sm" variant="outline" onClick={() => openDialog(p)}>
              <Pencil className="h-3.5 w-3.5" />
              {t("common.edit")}
            </Button>
            <Button size="sm" variant="ghost" onClick={() => toggleActive.mutate(p)}>
              {p.active ? t("hr.common.deactivate") : t("hr.common.activate")}
            </Button>
          </div>
        ) : null,
    },
  ];

  const text = (id: string, label: string, key: keyof ProfileDraft, placeholder = "") => (
    <div className="space-y-1.5">
      <Label htmlFor={id}>{label}</Label>
      <Input id={id} placeholder={placeholder} value={String(draft[key])} onChange={(e) => setDraft({ ...draft, [key]: e.target.value } as ProfileDraft)} />
    </div>
  );
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("hr.clock.profiles.title")}</CardTitle>
        <p className="text-sm text-muted-foreground">{t("hr.clock.profiles.help")}</p>
      </CardHeader>
      <CardContent>
        <HrListTable
          tableKey="hr.clock.profiles"
          columns={columns}
          rows={rows}
          rowKey={(p) => p.id}
          loading={profiles.isLoading}
          emptyIcon={<Fingerprint className="h-5 w-5" />}
          emptyTitle={t("hr.clock.profiles.empty.title")}
          emptyDescription={t("hr.clock.profiles.empty.description")}
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
              {hasPermission("hr.import_clock") && (
                <Button size="sm" onClick={() => openDialog(null)}>
                  <Plus className="h-4 w-4" />
                  {t("hr.clock.profiles.new")}
                </Button>
              )}
            </>
          }
        />
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogContent className="max-w-2xl">
            <DialogHeader>
              <DialogTitle>{t(editing ? "hr.clock.profiles.editTitle" : "hr.clock.profiles.new")}</DialogTitle>
              <DialogDescription>{t("hr.clock.profiles.columnsHelp")}</DialogDescription>
            </DialogHeader>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label htmlFor="profile-code">{t("hr.schedules.code")}</Label>
                <Input id="profile-code" disabled={editing !== null} value={draft.code} onChange={(e) => setDraft({ ...draft, code: e.target.value })} />
              </div>
              {text("profile-name", t("hr.schedules.name"), "name")}
              <div className="space-y-1.5">
                <Label htmlFor="profile-delimiter">{t("hr.clock.profiles.delimiter")}</Label>
                <Select id="profile-delimiter" value={draft.delimiter} onChange={(e) => setDraft({ ...draft, delimiter: e.target.value })}>
                  {DELIMITERS.map((value) => (
                    <option key={value} value={value}>{delimiterLabel(value)}</option>
                  ))}
                </Select>
              </div>
              <label className="flex items-center gap-2 self-end pb-2 text-sm">
                <Checkbox checked={draft.hasHeader} onCheckedChange={(value) => setDraft({ ...draft, hasHeader: value === true })} />
                {t("hr.clock.profiles.hasHeader")}
              </label>
              {text("profile-badge", t("hr.clock.profiles.badgeColumn"), "badgeColumn")}
              {text("profile-timestamp", t("hr.clock.profiles.timestampColumn"), "timestampColumn")}
              {text("profile-time", t("hr.clock.profiles.timeColumn"), "timeColumn")}
              {text("profile-format", t("hr.clock.profiles.format"), "timestampFormat", "%d/%m/%Y %H:%M")}
              {text("profile-direction", t("hr.clock.profiles.directionColumn"), "directionColumn")}
              <span />
              {text("profile-in", t("hr.clock.profiles.inValues"), "inValues")}
              {text("profile-out", t("hr.clock.profiles.outValues"), "outValues")}
            </div>
            <p className="text-xs text-muted-foreground">{t("hr.clock.profiles.formatHelp")}</p>
            {formError && <p className="text-sm text-destructive">{formError}</p>}
            <div className="flex justify-end gap-2">
              <Button variant="ghost" onClick={() => setOpen(false)}>{t("common.cancel")}</Button>
              <Button onClick={submit} disabled={save.isPending}>{save.isPending ? t("common.saving") : t("common.save")}</Button>
            </div>
          </DialogContent>
        </Dialog>
      </CardContent>
    </Card>
  );
}
