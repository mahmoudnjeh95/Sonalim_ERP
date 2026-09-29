import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { BookText } from "lucide-react";
import { useAuth } from "../../lib/auth";
import { useI18n } from "../../lib/i18n";
import { useColumnFilters, type FilterField } from "../../lib/useColumnFilters";
import type { ColumnDef } from "../../lib/useTableColumns";
import { Button } from "../../components/ui/button";
import { Card, CardContent, CardHeader } from "../../components/ui/card";
import { Select } from "../../components/ui/select";
import { DateRangeFilter } from "../../components/patterns/DateRangeFilter";
import { EmptyState } from "../../components/patterns/EmptyState";
import { FilterTabs } from "../../components/patterns/FilterTabs";
import { LedgerTable, rangeFilter, textFilter } from "./LedgerTable";
import { formatAmount, formatAmountCell, formatDate, monthEndIso, yearStartIso } from "./ledgerFormat";
import { LEDGER_KEYS, getGeneralLedger, listAccounts, type GeneralLedgerLine } from "./ledgerApi";

export function GeneralLedgerPage() {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const [searchParams, setSearchParams] = useSearchParams();
  const defaultRange = { from: yearStartIso(), to: monthEndIso() };
  const account = searchParams.get("account") ?? "";
  const from = searchParams.get("from") ?? defaultRange.from;
  const to = searchParams.get("to") ?? defaultRange.to;
  const [journalFilter, setJournalFilter] = useState<string>("all");
  const setParams = (next: { account?: string; from?: string; to?: string }) => {
    const params = new URLSearchParams(searchParams);
    for (const [key, value] of Object.entries(next)) {
      if (value) params.set(key, value);
      else params.delete(key);
    }
    setSearchParams(params, { replace: true });
  };
  const { data: accounts = [] } = useQuery({ queryKey: LEDGER_KEYS.accounts, queryFn: () => listAccounts(token) });
  const { data: ledger, isLoading } = useQuery({
    queryKey: LEDGER_KEYS.generalLedger(account, from, to),
    queryFn: () => getGeneralLedger(token, account, from, to),
    enabled: account !== "",
  });
  const lines = ledger?.lines ?? [];
  const journalCodes = [...new Set(lines.map((line) => line.journal_code))].sort();
  const fields: FilterField<GeneralLedgerLine>[] = [
    { key: "number", kind: "text", getValue: (line) => line.number },
    { key: "label", kind: "text", getValue: (line) => line.label },
    { key: "debit", kind: "range", getValue: (line) => line.debit },
    { key: "credit", kind: "range", getValue: (line) => line.credit },
  ];
  const columnFilters = useColumnFilters(fields);
  const rows = columnFilters.apply(journalFilter === "all" ? lines : lines.filter((line) => line.journal_code === journalFilter));
  const columns: ColumnDef<GeneralLedgerLine>[] = [
    {
      key: "entry_date",
      header: t("finance.entries.column.date"),
      defaultWidth: 110,
      cell: (line) => formatDate(line.entry_date),
      sortValue: (line) => line.entry_date,
    },
    {
      key: "number",
      header: t("finance.entries.column.number"),
      defaultWidth: 170,
      cell: (line) => (
        <Link to={`/finance/entries?entry=${line.entry_id}`} className="font-mono text-primary hover:underline">
          {line.number}
        </Link>
      ),
      filterCell: textFilter(columnFilters, "number", t("finance.entries.column.number")),
      sortValue: (line) => line.number,
    },
    {
      key: "journal_code",
      header: t("finance.entries.column.journal"),
      defaultWidth: 90,
      cell: (line) => <span className="font-mono">{line.journal_code}</span>,
      sortValue: (line) => line.journal_code,
    },
    {
      key: "label",
      header: t("finance.entries.column.label"),
      defaultWidth: 280,
      cell: (line) => line.label,
      filterCell: textFilter(columnFilters, "label", t("finance.entries.column.label")),
      sortValue: (line) => line.label,
    },
    {
      key: "debit",
      header: t("finance.entries.line.debit"),
      defaultWidth: 130,
      headerClassName: "text-right",
      cellClassName: "text-right tabular-nums",
      cell: (line) => formatAmountCell(line.debit),
      filterCell: rangeFilter(columnFilters, "debit"),
      sortValue: (line) => line.debit,
    },
    {
      key: "credit",
      header: t("finance.entries.line.credit"),
      defaultWidth: 130,
      headerClassName: "text-right",
      cellClassName: "text-right tabular-nums",
      cell: (line) => formatAmountCell(line.credit),
      filterCell: rangeFilter(columnFilters, "credit"),
      sortValue: (line) => line.credit,
    },
    {
      key: "balance",
      header: t("finance.generalLedger.balance"),
      defaultWidth: 140,
      headerClassName: "text-right",
      cellClassName: "text-right tabular-nums",
      cell: (line) => formatAmount(line.balance),
    },
  ];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">{t("finance.generalLedger.title")}</h1>
        <p className="text-sm text-muted-foreground">{t("finance.generalLedger.subtitle")}</p>
      </div>
      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center gap-3">
            <div className="w-72">
              <Select value={account} onChange={(event) => setParams({ account: event.target.value })} aria-label={t("finance.generalLedger.account")}>
                <option value="">{t("finance.generalLedger.pickAccount")}</option>
                {accounts
                  .filter((candidate) => candidate.is_postable)
                  .map((candidate) => (
                    <option key={candidate.code} value={candidate.code}>
                      {candidate.code} · {candidate.name}
                    </option>
                  ))}
              </Select>
            </div>
            <DateRangeFilter
              from={from}
              to={to}
              onChange={(range) => setParams({ from: range.from, to: range.to })}
              onReset={() => setParams({ from: "", to: "" })}
              isDefault={from === defaultRange.from && to === defaultRange.to}
            />
          </div>
          {ledger && (
            <div className="grid grid-cols-2 gap-3 pt-3 text-sm sm:grid-cols-4">
              <div>
                <p className="text-muted-foreground">{t("finance.generalLedger.opening")}</p>
                <p className="font-semibold tabular-nums">{formatAmount(ledger.opening_balance)}</p>
              </div>
              <div>
                <p className="text-muted-foreground">{t("finance.generalLedger.totalDebit")}</p>
                <p className="font-semibold tabular-nums">{formatAmount(ledger.total_debit)}</p>
              </div>
              <div>
                <p className="text-muted-foreground">{t("finance.generalLedger.totalCredit")}</p>
                <p className="font-semibold tabular-nums">{formatAmount(ledger.total_credit)}</p>
              </div>
              <div>
                <p className="text-muted-foreground">{t("finance.generalLedger.closing")}</p>
                <p className="font-semibold tabular-nums">{formatAmount(ledger.closing_balance)}</p>
              </div>
            </div>
          )}
        </CardHeader>
        <CardContent className="p-0 pb-2">
          {account === "" ? (
            <EmptyState
              icon={<BookText className="h-5 w-5" />}
              title={t("finance.generalLedger.pickAccount")}
              description={t("finance.generalLedger.pickAccountHint")}
            />
          ) : (
            <LedgerTable
              tableKey="finance.generalLedger"
              columns={columns}
              rows={rows}
              rowKey={(line) => `${line.entry_id}-${line.number}-${line.debit}-${line.credit}-${line.balance}`}
              isLoading={isLoading}
              emptyIcon={<BookText className="h-5 w-5" />}
              emptyTitle={t("finance.generalLedger.emptyTitle")}
              emptyDescription={t("finance.generalLedger.emptyDescription")}
              toolbar={
                <>
                  <FilterTabs
                    value={journalFilter}
                    onChange={setJournalFilter}
                    options={[{ value: "all", label: t("common.all") }, ...journalCodes.map((code) => ({ value: code, label: code }))]}
                  />
                  {columnFilters.isActive && (
                    <Button variant="ghost" size="sm" onClick={columnFilters.reset}>
                      {t("common.clearFilters")}
                    </Button>
                  )}
                </>
              }
            />
          )}
        </CardContent>
      </Card>
    </div>
  );
}
