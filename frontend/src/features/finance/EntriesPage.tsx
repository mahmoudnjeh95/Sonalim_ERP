import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useFieldArray, useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BookOpen, Pencil, Plus, RotateCcw, Send, Trash2, TriangleAlert } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../../lib/auth";
import { useI18n, type TranslationKey } from "../../lib/i18n";
import { useColumnFilters, type FilterField } from "../../lib/useColumnFilters";
import type { ColumnDef } from "../../lib/useTableColumns";
import { Button } from "../../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "../../components/ui/dialog";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Select } from "../../components/ui/select";
import { Skeleton } from "../../components/ui/skeleton";
import { DateRangeFilter } from "../../components/patterns/DateRangeFilter";
import { FilterTabs } from "../../components/patterns/FilterTabs";
import { EntryStatusBadge, LedgerTable, rangeFilter, textFilter } from "./LedgerTable";
import { errorText, formatAmount, formatAmountCell, formatDate, monthEndIso, monthStartIso, todayIso } from "./ledgerFormat";
import {
  LEDGER_KEYS,
  createEntry,
  deleteEntry,
  getEntry,
  invalidateLedgerData,
  listAccounts,
  listEntries,
  listJournals,
  listPostingFailures,
  postEntry,
  retryPostingFailure,
  reverseEntry,
  updateEntry,
  type EntryFilters,
  type EntryInput,
  type EntryStatus,
  type Journal,
  type JournalEntry,
  type JournalEntryDetail,
  type PostingFailure,
} from "./ledgerApi";

export const FAILURE_KIND_KEYS: Record<string, TranslationKey> = {
  payroll_run: "finance.failures.kind.payroll_run",
  payroll_payment: "finance.failures.kind.payroll_payment",
  payroll_reversal: "finance.failures.kind.payroll_reversal",
  invoice_issued: "finance.failures.kind.invoice_issued",
  invoice_paid: "finance.failures.kind.invoice_paid",
};

/** The refusal in the language the user picked (French falls back to English if none was stored). */
export function failureMessage(failure: PostingFailure, language: string): string {
  return language === "fr" && failure.error_message_fr ? failure.error_message_fr : failure.error_message;
}

type StatusFilter = "all" | EntryStatus;

