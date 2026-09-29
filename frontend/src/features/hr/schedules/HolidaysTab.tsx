import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarHeart, Pencil, Plus } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../../../lib/auth";
import { useI18n } from "../../../lib/i18n";
import { Button } from "../../../components/ui/button";
import { Input } from "../../../components/ui/input";
import { Label } from "../../../components/ui/label";
import { Checkbox } from "../../../components/ui/checkbox";
import { Badge } from "../../../components/ui/badge";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "../../../components/ui/dialog";
import { FilterTabs } from "../../../components/patterns/FilterTabs";
import { useColumnFilters, type FilterField } from "../../../lib/useColumnFilters";
import type { ColumnDef } from "../../../lib/useTableColumns";
import { HrListTable } from "../HrListTable";
import { HR_KEYS, createHoliday, listHolidays, updateHoliday, type PublicHoliday } from "../presenceApi";
import { errorText, formatDay, todayIso } from "../presenceFormat";

interface HolidayDraft { countryCode: string; date: string; name: string; paid: boolean; confirmed: boolean }
type CheckFilter = "all" | "toConfirm" | "confirmed";

export function HolidaysTab() {
  const { session, hasPermission } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const [year, setYear] = useState(Number(todayIso().slice(0, 4)));
  const holidays = useQuery({ queryKey: [...HR_KEYS.holidays, year], queryFn: () => listHolidays(token, year) });
  const [checkFilter, setCheckFilter] = useState<CheckFilter>("all");
  const [editing, setEditing] = useState<PublicHoliday | null>(null);
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<HolidayDraft>({ countryCode: "", date: "", name: "", paid: true, confirmed: false });
  const [formError, setFormError] = useState<string | null>(null);
  const canEdit = hasPermission("hr.admin_presence");

  const save = useMutation({
    mutationFn: () => {
      const body = { holiday_date: draft.date, name: draft.name.trim(), paid: draft.paid, confirmed: draft.confirmed };
      return editing ? updateHoliday(token, editing.id, body) : createHoliday(token, { ...body, country_code: draft.countryCode.trim().toUpperCase() });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: HR_KEYS.holidays });
      queryClient.invalidateQueries({ queryKey: HR_KEYS.presence });
      setOpen(false);
      toast.success(t(editing ? "hr.holidays.updated" : "hr.holidays.created"));
    },
    onError: (error) => setFormError(errorText(error, t("hr.common.saveError"))),
  });

  function openDialog(holiday: PublicHoliday | null) {
    setEditing(holiday);
    // A new holiday takes the country of the ones already listed; nothing is assumed when there are none.
    const knownCountry = holidays.data?.[0]?.country_code ?? "";
    setDraft(
      holiday
        ? { countryCode: holiday.country_code, date: holiday.holiday_date, name: holiday.name, paid: holiday.paid, confirmed: holiday.confirmed }
        : { countryCode: knownCountry, date: "", name: "", paid: true, confirmed: false },
    );
    setFormError(null);
    setOpen(true);
  }
  function submit() {
    if (!/^[A-Za-z]{2}$/.test(draft.countryCode.trim()) || !draft.date || !draft.name.trim()) {
      setFormError(t("hr.holidays.error.required"));
      return;
    }
    save.mutate();
  }

  const fields: FilterField<PublicHoliday>[] = [
    { key: "name", kind: "text", getValue: (h) => h.name },
    { key: "country", kind: "text", getValue: (h) => h.country_code },
  ];
  const filters = useColumnFilters(fields);
  const rows = filters.apply(
    (holidays.data ?? []).filter((h) => checkFilter === "all" || (checkFilter === "confirmed") === h.confirmed),
  );
  const columns: ColumnDef<PublicHoliday>[] = [
    { key: "date", header: t("hr.holidays.date"), defaultWidth: 150, sortValue: (h) => h.holiday_date, cell: (h) => formatDay(h.holiday_date) },
    {
      key: "name", header: t("hr.holidays.name"), defaultWidth: 300, sortValue: (h) => h.name, cell: (h) => h.name,
      filterCell: { type: "text", placeholder: t("hr.holidays.name"), value: filters.text.name ?? "", onChange: (v) => filters.setTextValue("name", v) },
    },
    {
      key: "country", header: t("hr.holidays.country"), defaultWidth: 90, cell: (h) => h.country_code,
      filterCell: { type: "text", placeholder: t("hr.holidays.country"), value: filters.text.country ?? "", onChange: (v) => filters.setTextValue("country", v) },
    },
    { key: "paid", header: t("hr.holidays.paid"), defaultWidth: 90, cell: (h) => (h.paid ? t("common.yes") : t("common.no")) },
    {
      key: "check", header: t("hr.holidays.status"), defaultWidth: 130,
      cell: (h) => <Badge variant={h.confirmed ? "success" : "warning"}>{t(h.confirmed ? "hr.common.confirmed" : "hr.common.toConfirm")}</Badge>,
    },
    {
      key: "actions", header: "", defaultWidth: 120, alwaysVisible: true,
      cell: (h) =>
        canEdit ? (
          <Button size="sm" variant="outline" onClick={() => openDialog(h)}>
            <Pencil className="h-3.5 w-3.5" />
            {t("common.edit")}
          </Button>
        ) : null,
    },
  ];

  return (
    <>
      <HrListTable
        tableKey="hr.publicHolidays"
        columns={columns}
        rows={rows}
        rowKey={(h) => h.id}
        loading={holidays.isLoading}
        emptyIcon={<CalendarHeart className="h-5 w-5" />}
        emptyTitle={t("hr.holidays.empty.title")}
        emptyDescription={t("hr.holidays.empty.description")}
        filtersActive={filters.isActive}
        onClearFilters={filters.reset}
        toolbar={
          <>
            <Input type="number" className="w-24" aria-label={t("hr.common.year")} value={year} onChange={(e) => setYear(Number(e.target.value) || year)} />
            <FilterTabs
              value={checkFilter}
              onChange={setCheckFilter}
              options={[
                { value: "all", label: t("common.all") },
                { value: "toConfirm", label: t("hr.common.toConfirm") },
                { value: "confirmed", label: t("hr.common.confirmed") },
              ]}
            />
            {hasPermission("hr.manage_presence") && (
              <Button size="sm" onClick={() => openDialog(null)}>
                <Plus className="h-4 w-4" />
                {t("hr.holidays.new")}
              </Button>
            )}
          </>
        }
      />
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t(editing ? "hr.holidays.editTitle" : "hr.holidays.new")}</DialogTitle>
            <DialogDescription>{t("hr.holidays.dialogHelp")}</DialogDescription>
          </DialogHeader>
          <div className="grid grid-cols-[100px_1fr] gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="holiday-country">{t("hr.holidays.country")}</Label>
              <Input id="holiday-country" maxLength={2} disabled={editing !== null} value={draft.countryCode} onChange={(e) => setDraft({ ...draft, countryCode: e.target.value })} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="holiday-date">{t("hr.holidays.date")}</Label>
              <Input id="holiday-date" type="date" value={draft.date} onChange={(e) => setDraft({ ...draft, date: e.target.value })} />
            </div>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="holiday-name">{t("hr.holidays.name")}</Label>
            <Input id="holiday-name" value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
          </div>
          <label className="flex items-center gap-2 text-sm">
            <Checkbox checked={draft.paid} onCheckedChange={(value) => setDraft({ ...draft, paid: value === true })} />
            {t("hr.holidays.paid")}
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
