import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BellRing, CalendarClock, Download, FileText, Hourglass, Mail, Play, Plus, Settings as SettingsIcon, Trash2, UserRound } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../../lib/auth";
import { useI18n, type TranslationKey } from "../../lib/i18n";
import { useColumnFilters, type FilterField } from "../../lib/useColumnFilters";
import type { ColumnDef } from "../../lib/useTableColumns";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { Checkbox } from "../../components/ui/checkbox";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "../../components/ui/dialog";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Select } from "../../components/ui/select";
import { Tabs, TabsList, TabsTrigger } from "../../components/ui/tabs";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../../components/ui/table";
import { FilterTabs } from "../../components/patterns/FilterTabs";
import { StickyTabBar } from "../../components/patterns/StickyTabBar";
import { openDocument } from "../warehouse/printDocument";
import { LedgerTable, rangeFilter, textFilter } from "./LedgerTable";
import { errorText, formatAmount, formatDate } from "./ledgerFormat";
import {
  BUCKETS,
  RECEIVABLES_QUERY_KEY,
  createPaymentTerm,
  downloadReceivables,
  getAging,
  getDunningLevels,
  getLetter,
  getReceivablesSettings,
  getStatement,
  getWorklist,
  listPaymentTerms,
  recordDunningAction,
  runDunning,
  saveDunningLevels,
  saveReceivablesSettings,
  setCreditLimit,
  setPartnerTerm,
  setPromiseStatus,
  updatePaymentTerm,
  type ActionKind,
  type AgingRow,
  type BucketKey,
  type DunningAction,
  type DunningLevel,
  type Installment,
  type PaymentTerm,
  type WorklistRow,
} from "./receivablesApi";

const amount = (value: string | number | null | undefined) => formatAmount(Number(value ?? 0));

const BUCKET_KEYS: Record<BucketKey, TranslationKey> = {
  not_due: "finance.receivables.bucket.not_due",
  "1_30": "finance.receivables.bucket.1_30",
  "31_60": "finance.receivables.bucket.31_60",
  "61_90": "finance.receivables.bucket.61_90",
  over_90: "finance.receivables.bucket.over_90",
};

const ACTION_KEYS: Record<ActionKind, TranslationKey> = {
  letter: "finance.receivables.action.letter",
  call: "finance.receivables.action.call",
  email: "finance.receivables.action.email",
  promise: "finance.receivables.action.promise",
  note: "finance.receivables.action.note",
};

function useNames() {
  const { language } = useI18n();
  return {
    termName: (term: PaymentTerm | null | undefined) => (term ? (language === "fr" ? term.name_fr : term.name_en) : null),
    levelName: (level: DunningLevel | null | undefined) => (level ? (language === "fr" ? level.name_fr : level.name_en) : null),
  };
}

async function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

// ---- the letter -------------------------------------------------------------------------------------------

export function usePrintLetter() {
  const { session } = useAuth();
  const { t, language } = useI18n();
  return async (partnerId: string, level?: number) => {
    try {
      const letter = await getLetter(session!.token, partnerId, level);
      const company = letter.company;
      const body = language === "fr" ? letter.level.letter_fr : letter.level.letter_en;
      const name = language === "fr" ? letter.level.name_fr : letter.level.name_en;
      // The company block from Recouvrement > Paramètres; an empty detail is simply left off.
      const companyFields = ([
        ["finance.receivables.settings.companyAddress", company.company_address],
        ["finance.receivables.settings.companyPhone", company.company_phone],
        ["finance.receivables.settings.companyEmail", company.company_email],
        ["finance.receivables.settings.companyTaxId", company.company_tax_id],
        ["finance.receivables.settings.companyRccm", company.company_rccm],
      ] as [TranslationKey, string | null][]).filter(([, value]) => value).map(([key, value]) => [t(key), value!] as [string, string]);
      const signature = [company.signatory, company.signatory_title].filter(Boolean).join("\n");
      const opened = openDocument(
        {
          brand: company.company_name ?? "Sonalim",
          title: `${name} — ${letter.partner.name}`,
          fields: [
            ...companyFields,
            [t("finance.receivables.letter.to"), [letter.partner.name, letter.partner.phone, letter.partner.email].filter(Boolean).join(" · ")],
            [t("finance.receivables.letter.date"), formatDate(letter.date)],
            [t("finance.receivables.letter.totalOverdue"), `${amount(letter.overdue)} F CFA`],
          ],
          headers: [
            t("finance.receivables.column.invoice"),
            t("finance.receivables.column.invoiceDate"),
            t("finance.receivables.column.dueDate"),
            t("finance.receivables.column.total"),
            t("finance.receivables.column.overdue"),
            t("finance.receivables.column.daysLate"),
          ],
          rows: letter.invoices.map((invoice) => [
            invoice.number ?? invoice.id.slice(-8),
            formatDate(invoice.invoice_date),
            invoice.oldest_due ? formatDate(invoice.oldest_due) : "",
            amount(invoice.total),
            amount(invoice.overdue),
            invoice.days_overdue,
          ]),
          footer: signature ? `${body}\n\n${signature}` : body,
        },
        { print: true },
      );
      if (!opened) toast.error(t("finance.receivables.letter.popupBlocked"));
    } catch (error) {
      toast.error(t("finance.receivables.letter.error"), { description: errorText(error) });
    }
  };
}

// ---- the customer account ------------------------------------------------------------------------------