export function EntriesPage() {
  const { session, hasPermission } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const [searchParams, setSearchParams] = useSearchParams();
  const defaultRange = { from: monthStartIso(), to: monthEndIso() };
  const [range, setRange] = useState(defaultRange);
  const [journalCode, setJournalCode] = useState("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [formEntry, setFormEntry] = useState<JournalEntryDetail | "new" | null>(null);
  const openEntryId = searchParams.get("entry");
  const filters: EntryFilters = { date_from: range.from, date_to: range.to, journal_code: journalCode || undefined };
  const { data: entries = [], isLoading } = useQuery({
    queryKey: LEDGER_KEYS.entryList(filters),
    queryFn: () => listEntries(token, filters),
  });
  const { data: journals = [] } = useQuery({ queryKey: LEDGER_KEYS.journals, queryFn: () => listJournals(token) });

  const openEntry = (id: string | null) => {
    const next = new URLSearchParams(searchParams);
    if (id) next.set("entry", id);
    else next.delete("entry");
    setSearchParams(next, { replace: true });
  };

  const fields: FilterField<JournalEntry>[] = [
    { key: "number", kind: "text", getValue: (entry) => entry.number ?? "" },
    { key: "label", kind: "text", getValue: (entry) => entry.label },
    { key: "reference", kind: "text", getValue: (entry) => entry.reference ?? "" },
    { key: "total_debit", kind: "range", getValue: (entry) => entry.total_debit },
  ];
  const columnFilters = useColumnFilters(fields);
  const rows = columnFilters.apply(statusFilter === "all" ? entries : entries.filter((entry) => entry.status === statusFilter));
  const total = rows.reduce((sum, entry) => sum + entry.total_debit, 0);

  const columns: ColumnDef<JournalEntry>[] = [
    {
      key: "entry_date",
      header: t("finance.entries.column.date"),
      defaultWidth: 110,
      cell: (entry) => formatDate(entry.entry_date),
      sortValue: (entry) => entry.entry_date,
    },
    {
      key: "number",
      header: t("finance.entries.column.number"),
      defaultWidth: 170,
      cell: (entry) => <span className="font-mono">{entry.number ?? "—"}</span>,
      filterCell: textFilter(columnFilters, "number", t("finance.entries.column.number")),
      sortValue: (entry) => entry.number ?? "",
    },
    {
      key: "journal_code",
      header: t("finance.entries.column.journal"),
      defaultWidth: 90,
      cell: (entry) => <span className="font-mono">{entry.journal_code}</span>,
      sortValue: (entry) => entry.journal_code,
    },
    {
      key: "label",
      header: t("finance.entries.column.label"),
      defaultWidth: 280,
      cell: (entry) => entry.label,
      filterCell: textFilter(columnFilters, "label", t("finance.entries.column.label")),
      sortValue: (entry) => entry.label,
    },
    {
      key: "reference",
      header: t("finance.entries.column.reference"),
      defaultWidth: 150,
      cell: (entry) => <span className="text-muted-foreground">{entry.reference ?? ""}</span>,
      filterCell: textFilter(columnFilters, "reference", t("finance.entries.column.reference")),
      sortValue: (entry) => entry.reference ?? "",
    },
    {
      key: "status",
      header: t("finance.entries.column.status"),
      defaultWidth: 130,
      cell: (entry) => <EntryStatusBadge status={entry.status} />,
      sortValue: (entry) => entry.status,
    },
    {
      key: "total_debit",
      header: t("finance.entries.column.amount"),
      defaultWidth: 150,
      headerClassName: "text-right",
      cellClassName: "text-right tabular-nums",
      cell: (entry) => formatAmount(entry.total_debit),
      filterCell: rangeFilter(columnFilters, "total_debit"),
      sortValue: (entry) => entry.total_debit,
    },
  ];

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">{t("finance.entries.title")}</h1>
          <p className="text-sm text-muted-foreground">{t("finance.entries.subtitle")}</p>
        </div>
        {hasPermission("finance.manage_entries") && (
          <Button onClick={() => setFormEntry("new")}>
            <Plus className="h-4 w-4" />
            {t("finance.entries.new")}
          </Button>
        )}
      </div>
      <PostingFailuresCard />
      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center gap-3">
            <CardTitle>{t("finance.entries.tableTitle")}</CardTitle>
            <DateRangeFilter
              from={range.from}
              to={range.to}
              onChange={setRange}
              onReset={() => setRange(defaultRange)}
              isDefault={range.from === defaultRange.from && range.to === defaultRange.to}
            />
            <div className="w-56">
              <Select value={journalCode} onChange={(event) => setJournalCode(event.target.value)} aria-label={t("finance.entries.column.journal")}>
                <option value="">{t("finance.entries.allJournals")}</option>
                {journals.map((journal) => (
                  <option key={journal.code} value={journal.code}>
                    {journal.code} · {journal.name}
                  </option>
                ))}
              </Select>
            </div>
          </div>
        </CardHeader>
        <CardContent className="p-0 pb-2">
          <LedgerTable
            tableKey="finance.entries"
            columns={columns}
            rows={rows}
            rowKey={(entry) => entry.id}
            isLoading={isLoading}
            emptyIcon={<BookOpen className="h-5 w-5" />}
            emptyTitle={t("finance.entries.emptyTitle")}
            emptyDescription={t("finance.entries.emptyDescription")}
            onRowClick={(entry) => openEntry(entry.id)}
            footer={(key) => (key === "label" ? t("finance.entries.total") : key === "total_debit" ? formatAmount(total) : "")}
            toolbar={
              <>
                <FilterTabs
                  value={statusFilter}
                  onChange={setStatusFilter}
                  options={[
                    { value: "all", label: t("common.all") },
                    { value: "draft", label: t("finance.entries.status.draft") },
                    { value: "posted", label: t("finance.entries.status.posted") },
                    { value: "reversed", label: t("finance.entries.status.reversed") },
                  ]}
                />
                {columnFilters.isActive && (
                  <Button variant="ghost" size="sm" onClick={columnFilters.reset}>
                    {t("common.clearFilters")}
                  </Button>
                )}
              </>
            }
          />
        </CardContent>
      </Card>
      {openEntryId && (
        <EntryDetailDialog
          entryId={openEntryId}
          onClose={() => openEntry(null)}
          onEdit={(entry) => {
            openEntry(null);
            setFormEntry(entry);
          }}
        />
      )}
      {formEntry !== null && (
        <EntryFormDialog entry={formEntry === "new" ? null : formEntry} journals={journals} onClose={() => setFormEntry(null)} />
      )}
    </div>
  );
}

