import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileUp, Upload } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../../../lib/auth";
import { useI18n, type TranslationKey } from "../../../lib/i18n";
import { AppLoader } from "../../../components/patterns/AppLoader";
import { Button } from "../../../components/ui/button";
import { Input } from "../../../components/ui/input";
import { Label } from "../../../components/ui/label";
import { Select } from "../../../components/ui/select";
import { Badge } from "../../../components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "../../../components/ui/card";
import { FilterTabs } from "../../../components/patterns/FilterTabs";
import { useColumnFilters, type FilterField } from "../../../lib/useColumnFilters";
import type { ColumnDef } from "../../../lib/useTableColumns";
import { HrListTable } from "../HrListTable";
import { useBooted } from "../HrTabsPage";
import { HR_KEYS, listClockImports, listClockProfiles, stageClockImport, type ClockImport, type ClockImportStatus } from "../presenceApi";
import { addDaysIso, errorText, formatDay, monthStartOf, todayIso } from "../presenceFormat";
import { ClockImportReview } from "./ClockImportReview";
import { ClockProfilesCard } from "./ClockProfilesCard";

const STATUS_LABEL: Record<ClockImportStatus, TranslationKey> = {
  staged: "hr.clock.status.staged", committed: "hr.clock.status.committed", discarded: "hr.clock.status.discarded",
};
const STATUS_VARIANT = { staged: "warning", committed: "success", discarded: "default" } as const;