function CustomerAccountDialog({ partnerId, onClose }: { partnerId: string; onClose: () => void }) {
  const { session, hasPermission } = useAuth();
  const { t, language } = useI18n();
  const { termName, levelName } = useNames();
  const token = session!.token;
  const queryClient = useQueryClient();
  const printLetter = usePrintLetter();
  const canManage = hasPermission("finance.manage_receivables");
  const canChase = hasPermission("finance.manage_dunning");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const statementKey = [...RECEIVABLES_QUERY_KEY, "statement", partnerId, dateFrom, dateTo];
  const { data: statement } = useQuery({ queryKey: statementKey, queryFn: () => getStatement(token, partnerId, dateFrom || undefined, dateTo || undefined) });
  const { data: terms = [] } = useQuery({ queryKey: [...RECEIVABLES_QUERY_KEY, "terms"], queryFn: () => listPaymentTerms(token) });
  const { data: levels = [] } = useQuery({ queryKey: [...RECEIVABLES_QUERY_KEY, "levels"], queryFn: () => getDunningLevels(token) });
  const [limit, setLimit] = useState("");
  const [kind, setKind] = useState<ActionKind>("letter");
  const [level, setLevel] = useState("");
  const [note, setNote] = useState("");
  const [promiseDate, setPromiseDate] = useState("");
  const [promiseAmount, setPromiseAmount] = useState("");

  const position = statement?.position;
  useEffect(() => {
    if (position) setLimit(position.credit_limit === null ? "" : String(Number(position.credit_limit)));
    if (position?.dunning_level) setLevel(String(position.dunning_level.level));
  }, [position?.credit_limit, position?.dunning_level?.level]); // eslint-disable-line react-hooks/exhaustive-deps

  const refresh = () => void queryClient.invalidateQueries({ queryKey: RECEIVABLES_QUERY_KEY });
  const fail = (key: TranslationKey) => (error: unknown) => toast.error(t(key), { description: errorText(error) });
  const termMutation = useMutation({
    mutationFn: (termId: string | null) => setPartnerTerm(token, partnerId, "customer", termId),
    onSuccess: () => { refresh(); toast.success(t("finance.receivables.saved")); },
    onError: fail("finance.receivables.saveError"),
  });
  const limitMutation = useMutation({
    mutationFn: () => setCreditLimit(token, partnerId, limit.trim() === "" ? null : Number(limit)),
    onSuccess: () => { refresh(); toast.success(t("finance.receivables.saved")); },
    onError: fail("finance.receivables.saveError"),
  });
  const actionMutation = useMutation({
    mutationFn: () =>
      recordDunningAction(token, {
        partner_id: partnerId,
        kind,
        level: kind === "letter" && level ? Number(level) : null,
        note: note || undefined,
        promise_date: kind === "promise" ? promiseDate : undefined,
        promise_amount: kind === "promise" && promiseAmount ? Number(promiseAmount) : undefined,
      }),
    onSuccess: () => {
      refresh();
      setNote("");
      setPromiseDate("");
      setPromiseAmount("");
      toast.success(t("finance.receivables.actionRecorded"));
      if (kind === "letter") void printLetter(partnerId, level ? Number(level) : undefined);
    },
    onError: fail("finance.receivables.actionError"),
  });
  const promiseMutation = useMutation({
    mutationFn: ({ id, status }: { id: string; status: "kept" | "broken" }) => setPromiseStatus(token, id, status),
    onSuccess: refresh,
    onError: fail("finance.receivables.saveError"),
  });

  async function exportStatement(format: "csv" | "xlsx") {
    try {
      await saveBlob(await downloadReceivables(token, { statement: partnerId }, format, language), `releve.${format}`);
    } catch (error) {
      toast.error(t("finance.receivables.exportError"), { description: errorText(error) });
    }
  }

  const kindLabel = (line: { kind: string }) =>
    t(({ invoice: "finance.receivables.line.invoice", credit_note: "finance.receivables.line.credit_note", payment: "finance.receivables.line.payment",
         payment_reversed: "finance.receivables.line.payment_reversed" } as Record<string, TranslationKey>)[line.kind]);

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-h-[92vh] max-w-5xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{t("finance.receivables.account.title")} — {statement?.partner_name ?? "…"}</DialogTitle>
          <DialogDescription>{t("finance.receivables.account.description")}</DialogDescription>
        </DialogHeader>
        {position && (
          <div className="space-y-5">
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
              {[
                ["finance.receivables.exposure", amount(position.exposure)],
                ["finance.receivables.creditLimit", position.credit_limit === null ? t("finance.receivables.noLimit") : amount(position.credit_limit)],
                ["finance.receivables.available", position.available === null ? "—" : amount(position.available)],
                ["finance.receivables.column.overdue", amount(position.overdue)],
                ["finance.receivables.column.daysLate", String(position.max_days_overdue)],
              ].map(([key, value]) => (
                <div key={key} className="rounded-md border p-3">
                  <div className="text-xs text-muted-foreground">{t(key as TranslationKey)}</div>
                  <div className="text-lg font-semibold tabular-nums">{value}</div>
                </div>
              ))}
            </div>
            <div className="text-xs text-muted-foreground">
              {t("finance.receivables.exposureParts")} {amount(position.open_invoices)} · {amount(position.uninvoiced_deliveries)} · {amount(position.undelivered_orders)}
            </div>
            {position.dunning_level && (
              <div className={`rounded-md border px-3 py-2 text-sm ${position.blocked ? "border-destructive/30 bg-destructive-soft text-destructive" : "border-warning/30 bg-warning-soft text-warning"}`}>
                {t("finance.receivables.levelReached")} {position.dunning_level.level} — {levelName(position.dunning_level)}
                {position.blocked && ` · ${t("finance.receivables.blocked")}`}
              </div>
            )}

            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-1.5">
                <Label htmlFor="customer_term">{t("finance.receivables.customerTerm")}</Label>
                <Select id="customer_term" disabled={!canManage || termMutation.isPending} value={position.customer_term?.id ?? ""}
                        onChange={(e) => termMutation.mutate(e.target.value || null)}>
                  <option value="">{t("finance.receivables.noTerm")}</option>
                  {terms.map((term) => <option key={term.id} value={term.id}>{termName(term)}</option>)}
                </Select>
                <p className="text-xs text-muted-foreground">{t("finance.receivables.termHint")}</p>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="credit_limit">{t("finance.receivables.creditLimit")}</Label>
                <div className="flex gap-2">
                  <Input id="credit_limit" type="number" min={0} step={1} disabled={!canManage} value={limit} placeholder={t("finance.receivables.noLimit")}
                         onChange={(e) => setLimit(e.target.value)} />
                  {canManage && <Button variant="outline" disabled={limitMutation.isPending} onClick={() => limitMutation.mutate()}>{t("common.save")}</Button>}
                </div>
              </div>
            </div>

            <div>
              <h3 className="mb-2 text-sm font-semibold">{t("finance.receivables.agingTitle")}</h3>
              <div className="grid grid-cols-5 gap-2 text-sm">
                {BUCKETS.map((bucket) => (
                  <div key={bucket} className="rounded-md border p-2">
                    <div className="text-xs text-muted-foreground">{t(BUCKET_KEYS[bucket])}</div>
                    <div className="tabular-nums">{amount(position.buckets[bucket])}</div>
                  </div>
                ))}
              </div>
            </div>

            <div className="space-y-2">
              <div className="flex flex-wrap items-end gap-2">
                <h3 className="mr-auto text-sm font-semibold">{t("finance.receivables.statement")}</h3>
                <div className="space-y-1"><Label htmlFor="st_from" className="text-xs">{t("finance.receivables.from")}</Label>
                  <Input id="st_from" type="date" className="h-8" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} /></div>
                <div className="space-y-1"><Label htmlFor="st_to" className="text-xs">{t("finance.receivables.to")}</Label>
                  <Input id="st_to" type="date" className="h-8" value={dateTo} onChange={(e) => setDateTo(e.target.value)} /></div>
                <Button size="sm" variant="outline" onClick={() => exportStatement("xlsx")}><Download className="h-3.5 w-3.5" />Excel</Button>
                <Button size="sm" variant="outline" onClick={() => exportStatement("csv")}><Download className="h-3.5 w-3.5" />CSV</Button>
              </div>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>{t("finance.receivables.letter.date")}</TableHead>
                    <TableHead>{t("finance.receivables.column.type")}</TableHead>
                    <TableHead>{t("finance.receivables.column.reference")}</TableHead>
                    <TableHead>{t("finance.receivables.column.dueDate")}</TableHead>
                    <TableHead className="text-right">{t("finance.receivables.column.debit")}</TableHead>
                    <TableHead className="text-right">{t("finance.receivables.column.credit")}</TableHead>
                    <TableHead className="text-right">{t("finance.receivables.column.balance")}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  <TableRow>
                    <TableCell colSpan={6} className="text-muted-foreground">{t("finance.receivables.opening")}</TableCell>
                    <TableCell className="text-right tabular-nums">{amount(statement.opening_balance)}</TableCell>
                  </TableRow>
                  {statement.lines.map((line, index) => (
                    <TableRow key={`${line.reference}-${index}`}>
                      <TableCell>{formatDate(line.date)}</TableCell>
                      <TableCell>{kindLabel(line)}</TableCell>
                      <TableCell className="font-mono text-xs">{line.reference}{line.against ? ` → ${line.against}` : ""}</TableCell>
                      <TableCell>{line.due_date ? formatDate(line.due_date) : ""}</TableCell>
                      <TableCell className="text-right tabular-nums">{Number(line.debit) ? amount(line.debit) : ""}</TableCell>
                      <TableCell className="text-right tabular-nums">{Number(line.credit) ? amount(line.credit) : ""}</TableCell>
                      <TableCell className="text-right tabular-nums">{amount(line.balance)}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>

            <div className="space-y-2">
              <h3 className="text-sm font-semibold">{t("finance.receivables.history")}</h3>
              {canChase && (
                <div className="grid gap-2 rounded-md border p-3 sm:grid-cols-6">
                  <Select aria-label={t("finance.receivables.column.type")} value={kind} onChange={(e) => setKind(e.target.value as ActionKind)}>
                    {(["letter", "call", "email", "promise", "note"] as ActionKind[]).map((k) => <option key={k} value={k}>{t(ACTION_KEYS[k])}</option>)}
                  </Select>
                  {kind === "letter" && (
                    <Select aria-label={t("finance.receivables.level")} value={level} onChange={(e) => setLevel(e.target.value)}>
                      {levels.map((l) => <option key={l.level} value={l.level}>{l.level} — {levelName(l)}</option>)}
                    </Select>
                  )}
                  {kind === "promise" && (
                    <>
                      <Input type="date" aria-label={t("finance.receivables.promiseDate")} value={promiseDate} onChange={(e) => setPromiseDate(e.target.value)} />
                      <Input type="number" min={1} step={1} aria-label={t("finance.receivables.promiseAmount")} placeholder={t("finance.receivables.promiseAmount")}
                             value={promiseAmount} onChange={(e) => setPromiseAmount(e.target.value)} />
                    </>
                  )}
                  <Input className="sm:col-span-2" placeholder={t("finance.receivables.notePlaceholder")} value={note} onChange={(e) => setNote(e.target.value)} />
                  <Button disabled={actionMutation.isPending || (kind === "promise" && !promiseDate)} onClick={() => actionMutation.mutate()}>
                    <Plus className="h-4 w-4" />
                    {t(kind === "letter" ? "finance.receivables.recordAndPrint" : "finance.receivables.record")}
                  </Button>
                </div>
              )}
              {kind === "email" && <p className="text-xs text-muted-foreground">{t("finance.receivables.noEmail")}</p>}
              <HistoryList actions={statement.dunning_history} levels={levels} canChase={canChase}
                           onPromise={(id, status) => promiseMutation.mutate({ id, status })} />
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

function HistoryList({ actions, levels, canChase, onPromise }: {
  actions: DunningAction[]; levels: DunningLevel[]; canChase: boolean; onPromise: (id: string, status: "kept" | "broken") => void;
}) {
  const { t } = useI18n();
  const { levelName } = useNames();
  if (actions.length === 0) return <p className="text-sm text-muted-foreground">{t("finance.receivables.noHistory")}</p>;
  return (
    <ul className="divide-y rounded-md border text-sm">
      {actions.map((action) => (
        <li key={action.id} className="flex flex-wrap items-center gap-2 px-3 py-2">
          <span className="text-xs text-muted-foreground">{formatDate(action.created_at)}</span>
          <Badge variant={action.kind === "promise" ? "primary" : "default"}>{t(ACTION_KEYS[action.kind])}</Badge>
          {action.level && <span>{action.level} — {levelName(levels.find((l) => l.level === action.level))}</span>}
          {action.promise_date && (
            <span>
              {t("finance.receivables.promisedFor")} {formatDate(action.promise_date)}
              {action.promise_amount ? ` · ${amount(action.promise_amount)} F CFA` : ""}
            </span>
          )}
          {action.promise_status && (
            <Badge variant={action.promise_status === "kept" ? "success" : action.promise_status === "broken" ? "destructive" : "warning"}>
              {t(`finance.receivables.promise.${action.promise_status}` as TranslationKey)}
            </Badge>
          )}
          {action.note && <span className="text-muted-foreground">« {action.note} »</span>}
          {canChase && action.promise_status === "open" && (
            <span className="ml-auto flex gap-1">
              <Button size="sm" variant="outline" onClick={() => onPromise(action.id, "kept")}>{t("finance.receivables.promise.markKept")}</Button>
              <Button size="sm" variant="outline" onClick={() => onPromise(action.id, "broken")}>{t("finance.receivables.promise.markBroken")}</Button>
            </span>
          )}
        </li>
      ))}
    </ul>
  );
}

// ---- tabs ---------------------------------------------------------------------------------------------------

type ChaseFilter = "to_chase" | "all" | "promised" | "blocked";

function WorklistTab({ openAccount }: { openAccount: (partnerId: string) => void }) {
  const { session, hasPermission } = useAuth();
  const { t } = useI18n();
  const { levelName } = useNames();
  const token = session!.token;
  const queryClient = useQueryClient();
  const printLetter = usePrintLetter();
  const [filter, setFilter] = useState<ChaseFilter>("to_chase");
  const { data: rows = [], isLoading } = useQuery({ queryKey: [...RECEIVABLES_QUERY_KEY, "worklist"], queryFn: () => getWorklist(token) });
  const runMutation = useMutation({
    mutationFn: () => runDunning(token),
    onSuccess: (result) => {
      void queryClient.invalidateQueries({ queryKey: RECEIVABLES_QUERY_KEY });
      toast.success(`${t("finance.receivables.runDone")} ${result.levels_announced} · ${result.promises_broken}`);
    },
    onError: (error) => toast.error(t("finance.receivables.saveError"), { description: errorText(error) }),
  });
  const fields: FilterField<WorklistRow>[] = [
    { key: "partner", kind: "text", getValue: (row) => row.partner_name ?? "" },
    { key: "overdue", kind: "range", getValue: (row) => Number(row.overdue) },
    { key: "days", kind: "range", getValue: (row) => row.days_overdue },
  ];
  const columnFilters = useColumnFilters(fields);
  const filtered = columnFilters.apply(rows.filter((row) =>
    filter === "all" || (filter === "to_chase" && row.to_chase) || (filter === "promised" && row.open_promise) || (filter === "blocked" && row.blocked)));
  const columns: ColumnDef<WorklistRow>[] = [
    { key: "partner", header: t("finance.receivables.column.customer"), defaultWidth: 220, cell: (row) => row.partner_name ?? row.partner_id,
      filterCell: textFilter(columnFilters, "partner", t("finance.receivables.column.customer")), sortValue: (row) => row.partner_name ?? "" },
    { key: "overdue", header: t("finance.receivables.column.overdue"), defaultWidth: 130, cellClassName: "text-right tabular-nums",
      cell: (row) => amount(row.overdue), filterCell: rangeFilter(columnFilters, "overdue"), sortValue: (row) => Number(row.overdue) },
    { key: "remaining", header: t("finance.receivables.column.remaining"), defaultWidth: 130, cellClassName: "text-right tabular-nums",
      cell: (row) => amount(row.remaining), sortValue: (row) => Number(row.remaining) },
    { key: "days", header: t("finance.receivables.column.daysLate"), defaultWidth: 100, cellClassName: "text-right tabular-nums",
      cell: (row) => row.days_overdue, filterCell: rangeFilter(columnFilters, "days"), sortValue: (row) => row.days_overdue },
    { key: "level", header: t("finance.receivables.level"), defaultWidth: 190, sortValue: (row) => row.level_reached?.level ?? 0,
      cell: (row) => row.level_reached ? (
        <Badge variant={row.blocked ? "destructive" : "warning"}>{row.level_reached.level} — {levelName(row.level_reached)}</Badge>
      ) : "—" },
    { key: "sent", header: t("finance.receivables.column.lastLetter"), defaultWidth: 110, cell: (row) => row.level_sent ?? "—" },
    { key: "promise", header: t("finance.receivables.action.promise"), defaultWidth: 160,
      cell: (row) => row.open_promise?.promise_date ? `${t("finance.receivables.promisedFor")} ${formatDate(row.open_promise.promise_date)}`
        : row.broken_promise ? <Badge variant="destructive">{t("finance.receivables.promise.broken")}</Badge> : "" },
    { key: "actions", header: "", alwaysVisible: true, defaultWidth: 230, cell: (row) => (
      <span className="flex gap-1">
        <Button size="sm" variant="outline" onClick={() => openAccount(row.partner_id)}><UserRound className="h-3.5 w-3.5" />{t("finance.receivables.account.open")}</Button>
        <Button size="sm" variant="outline" onClick={() => void printLetter(row.partner_id, row.next_level?.level ?? row.level_reached?.level)}>
          <FileText className="h-3.5 w-3.5" />{t("finance.receivables.action.letter")}
        </Button>
      </span>
    ) },
  ];
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between gap-3">
        <div>
          <CardTitle>{t("finance.receivables.tabs.dunning")}</CardTitle>
          <p className="text-sm text-muted-foreground">{t("finance.receivables.dunningHint")}</p>
        </div>
        {hasPermission("finance.manage_dunning") && (
          <Button variant="outline" disabled={runMutation.isPending} onClick={() => runMutation.mutate()}>
            <Play className="h-4 w-4" />{t("finance.receivables.run")}
          </Button>
        )}
      </CardHeader>
      <CardContent className="p-0 pb-2">
        <LedgerTable tableKey="finance.receivables.worklist" columns={columns} rows={filtered} rowKey={(row) => row.partner_id} isLoading={isLoading}
          emptyIcon={<BellRing className="h-5 w-5" />} emptyTitle={t("finance.receivables.emptyTitle")} emptyDescription={t("finance.receivables.emptyDescription")}
          toolbar={
            <>
              <FilterTabs value={filter} onChange={setFilter} options={[
                { value: "to_chase", label: t("finance.receivables.filter.toChase") },
                { value: "promised", label: t("finance.receivables.filter.promised") },
                { value: "blocked", label: t("finance.receivables.filter.blocked") },
                { value: "all", label: t("common.all") },
              ]} />
              {columnFilters.isActive && <Button variant="ghost" size="sm" onClick={columnFilters.reset}>{t("common.clearFilters")}</Button>}
            </>
          } />
      </CardContent>
    </Card>
  );
}

function AgingTab({ openAccount }: { openAccount: (partnerId: string) => void }) {
  const { session } = useAuth();
  const { t, language } = useI18n();
  const token = session!.token;
  const [filter, setFilter] = useState<"all" | "late">("all");
  const { data: rows = [], isLoading } = useQuery({ queryKey: [...RECEIVABLES_QUERY_KEY, "aging"], queryFn: () => getAging(token) });
  const fields: FilterField<AgingRow>[] = [
    { key: "partner", kind: "text", getValue: (row) => row.partner_name ?? "" },
    { key: "remaining", kind: "range", getValue: (row) => Number(row.remaining) },
  ];
  const columnFilters = useColumnFilters(fields);
  const filtered = columnFilters.apply(rows.filter((row) => filter === "all" || Number(row.overdue) > 0));
  const total = (key: keyof AgingRow) => filtered.reduce((sum, row) => sum + Number(row[key] ?? 0), 0);
  const columns: ColumnDef<AgingRow>[] = [
    { key: "partner", header: t("finance.receivables.column.customer"), defaultWidth: 220, cell: (row) => (
      <button type="button" className="text-left underline-offset-2 hover:underline" onClick={() => openAccount(row.partner_id)}>{row.partner_name ?? row.partner_id}</button>
    ), filterCell: textFilter(columnFilters, "partner", t("finance.receivables.column.customer")), sortValue: (row) => row.partner_name ?? "" },
    { key: "limit", header: t("finance.receivables.creditLimit"), defaultWidth: 120, cellClassName: "text-right tabular-nums",
      cell: (row) => row.credit_limit === null ? "—" : amount(row.credit_limit) },
    { key: "remaining", header: t("finance.receivables.column.remaining"), defaultWidth: 130, cellClassName: "text-right tabular-nums",
      cell: (row) => amount(row.remaining), filterCell: rangeFilter(columnFilters, "remaining"), sortValue: (row) => Number(row.remaining) },
    ...BUCKETS.map((bucket): ColumnDef<AgingRow> => ({
      key: bucket, header: t(BUCKET_KEYS[bucket]), defaultWidth: 110, cellClassName: "text-right tabular-nums",
      cell: (row) => Number(row[`bucket_${bucket}`]) ? amount(row[`bucket_${bucket}`]) : "", sortValue: (row) => Number(row[`bucket_${bucket}`]),
    })),
    { key: "days", header: t("finance.receivables.column.daysLate"), defaultWidth: 100, cellClassName: "text-right tabular-nums",
      cell: (row) => row.max_days_overdue || "", sortValue: (row) => row.max_days_overdue },
  ];
  async function exportAging(format: "csv" | "xlsx") {
    try {
      await saveBlob(await downloadReceivables(token, "aging", format, language), `balance-agee.${format}`);
    } catch (error) {
      toast.error(t("finance.receivables.exportError"), { description: errorText(error) });
    }
  }
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between gap-3">
        <CardTitle>{t("finance.receivables.tabs.aging")}</CardTitle>
        <span className="flex gap-2">
          <Button size="sm" variant="outline" onClick={() => exportAging("xlsx")}><Download className="h-3.5 w-3.5" />Excel</Button>
          <Button size="sm" variant="outline" onClick={() => exportAging("csv")}><Download className="h-3.5 w-3.5" />CSV</Button>
        </span>
      </CardHeader>
      <CardContent className="p-0 pb-2">
        <LedgerTable tableKey="finance.receivables.aging" columns={columns} rows={filtered} rowKey={(row) => row.partner_id} isLoading={isLoading}
          emptyIcon={<Hourglass className="h-5 w-5" />} emptyTitle={t("finance.receivables.agingEmpty")} emptyDescription={t("finance.receivables.agingEmptyDescription")}
          footer={(key) => key === "remaining" ? amount(total("remaining")) : (BUCKETS as readonly string[]).includes(key) ? amount(total(`bucket_${key}` as keyof AgingRow)) : null}
          toolbar={
            <>
              <FilterTabs value={filter} onChange={setFilter} options={[
                { value: "all", label: t("common.all") },
                { value: "late", label: t("finance.receivables.filter.late") },
              ]} />
              {columnFilters.isActive && <Button variant="ghost" size="sm" onClick={columnFilters.reset}>{t("common.clearFilters")}</Button>}
            </>
          } />
      </CardContent>
    </Card>
  );
}

function describeInstallments(installments: Installment[], t: (key: TranslationKey) => string) {
  return installments.map((i) => {
    const parts = [`${Number(i.percent)} %`, `${i.days} ${t("finance.receivables.terms.days")}`];
    if (i.end_of_month) parts.push(t("finance.receivables.terms.endOfMonth"));
    if (i.day_of_month) parts.push(`${t("finance.receivables.terms.onThe")} ${i.day_of_month}`);
    return parts.join(" ");
  }).join(" + ");
}

const EMPTY_INSTALLMENT: Installment = { percent: 100, days: 30, end_of_month: false, day_of_month: null };

function TermDialog({ term, onClose }: { term: PaymentTerm | null; onClose: () => void }) {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const [code, setCode] = useState(term?.code ?? "");
  const [nameFr, setNameFr] = useState(term?.name_fr ?? "");
  const [nameEn, setNameEn] = useState(term?.name_en ?? "");
  const [installments, setInstallments] = useState<Installment[]>(term?.installments ?? [EMPTY_INSTALLMENT]);
  const mutation = useMutation({
    mutationFn: () => {
      const cleaned = installments.map((i) => ({ ...i, percent: Number(i.percent), days: Number(i.days), day_of_month: i.day_of_month ? Number(i.day_of_month) : null }));
      return term ? updatePaymentTerm(token, term.id, { name_fr: nameFr, name_en: nameEn, installments: cleaned })
        : createPaymentTerm(token, { code, name_fr: nameFr, name_en: nameEn, installments: cleaned });
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: RECEIVABLES_QUERY_KEY });
      toast.success(t("finance.receivables.saved"));
      onClose();
    },
    onError: (error) => toast.error(t("finance.receivables.saveError"), { description: errorText(error) }),
  });
  const update = (index: number, patch: Partial<Installment>) => setInstallments((all) => all.map((i, n) => (n === index ? { ...i, ...patch } : i)));
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>{t(term ? "finance.receivables.terms.edit" : "finance.receivables.terms.new")}</DialogTitle>
          <DialogDescription>{t("finance.receivables.terms.description")}</DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <div className="grid gap-3 sm:grid-cols-3">
            <div className="space-y-1.5"><Label htmlFor="term_code">{t("finance.receivables.terms.code")}</Label>
              <Input id="term_code" disabled={!!term} value={code} onChange={(e) => setCode(e.target.value)} /></div>
            <div className="space-y-1.5"><Label htmlFor="term_fr">{t("finance.receivables.terms.nameFr")}</Label>
              <Input id="term_fr" value={nameFr} onChange={(e) => setNameFr(e.target.value)} /></div>
            <div className="space-y-1.5"><Label htmlFor="term_en">{t("finance.receivables.terms.nameEn")}</Label>
              <Input id="term_en" value={nameEn} onChange={(e) => setNameEn(e.target.value)} /></div>
          </div>
          {installments.map((installment, index) => (
            <div key={index} className="grid items-end gap-2 rounded-md border p-2 sm:grid-cols-5">
              <div className="space-y-1"><Label className="text-xs">%</Label>
                <Input type="number" min={1} max={100} value={installment.percent} onChange={(e) => update(index, { percent: e.target.value })} /></div>
              <div className="space-y-1"><Label className="text-xs">{t("finance.receivables.terms.days")}</Label>
                <Input type="number" min={0} value={installment.days} onChange={(e) => update(index, { days: Number(e.target.value) })} /></div>
              <label className="flex items-center gap-2 pb-2 text-sm">
                <Checkbox checked={installment.end_of_month} onCheckedChange={(checked) => update(index, { end_of_month: checked === true })} />
                {t("finance.receivables.terms.endOfMonth")}
              </label>
              <div className="space-y-1"><Label className="text-xs">{t("finance.receivables.terms.dayOfMonth")}</Label>
                <Input type="number" min={1} max={31} value={installment.day_of_month ?? ""} onChange={(e) => update(index, { day_of_month: e.target.value ? Number(e.target.value) : null })} /></div>
              <Button variant="ghost" size="sm" aria-label={t("finance.receivables.terms.removeInstallment")} disabled={installments.length === 1}
                      onClick={() => setInstallments((all) => all.filter((_, n) => n !== index))}><Trash2 className="h-4 w-4" /></Button>
            </div>
          ))}
          <div className="flex justify-between">
            <Button variant="outline" size="sm" onClick={() => setInstallments((all) => [...all, { ...EMPTY_INSTALLMENT, percent: 0 }])}>
              <Plus className="h-4 w-4" />{t("finance.receivables.terms.addInstallment")}
            </Button>
            <Button disabled={mutation.isPending || !nameFr || (!term && !code)} onClick={() => mutation.mutate()}>{t("common.save")}</Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function TermsTab() {
  const { session, hasPermission } = useAuth();
  const { t } = useI18n();
  const { termName } = useNames();
  const token = session!.token;
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState<PaymentTerm | "new" | null>(null);
  const [filter, setFilter] = useState<"active" | "all">("active");
  const { data: terms = [], isLoading } = useQuery({ queryKey: [...RECEIVABLES_QUERY_KEY, "terms", "all"], queryFn: () => listPaymentTerms(token, true) });
  const canAdmin = hasPermission("finance.admin_receivables");
  const toggle = useMutation({
    mutationFn: (term: PaymentTerm) => updatePaymentTerm(token, term.id, { active: !term.active }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: RECEIVABLES_QUERY_KEY }),
    onError: (error) => toast.error(t("finance.receivables.saveError"), { description: errorText(error) }),
  });
  const fields: FilterField<PaymentTerm>[] = [
    { key: "code", kind: "text", getValue: (term) => term.code },
    { key: "name", kind: "text", getValue: (term) => termName(term) ?? "" },
  ];
  const columnFilters = useColumnFilters(fields);
  const rows = columnFilters.apply(terms.filter((term) => filter === "all" || term.active));
  const columns: ColumnDef<PaymentTerm>[] = [
    { key: "code", header: t("finance.receivables.terms.code"), defaultWidth: 120, cell: (term) => <span className="font-mono">{term.code}</span>,
      filterCell: textFilter(columnFilters, "code", t("finance.receivables.terms.code")), sortValue: (term) => term.code },
    { key: "name", header: t("finance.receivables.terms.name"), defaultWidth: 240, cell: (term) => termName(term),
      filterCell: textFilter(columnFilters, "name", t("finance.receivables.terms.name")) },
    { key: "rule", header: t("finance.receivables.terms.rule"), defaultWidth: 320, cell: (term) => describeInstallments(term.installments, t) },
    { key: "active", header: t("finance.receivables.terms.active"), defaultWidth: 90,
      cell: (term) => <Badge variant={term.active ? "success" : "default"}>{t(term.active ? "finance.receivables.terms.isActive" : "finance.receivables.terms.isInactive")}</Badge> },
    { key: "actions", header: "", alwaysVisible: true, defaultWidth: 190, cell: (term) => canAdmin && (
      <span className="flex gap-1">
        <Button size="sm" variant="outline" onClick={() => setEditing(term)}>{t("common.edit")}</Button>
        <Button size="sm" variant="ghost" onClick={() => toggle.mutate(term)}>{t(term.active ? "finance.receivables.terms.deactivate" : "finance.receivables.terms.activate")}</Button>
      </span>
    ) },
  ];
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between gap-3">
        <div>
          <CardTitle>{t("finance.receivables.tabs.terms")}</CardTitle>
          <p className="text-sm text-muted-foreground">{t("finance.receivables.terms.hint")}</p>
        </div>
        {hasPermission("finance.manage_receivables") && <Button onClick={() => setEditing("new")}><Plus className="h-4 w-4" />{t("finance.receivables.terms.new")}</Button>}
      </CardHeader>
      <CardContent className="p-0 pb-2">
        <LedgerTable tableKey="finance.receivables.terms" columns={columns} rows={rows} rowKey={(term) => term.id} isLoading={isLoading}
          emptyIcon={<CalendarClock className="h-5 w-5" />} emptyTitle={t("finance.receivables.terms.empty")} emptyDescription={t("finance.receivables.terms.hint")}
          toolbar={
            <>
              <FilterTabs value={filter} onChange={setFilter} options={[
                { value: "active", label: t("finance.receivables.terms.isActive") },
                { value: "all", label: t("common.all") },
              ]} />
              {columnFilters.isActive && <Button variant="ghost" size="sm" onClick={columnFilters.reset}>{t("common.clearFilters")}</Button>}
            </>
          } />
      </CardContent>
      {editing !== null && <TermDialog term={editing === "new" ? null : editing} onClose={() => setEditing(null)} />}
    </Card>
  );
}