function PostingFailuresCard() {
  const { session, hasPermission } = useAuth();
  const { t, language } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const [moduleFilter, setModuleFilter] = useState<"all" | "payroll" | "finance">("all");
  const { data: failures = [], isLoading } = useQuery({ queryKey: LEDGER_KEYS.failures, queryFn: () => listPostingFailures(token) });
  const retryMutation = useMutation({
    mutationFn: (id: string) => retryPostingFailure(token, id),
    onSuccess: () => {
      invalidateLedgerData(queryClient);
      toast.success(t("finance.failures.retried"));
    },
    onError: (error) => toast.error(t("finance.failures.retryError"), { description: errorText(error) }),
  });
  const fields: FilterField<PostingFailure>[] = [
    { key: "source_id", kind: "text", getValue: (failure) => failure.source_id },
    { key: "message", kind: "text", getValue: (failure) => failureMessage(failure, language) },
  ];
  const columnFilters = useColumnFilters(fields);
  const rows = columnFilters.apply(
    moduleFilter === "all" ? failures : failures.filter((failure) => failure.source_module === moduleFilter),
  );
  const columns: ColumnDef<PostingFailure>[] = [
    {
      key: "failed_at",
      header: t("finance.failures.column.failedAt"),
      defaultWidth: 110,
      cell: (failure) => formatDate(failure.failed_at),
      sortValue: (failure) => failure.failed_at,
    },
    {
      key: "source_kind",
      header: t("finance.failures.column.kind"),
      defaultWidth: 170,
      cell: (failure) => (FAILURE_KIND_KEYS[failure.source_kind] ? t(FAILURE_KIND_KEYS[failure.source_kind]) : failure.source_kind),
      sortValue: (failure) => failure.source_kind,
    },
    {
      key: "source_id",
      header: t("finance.failures.column.source"),
      defaultWidth: 240,
      cell: (failure) => <span className="font-mono text-xs">{failure.source_id}</span>,
      filterCell: textFilter(columnFilters, "source_id", t("finance.failures.column.source")),
      sortValue: (failure) => failure.source_id,
    },
    {
      key: "message",
      header: t("finance.failures.column.reason"),
      defaultWidth: 380,
      cell: (failure) => failureMessage(failure, language),
      filterCell: textFilter(columnFilters, "message", t("finance.failures.column.reason")),
    },
    {
      key: "actions",
      header: t("finance.column.action"),
      defaultWidth: 120,
      alwaysVisible: true,
      headerClassName: "text-right",
      cell: (failure) =>
        hasPermission("finance.manage_entries") ? (
          <div className="flex justify-end">
            <Button size="sm" variant="outline" disabled={retryMutation.isPending} onClick={() => retryMutation.mutate(failure.id)}>
              <RotateCcw className="h-3.5 w-3.5" />
              {t("finance.failures.retry")}
            </Button>
          </div>
        ) : null,
    },
  ];
  if (!isLoading && failures.length === 0) return null;
  return (
    <Card className="border-destructive/30">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <TriangleAlert className="h-4 w-4 text-destructive" />
          {t("finance.failures.title")}
        </CardTitle>
        <p className="text-sm text-muted-foreground">{t("finance.failures.subtitle")}</p>
      </CardHeader>
      <CardContent className="p-0 pb-2">
        <LedgerTable
          tableKey="finance.postingFailures"
          columns={columns}
          rows={rows}
          rowKey={(failure) => failure.id}
          isLoading={isLoading}
          loading="skeleton"
          emptyIcon={<TriangleAlert className="h-5 w-5" />}
          emptyTitle={t("finance.failures.emptyTitle")}
          emptyDescription={t("finance.failures.emptyDescription")}
          toolbar={
            <>
              <FilterTabs
                value={moduleFilter}
                onChange={setModuleFilter}
                options={[
                  { value: "all", label: t("common.all") },
                  { value: "payroll", label: t("finance.rules.source.payroll") },
                  { value: "finance", label: t("finance.rules.source.invoice") },
                ]}
              />
              {columnFilters.isActive && (
                <Button variant="ghost" size="sm" onClick={columnFilters.reset}>
                  {t("common.clearFilters")}
                </Button>
              )}
            </>
          }
        />
      </CardContent>
    </Card>
  );
}