export function ClockImportsPage() {
  const { session, hasPermission } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const profiles = useQuery({ queryKey: HR_KEYS.clockProfiles, queryFn: () => listClockProfiles(token) });
  const imports = useQuery({ queryKey: HR_KEYS.clockImports, queryFn: () => listClockImports(token) });
  const booted = useBooted(!profiles.isLoading && !imports.isLoading);
  const [profileId, setProfileId] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [dateFrom, setDateFrom] = useState(monthStartOf(todayIso()));
  const [dateTo, setDateTo] = useState(addDaysIso(todayIso(), -1));
  const [formError, setFormError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<"all" | ClockImportStatus>("all");

  const stage = useMutation({
    mutationFn: async () => stageClockImport(token, { profile_id: profileId, file_name: file!.name, content: await file!.text(), date_from: dateFrom, date_to: dateTo }),
    onSuccess: (staged) => {
      queryClient.invalidateQueries({ queryKey: HR_KEYS.clockImports });
      setSelected(staged.id);
      setFile(null);
      toast.success(t("hr.clock.upload.staged"));
    },
    onError: (error) => setFormError(errorText(error, t("hr.common.saveError"))),
  });
  function submit() {
    if (!profileId || !file || !dateFrom || !dateTo || dateTo < dateFrom) {
      setFormError(t("hr.clock.upload.error.required"));
      return;
    }
    setFormError(null);
    stage.mutate();
  }

  const fields: FilterField<ClockImport>[] = [
    { key: "file", kind: "text", getValue: (i) => i.file_name },
    { key: "profile", kind: "text", getValue: (i) => i.profile_code },
    { key: "errors", kind: "range", getValue: (i) => i.error_rows },
  ];
  const filters = useColumnFilters(fields);
  const rows = filters.apply((imports.data ?? []).filter((i) => statusFilter === "all" || i.status === statusFilter));
  const columns: ColumnDef<ClockImport>[] = [
    {
      key: "file", header: t("hr.clock.imports.file"), defaultWidth: 220, sortValue: (i) => i.file_name, cell: (i) => <span className="font-medium">{i.file_name}</span>,
      filterCell: { type: "text", placeholder: t("hr.clock.imports.file"), value: filters.text.file ?? "", onChange: (v) => filters.setTextValue("file", v) },
    },
    {
      key: "profile", header: t("hr.clock.imports.profile"), defaultWidth: 120, cell: (i) => i.profile_code,
      filterCell: { type: "text", placeholder: t("hr.clock.imports.profile"), value: filters.text.profile ?? "", onChange: (v) => filters.setTextValue("profile", v) },
    },
    { key: "period", header: t("hr.clock.imports.period"), defaultWidth: 220, sortValue: (i) => i.date_from, cell: (i) => `${formatDay(i.date_from)} → ${formatDay(i.date_to)}` },
    { key: "status", header: t("hr.presence.status"), defaultWidth: 120, cell: (i) => <Badge variant={STATUS_VARIANT[i.status]}>{t(STATUS_LABEL[i.status])}</Badge> },
    { key: "rows", header: t("hr.clock.imports.rows"), defaultWidth: 90, cellClassName: "tabular-nums", sortValue: (i) => i.total_rows, cell: (i) => i.total_rows },
    {
      key: "errors", header: t("hr.clock.imports.errors"), defaultWidth: 110, cellClassName: "tabular-nums", sortValue: (i) => i.error_rows, cell: (i) => i.error_rows,
      filterCell: { type: "range", min: filters.range.errors?.min ?? "", max: filters.range.errors?.max ?? "", onMinChange: (v) => filters.setRangeValue("errors", "min", v), onMaxChange: (v) => filters.setRangeValue("errors", "max", v) },
    },
    { key: "uploaded", header: t("hr.clock.imports.uploaded"), defaultWidth: 200, sortValue: (i) => i.uploaded_at, cell: (i) => `${formatDay(i.uploaded_at.slice(0, 10))} · ${i.uploaded_by_email ?? ""}` },
    {
      key: "actions", header: "", defaultWidth: 120, alwaysVisible: true,
      cell: (i) => <Button size="sm" variant={i.id === selected ? "default" : "outline"} onClick={() => setSelected(i.id)}>{t("hr.clock.imports.review")}</Button>,
    },
  ];

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">{t("hr.clock.title")}</h1>
        <p className="text-sm text-muted-foreground">{t("hr.clock.subtitle")}</p>
      </div>
      {!booted && <AppLoader label={t("hr.clock.loading")} />}
      <div hidden={!booted} className="space-y-4">
        {hasPermission("hr.import_clock") && (
          <Card>
            <CardHeader>
              <CardTitle>{t("hr.clock.upload.title")}</CardTitle>
              <p className="text-sm text-muted-foreground">{t("hr.clock.upload.periodHelp")}</p>
            </CardHeader>
            <CardContent className="flex flex-wrap items-end gap-3">
              <div className="space-y-1.5">
                <Label htmlFor="upload-profile">{t("hr.clock.upload.profile")}</Label>
                <Select id="upload-profile" value={profileId} onChange={(e) => setProfileId(e.target.value)}>
                  <option value="">—</option>
                  {(profiles.data ?? []).filter((p) => p.active).map((p) => (
                    <option key={p.id} value={p.id}>{p.code} · {p.name}</option>
                  ))}
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="upload-file">{t("hr.clock.upload.file")}</Label>
                <Input id="upload-file" type="file" accept=".csv,.txt,text/csv" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="upload-from">{t("hr.common.from")}</Label>
                <Input id="upload-from" type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="upload-to">{t("hr.common.to")}</Label>
                <Input id="upload-to" type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} />
              </div>
              <Button onClick={submit} disabled={stage.isPending}>
                <Upload className="h-4 w-4" />
                {stage.isPending ? t("hr.clock.upload.uploading") : t("hr.clock.upload.submit")}
              </Button>
              {formError && <p className="w-full text-sm text-destructive">{formError}</p>}
            </CardContent>
          </Card>
        )}
        {selected && <ClockImportReview key={selected} importId={selected} onClose={() => setSelected(null)} />}
        <Card>
          <CardHeader>
            <CardTitle>{t("hr.clock.imports.title")}</CardTitle>
          </CardHeader>
          <CardContent>
            <HrListTable
              tableKey="hr.clock.imports"
              columns={columns}
              rows={rows}
              rowKey={(i) => i.id}
              loading={imports.isLoading}
              emptyIcon={<FileUp className="h-5 w-5" />}
              emptyTitle={t("hr.clock.imports.empty.title")}
              emptyDescription={t("hr.clock.imports.empty.description")}
              filtersActive={filters.isActive}
              onClearFilters={filters.reset}
              toolbar={
                <FilterTabs
                  value={statusFilter}
                  onChange={setStatusFilter}
                  options={[
                    { value: "all", label: t("common.all") },
                    { value: "staged", label: t("hr.clock.status.staged") },
                    { value: "committed", label: t("hr.clock.status.committed") },
                    { value: "discarded", label: t("hr.clock.status.discarded") },
                  ]}
                />
              }
            />
          </CardContent>
        </Card>
        <ClockProfilesCard />
      </div>
    </div>
  );
}