function SettingsTab() {
  const { session, hasPermission } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const canAdmin = hasPermission("finance.admin_receivables");
  const { data: settings } = useQuery({ queryKey: [...RECEIVABLES_QUERY_KEY, "settings"], queryFn: () => getReceivablesSettings(token) });
  const { data: levelsData } = useQuery({ queryKey: [...RECEIVABLES_QUERY_KEY, "levels"], queryFn: () => getDunningLevels(token) });
  const [form, setForm] = useState({
    block_overdue_days: "", warn_ratio: "90", chase_from: "", company_name: "", company_address: "", company_phone: "",
    company_email: "", company_tax_id: "", company_rccm: "", signatory: "", signatory_title: "",
  });
  const [levels, setLevels] = useState<DunningLevel[]>([]);
  useEffect(() => {
    if (!settings) return;
    setForm({
      block_overdue_days: settings.block_overdue_days === null ? "" : String(settings.block_overdue_days),
      warn_ratio: String(Math.round(Number(settings.warn_ratio) * 100)),
      chase_from: settings.chase_from ?? "",
      company_name: settings.company_name ?? "", company_address: settings.company_address ?? "",
      company_phone: settings.company_phone ?? "", signatory: settings.signatory ?? "",
      company_email: settings.company_email ?? "", company_tax_id: settings.company_tax_id ?? "",
      company_rccm: settings.company_rccm ?? "", signatory_title: settings.signatory_title ?? "",
    });
  }, [settings]);
  useEffect(() => { if (levelsData) setLevels(levelsData); }, [levelsData]);
  const done = () => { void queryClient.invalidateQueries({ queryKey: RECEIVABLES_QUERY_KEY }); toast.success(t("finance.receivables.saved")); };
  const fail = (error: unknown) => toast.error(t("finance.receivables.saveError"), { description: errorText(error) });
  const settingsMutation = useMutation({
    mutationFn: () => saveReceivablesSettings(token, {
      block_overdue_days: form.block_overdue_days === "" ? null : Number(form.block_overdue_days),
      warn_ratio: String(Number(form.warn_ratio) / 100),
      chase_from: form.chase_from || null,
      company_name: form.company_name || null, company_address: form.company_address || null,
      company_phone: form.company_phone || null, signatory: form.signatory || null,
      company_email: form.company_email || null, company_tax_id: form.company_tax_id || null,
      company_rccm: form.company_rccm || null, signatory_title: form.signatory_title || null,
    }),
    onSuccess: done, onError: fail,
  });
  const levelsMutation = useMutation({
    mutationFn: () => saveDunningLevels(token, levels.map(({ level: _level, ...rest }) => ({ ...rest, days_after_due: Number(rest.days_after_due) }))),
    onSuccess: done, onError: fail,
  });
  const updateLevel = (index: number, patch: Partial<DunningLevel>) => setLevels((all) => all.map((l, n) => (n === index ? { ...l, ...patch } : l)));
  const field = (key: keyof typeof form, labelKey: TranslationKey, type = "text") => (
    <div className="space-y-1.5">
      <Label htmlFor={`rs_${key}`}>{t(labelKey)}</Label>
      <Input id={`rs_${key}`} type={type} disabled={!canAdmin} value={form[key]} onChange={(e) => setForm((f) => ({ ...f, [key]: e.target.value }))} />
    </div>
  );
  return (
    <div className="space-y-6">
      <Card>
        <CardHeader><CardTitle>{t("finance.receivables.settings.credit")}</CardTitle></CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-2">
          {field("block_overdue_days", "finance.receivables.settings.blockOverdueDays", "number")}
          {field("warn_ratio", "finance.receivables.settings.warnRatio", "number")}
          <p className="text-xs text-muted-foreground sm:col-span-2">{t("finance.receivables.settings.creditHint")}</p>
          {field("chase_from", "finance.receivables.settings.chaseFrom", "date")}
          <p className="self-end text-xs text-muted-foreground">{t("finance.receivables.settings.chaseFromHint")}</p>
          <h3 className="pt-2 text-sm font-semibold sm:col-span-2">{t("finance.receivables.settings.letterHeader")}</h3>
          {field("company_name", "finance.receivables.settings.companyName")}
          {field("company_address", "finance.receivables.settings.companyAddress")}
          {field("company_phone", "finance.receivables.settings.companyPhone")}
          {field("company_email", "finance.receivables.settings.companyEmail", "email")}
          {field("company_tax_id", "finance.receivables.settings.companyTaxId")}
          {field("company_rccm", "finance.receivables.settings.companyRccm")}
          {field("signatory", "finance.receivables.settings.signatory")}
          {field("signatory_title", "finance.receivables.settings.signatoryTitle")}
          <p className="text-xs text-muted-foreground sm:col-span-2">{t("finance.receivables.settings.letterHeaderHint")}</p>
          {canAdmin && <div className="sm:col-span-2"><Button disabled={settingsMutation.isPending} onClick={() => settingsMutation.mutate()}>{t("common.save")}</Button></div>}
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>{t("finance.receivables.settings.levels")}</CardTitle>
          <p className="text-sm text-muted-foreground">{t("finance.receivables.settings.levelsHint")}</p>
        </CardHeader>
        <CardContent className="space-y-3">
          {levels.map((level, index) => (
            <div key={index} className="grid gap-2 rounded-md border p-3 sm:grid-cols-6">
              <div className="space-y-1"><Label className="text-xs">{t("finance.receivables.settings.daysAfterDue")}</Label>
                <Input type="number" min={1} disabled={!canAdmin} value={level.days_after_due} onChange={(e) => updateLevel(index, { days_after_due: Number(e.target.value) })} /></div>
              <div className="space-y-1 sm:col-span-2"><Label className="text-xs">{t("finance.receivables.terms.nameFr")}</Label>
                <Input disabled={!canAdmin} value={level.name_fr} onChange={(e) => updateLevel(index, { name_fr: e.target.value })} /></div>
              <div className="space-y-1 sm:col-span-2"><Label className="text-xs">{t("finance.receivables.terms.nameEn")}</Label>
                <Input disabled={!canAdmin} value={level.name_en} onChange={(e) => updateLevel(index, { name_en: e.target.value })} /></div>
              <label className="flex items-center gap-2 pt-5 text-sm">
                <Checkbox disabled={!canAdmin} checked={level.blocks_orders} onCheckedChange={(checked) => updateLevel(index, { blocks_orders: checked === true })} />
                {t("finance.receivables.settings.blocksOrders")}
              </label>
              <textarea className="min-h-16 rounded-md border bg-background px-3 py-2 text-sm sm:col-span-3" aria-label={t("finance.receivables.settings.letterFr")}
                        disabled={!canAdmin} value={level.letter_fr} onChange={(e) => updateLevel(index, { letter_fr: e.target.value })} />
              <textarea className="min-h-16 rounded-md border bg-background px-3 py-2 text-sm sm:col-span-3" aria-label={t("finance.receivables.settings.letterEn")}
                        disabled={!canAdmin} value={level.letter_en} onChange={(e) => updateLevel(index, { letter_en: e.target.value })} />
              {canAdmin && levels.length > 1 && (
                <Button variant="ghost" size="sm" className="justify-self-start" onClick={() => setLevels((all) => all.filter((_, n) => n !== index))}>
                  <Trash2 className="h-4 w-4" />{t("finance.receivables.settings.removeLevel")}
                </Button>
              )}
            </div>
          ))}
          {canAdmin && (
            <div className="flex justify-between">
              <Button variant="outline" size="sm" onClick={() => setLevels((all) => [...all, {
                level: all.length + 1, days_after_due: (all[all.length - 1]?.days_after_due ?? 0) + 15, name_fr: "", name_en: "", letter_fr: "", letter_en: "", blocks_orders: false }])}>
                <Plus className="h-4 w-4" />{t("finance.receivables.settings.addLevel")}
              </Button>
              <Button disabled={levelsMutation.isPending} onClick={() => levelsMutation.mutate()}>{t("common.save")}</Button>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

const TABS = [
  { value: "dunning", labelKey: "finance.receivables.tabs.dunning", icon: Mail },
  { value: "aging", labelKey: "finance.receivables.tabs.aging", icon: Hourglass },
  { value: "terms", labelKey: "finance.receivables.tabs.terms", icon: CalendarClock },
  { value: "settings", labelKey: "finance.receivables.tabs.settings", icon: SettingsIcon },
] as const;
type TabValue = (typeof TABS)[number]["value"];

export function ReceivablesPage() {
  const { t } = useI18n();
  const [searchParams, setSearchParams] = useSearchParams();
  const [tab, setTab] = useState<TabValue>("dunning");
  const partnerId = searchParams.get("partner");
  const openAccount = (id: string) => setSearchParams({ partner: id });
  return (
    <div className="space-y-6">
      <motion.div initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25 }}>
        <h1 className="text-xl font-semibold tracking-tight">{t("finance.receivables.title")}</h1>
        <p className="text-sm text-muted-foreground">{t("finance.receivables.subtitle")}</p>
      </motion.div>
      <StickyTabBar>
        <Tabs value={tab} onValueChange={(value) => setTab(value as TabValue)}>
          <TabsList>
            {TABS.map((def) => (
              <TabsTrigger key={def.value} value={def.value} active={tab === def.value} layoutId="receivables-tab-indicator">
                <span className="flex items-center gap-1.5"><def.icon className="h-4 w-4" />{t(def.labelKey)}</span>
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
      </StickyTabBar>
      <AnimatePresence mode="wait">
        <motion.div key={tab} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }} transition={{ duration: 0.2 }}>
          {tab === "dunning" && <WorklistTab openAccount={openAccount} />}
          {tab === "aging" && <AgingTab openAccount={openAccount} />}
          {tab === "terms" && <TermsTab />}
          {tab === "settings" && <SettingsTab />}
        </motion.div>
      </AnimatePresence>
      {partnerId && <CustomerAccountDialog partnerId={partnerId} onClose={() => setSearchParams({})} />}
    </div>
  );
}