function EntryDetailDialog({
  entryId,
  onClose,
  onEdit,
}: {
  entryId: string;
  onClose: () => void;
  onEdit: (entry: JournalEntryDetail) => void;
}) {
  const { session, hasPermission } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const [reverseDate, setReverseDate] = useState(todayIso());
  const { data: entry, isLoading } = useQuery({ queryKey: LEDGER_KEYS.entry(entryId), queryFn: () => getEntry(token, entryId) });
  const onError = (message: TranslationKey) => (error: unknown) => toast.error(t(message), { description: errorText(error) });
  const postMutation = useMutation({
    mutationFn: () => postEntry(token, entryId),
    onSuccess: () => {
      invalidateLedgerData(queryClient);
      toast.success(t("finance.entries.postedToast"));
    },
    onError: onError("finance.entries.postError"),
  });
  const deleteMutation = useMutation({
    mutationFn: () => deleteEntry(token, entryId),
    onSuccess: () => {
      invalidateLedgerData(queryClient);
      toast.success(t("finance.entries.deleted"));
      onClose();
    },
    onError: onError("finance.entries.deleteError"),
  });
  const reverseMutation = useMutation({
    mutationFn: () => reverseEntry(token, entryId, reverseDate),
    onSuccess: () => {
      invalidateLedgerData(queryClient);
      toast.success(t("finance.entries.reversedToast"));
    },
    onError: onError("finance.entries.reverseError"),
  });

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle>
            {entry?.number ?? t("finance.entries.draftTitle")} {entry && <EntryStatusBadge status={entry.status} />}
          </DialogTitle>
          <DialogDescription>
            {entry ? `${entry.journal_code} · ${formatDate(entry.entry_date)} · ${entry.label}` : ""}
          </DialogDescription>
        </DialogHeader>
        {isLoading || !entry ? (
          <Skeleton className="h-40 w-full" />
        ) : (
          <div className="space-y-4">
            {entry.reference && (
              <p className="text-sm text-muted-foreground">
                {t("finance.entries.column.reference")} : {entry.reference}
              </p>
            )}
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-left text-muted-foreground">
                  <th className="py-1.5">{t("finance.entries.line.account")}</th>
                  <th className="py-1.5">{t("finance.entries.line.label")}</th>
                  <th className="py-1.5 text-right">{t("finance.entries.line.debit")}</th>
                  <th className="py-1.5 text-right">{t("finance.entries.line.credit")}</th>
                </tr>
              </thead>
              <tbody>
                {entry.lines.map((line) => (
                  <tr key={line.line_no} className="border-b border-border/60">
                    <td className="py-1.5">
                      <span className="font-mono">{line.account_code}</span> {line.account_name}
                    </td>
                    <td className="py-1.5 text-muted-foreground">{[line.label, line.partner_name].filter(Boolean).join(" · ")}</td>
                    <td className="py-1.5 text-right tabular-nums">{formatAmountCell(line.debit)}</td>
                    <td className="py-1.5 text-right tabular-nums">{formatAmountCell(line.credit)}</td>
                  </tr>
                ))}
                <tr className="font-semibold">
                  <td className="py-1.5" colSpan={2}>
                    {t("finance.entries.total")}
                  </td>
                  <td className="py-1.5 text-right tabular-nums">{formatAmount(entry.total_debit)}</td>
                  <td className="py-1.5 text-right tabular-nums">{formatAmount(entry.total_credit)}</td>
                </tr>
              </tbody>
            </table>
            <div className="flex flex-wrap items-center justify-end gap-2">
              {entry.status === "draft" && hasPermission("finance.manage_entries") && (
                <Button variant="outline" disabled={deleteMutation.isPending} onClick={() => deleteMutation.mutate()}>
                  <Trash2 className="h-4 w-4" />
                  {t("common.delete")}
                </Button>
              )}
              {entry.status === "draft" && hasPermission("finance.admin_entries") && (
                <Button variant="outline" onClick={() => onEdit(entry)}>
                  <Pencil className="h-4 w-4" />
                  {t("common.edit")}
                </Button>
              )}
              {entry.status === "draft" && hasPermission("finance.manage_entries") && (
                <Button disabled={postMutation.isPending} onClick={() => postMutation.mutate()}>
                  <Send className="h-4 w-4" />
                  {t("finance.entries.post")}
                </Button>
              )}
              {entry.status === "posted" && hasPermission("finance.admin_entries") && (
                <>
                  <Label htmlFor="reverse_date" className="text-sm text-muted-foreground">
                    {t("finance.entries.reverseOn")}
                  </Label>
                  <Input
                    id="reverse_date"
                    type="date"
                    className="h-9 w-auto"
                    value={reverseDate}
                    onChange={(event) => setReverseDate(event.target.value)}
                  />
                  <Button variant="outline" disabled={reverseMutation.isPending} onClick={() => reverseMutation.mutate()}>
                    <RotateCcw className="h-4 w-4" />
                    {t("finance.entries.reverse")}
                  </Button>
                </>
              )}
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

const EMPTY_LINE = { account_code: "", debit: 0, credit: 0, label: "" };

function EntryFormDialog({ entry, journals, onClose }: { entry: JournalEntryDetail | null; journals: Journal[]; onClose: () => void }) {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const { data: accounts = [] } = useQuery({ queryKey: LEDGER_KEYS.accounts, queryFn: () => listAccounts(token) });
  const postable = accounts.filter((account) => account.is_postable);
  const schema = useMemo(
    () =>
      z.object({
        journal_code: z.string().min(1, t("common.required")),
        entry_date: z.string().min(1, t("common.required")),
        label: z.string().trim().min(1, t("common.required")),
        reference: z.string(),
        lines: z
          .array(
            z.object({
              account_code: z.string().min(1, t("common.required")),
              debit: z.coerce.number().int(t("common.wholeNumberOnly")).min(0),
              credit: z.coerce.number().int(t("common.wholeNumberOnly")).min(0),
              label: z.string(),
            }),
          )
          .min(2, t("finance.entries.needsTwoLines")),
      }),
    [t],
  );
  type EntryForm = z.infer<typeof schema>;
  const {
    register,
    control,
    handleSubmit,
    watch,
    formState: { errors },
  } = useForm<EntryForm>({
    resolver: zodResolver(schema),
    defaultValues: entry
      ? {
          journal_code: entry.journal_code,
          entry_date: entry.entry_date,
          label: entry.label,
          reference: entry.reference ?? "",
          lines: entry.lines.map((line) => ({
            account_code: line.account_code,
            debit: line.debit,
            credit: line.credit,
            label: line.label ?? "",
          })),
        }
      : { journal_code: "OD", entry_date: todayIso(), label: "", reference: "", lines: [EMPTY_LINE, EMPTY_LINE] },
  });
  const { fields, append, remove } = useFieldArray({ control, name: "lines" });
  const lines = watch("lines");
  const totalDebit = lines.reduce((sum, line) => sum + (Number(line.debit) || 0), 0);
  const totalCredit = lines.reduce((sum, line) => sum + (Number(line.credit) || 0), 0);

  const mutation = useMutation({
    mutationFn: (values: EntryForm) => {
      const input: EntryInput = {
        journal_code: values.journal_code,
        entry_date: values.entry_date,
        label: values.label,
        reference: values.reference || null,
        lines: values.lines.map((line) => ({
          account_code: line.account_code,
          debit: line.debit,
          credit: line.credit,
          label: line.label || null,
        })),
      };
      return entry ? updateEntry(token, entry.id, input) : createEntry(token, input);
    },
    onSuccess: () => {
      invalidateLedgerData(queryClient);
      toast.success(t(entry ? "finance.entries.updated" : "finance.entries.created"));
      onClose();
    },
    onError: (error) => toast.error(t("finance.entries.saveError"), { description: errorText(error) }),
  });

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-4xl">
        <DialogHeader>
          <DialogTitle>{t(entry ? "finance.entries.editTitle" : "finance.entries.newTitle")}</DialogTitle>
          <DialogDescription>{t("finance.entries.dialogDescription")}</DialogDescription>
        </DialogHeader>
        <form className="space-y-4" onSubmit={handleSubmit((values) => mutation.mutate(values))}>
          <div className="grid grid-cols-4 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="entry_journal">{t("finance.entries.column.journal")}</Label>
              <Select id="entry_journal" {...register("journal_code")}>
                {journals.map((journal) => (
                  <option key={journal.code} value={journal.code}>
                    {journal.code} · {journal.name}
                  </option>
                ))}
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="entry_date">{t("finance.entries.column.date")}</Label>
              <Input id="entry_date" type="date" {...register("entry_date")} />
              {errors.entry_date && <p className="text-sm text-destructive">{errors.entry_date.message}</p>}
            </div>
            <div className="col-span-2 space-y-1.5">
              <Label htmlFor="entry_label">{t("finance.entries.column.label")}</Label>
              <Input id="entry_label" {...register("label")} />
              {errors.label && <p className="text-sm text-destructive">{errors.label.message}</p>}
            </div>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="entry_reference">{t("finance.entries.column.reference")}</Label>
            <Input id="entry_reference" {...register("reference")} />
          </div>
          <div className="space-y-2">
            {fields.map((field, index) => (
              <div key={field.id} className="grid grid-cols-12 items-start gap-2">
                <div className="col-span-4">
                  <Select aria-label={t("finance.entries.line.account")} {...register(`lines.${index}.account_code` as const)}>
                    <option value="">{t("finance.entries.line.account")}</option>
                    {postable.map((account) => (
                      <option key={account.code} value={account.code}>
                        {account.code} · {account.name}
                      </option>
                    ))}
                  </Select>
                  {errors.lines?.[index]?.account_code && (
                    <p className="text-xs text-destructive">{errors.lines[index]?.account_code?.message}</p>
                  )}
                </div>
                <Input className="col-span-3" placeholder={t("finance.entries.line.label")} {...register(`lines.${index}.label` as const)} />
                <Input
                  className="col-span-2 text-right"
                  type="number"
                  min={0}
                  step={1}
                  placeholder={t("finance.entries.line.debit")}
                  {...register(`lines.${index}.debit` as const)}
                />
                <Input
                  className="col-span-2 text-right"
                  type="number"
                  min={0}
                  step={1}
                  placeholder={t("finance.entries.line.credit")}
                  {...register(`lines.${index}.credit` as const)}
                />
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="col-span-1"
                  onClick={() => remove(index)}
                  aria-label={t("common.delete")}
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </Button>
              </div>
            ))}
            {errors.lines?.message && <p className="text-sm text-destructive">{errors.lines.message}</p>}
            <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
              <Button type="button" variant="outline" size="sm" onClick={() => append({ ...EMPTY_LINE })}>
                <Plus className="h-3.5 w-3.5" />
                {t("finance.entries.addLine")}
              </Button>
              <span className={totalDebit === totalCredit ? "text-muted-foreground" : "font-medium text-warning"}>
                {t("finance.entries.line.debit")} {formatAmount(totalDebit)} · {t("finance.entries.line.credit")}{" "}
                {formatAmount(totalCredit)}
                {totalDebit !== totalCredit && ` · ${t("finance.entries.difference")} ${formatAmount(Math.abs(totalDebit - totalCredit))}`}
              </span>
            </div>
          </div>
          <Button type="submit" className="w-full" disabled={mutation.isPending}>
            {mutation.isPending ? t("common.saving") : t("finance.entries.saveDraft")}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}
