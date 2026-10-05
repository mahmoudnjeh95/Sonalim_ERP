import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Scale } from "lucide-react";
import { useAuth } from "../../lib/auth";
import { useI18n } from "../../lib/i18n";
import { useColumnFilters, type FilterField } from "../../lib/useColumnFilters";
import type { ColumnDef } from "../../lib/useTableColumns";
import { Button } from "../../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { DateRangeFilter } from "../../components/patterns/DateRangeFilter";
import { FilterTabs } from "../../components/patterns/FilterTabs";
import { LedgerTable, rangeFilter, textFilter } from "./LedgerTable";
import { formatAmount, formatAmountCell, monthEndIso, yearStartIso } from "./ledgerFormat";
import {
  LEDGER_KEYS,
  getBalances,
  getTrialBalance,
  type AccountBalance,
  type TrialBalanceAmounts,
  type TrialBalanceRow,
} from "./ledgerApi";

const AMOUNT_KEYS: (keyof TrialBalanceAmounts)[] = [
  "opening_debit",
  "opening_credit",
  "period_debit",
  "period_credit",
  "closing_debit",
  "closing_credit",
];

export function TrialBalancePage() {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const navigate = useNavigate();
  const defaultRange = { from: yearStartIso(), to: monthEndIso() };
  const [range, setRange] = useState(defaultRange);
  const [classFilter, setClassFilter] = useState<string>("all");
  const { data, isLoading } = useQuery({
    queryKey: LEDGER_KEYS.trialBalance(range.from, range.to),
    queryFn: () => getTrialBalance(token, range.from, range.to),
  });
  const allRows = data?.rows ?? [];
  const classes = [...new Set(allRows.map((row) => String(row.class_no)))].sort();

  const fields: FilterField<TrialBalanceRow>[] = [
    { key: "account_code", kind: "text", getValue: (row) => row.account_code },
    { key: "account_name", kind: "text", getValue: (row) => row.account_name },
    { key: "closing_debit", kind: "range", getValue: (row) => row.closing_debit },
    { key: "closing_credit", kind: "range", getValue: (row) => row.closing_credit },
  ];
  const columnFilters = useColumnFilters(fields);
  const rows = columnFilters.apply(classFilter === "all" ? allRows : allRows.filter((row) => String(row.class_no) === classFilter));
  // Totals of the rows shown, so a filtered view still adds up; unfiltered they equal the server's totals.
  const totals = Object.fromEntries(AMOUNT_KEYS.map((key) => [key, rows.reduce((sum, row) => sum + row[key], 0)])) as Record<
    keyof TrialBalanceAmounts,
    number
  >;

  const amountColumn = (key: keyof TrialBalanceAmounts, header: string, withFilter = false): ColumnDef<TrialBalanceRow> => ({
    key,
    header,
    defaultWidth: 130,
    headerClassName: "text-right",
    cellClassName: "text-right tabular-nums",
    cell: (row) => formatAmountCell(row[key]),
    filterCell: withFilter ? rangeFilter(columnFilters, key) : undefined,
    sortValue: (row) => row[key],
  });
  const columns: ColumnDef<TrialBalanceRow>[] = [
    {
      key: "account_code",
      header: t("finance.accounts.column.code"),
      defaultWidth: 110,
      cell: (row) => (
        <button
          type="button"
          className="font-mono text-primary hover:underline"
          onClick={() => navigate(`/finance/ledger?account=${row.account_code}&from=${range.from}&to=${range.to}`)}
        >
          {row.account_code}
        </button>
      ),
      filterCell: textFilter(columnFilters, "account_code", t("finance.accounts.column.code")),
      sortValue: (row) => row.account_code,
    },
    {
      key: "account_name",
      header: t("finance.accounts.column.name"),
      defaultWidth: 280,
      cell: (row) => row.account_name,
      filterCell: textFilter(columnFilters, "account_name", t("finance.accounts.column.name")),
      sortValue: (row) => row.account_name,
    },
    amountColumn("opening_debit", t("finance.trialBalance.openingDebit")),
    amountColumn("opening_credit", t("finance.trialBalance.openingCredit")),
    amountColumn("period_debit", t("finance.trialBalance.periodDebit")),
    amountColumn("period_credit", t("finance.trialBalance.periodCredit")),
    amountColumn("closing_debit", t("finance.trialBalance.closingDebit"), true),
    amountColumn("closing_credit", t("finance.trialBalance.closingCredit"), true),
  ];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">{t("finance.trialBalance.title")}</h1>
        <p className="text-sm text-muted-foreground">{t("finance.trialBalance.subtitle")}</p>
      </div>
      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center gap-3">
            <CardTitle>{t("finance.trialBalance.tableTitle")}</CardTitle>
            <DateRangeFilter
              from={range.from}
              to={range.to}
              onChange={setRange}
              onReset={() => setRange(defaultRange)}
              isDefault={range.from === defaultRange.from && range.to === defaultRange.to}
            />
          </div>
        </CardHeader>
        <CardContent className="p-0 pb-2">
          <LedgerTable
            tableKey="finance.trialBalance"
            columns={columns}
            rows={rows}
            rowKey={(row) => row.account_code}
            isLoading={isLoading}
            emptyIcon={<Scale className="h-5 w-5" />}
            emptyTitle={t("finance.trialBalance.emptyTitle")}
            emptyDescription={t("finance.trialBalance.emptyDescription")}
            footer={(key) =>
              key === "account_name"
                ? t("finance.entries.total")
                : AMOUNT_KEYS.includes(key as keyof TrialBalanceAmounts)
                  ? formatAmount(totals[key as keyof TrialBalanceAmounts])
                  : ""
            }
            toolbar={
              <>
                <FilterTabs
                  value={classFilter}
                  onChange={setClassFilter}
                  options={[
                    { value: "all", label: t("common.all") },
                    ...classes.map((classNo) => ({ value: classNo, label: `${t("finance.accounts.classShort")} ${classNo}` })),
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
      <BalancesCard asOf={range.to} />
    </div>
  );
}

const GROUPS = ["42", "43", "44"] as const;

function BalancesCard({ asOf }: { asOf: string }) {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const [group, setGroup] = useState<"all" | (typeof GROUPS)[number]>("all");
  const { data: balances = [], isLoading } = useQuery({ queryKey: LEDGER_KEYS.balances(asOf), queryFn: () => getBalances(token, asOf) });
  const fields: FilterField<AccountBalance>[] = [
    { key: "account_code", kind: "text", getValue: (row) => row.account_code },
    { key: "account_name", kind: "text", getValue: (row) => row.account_name },
    { key: "owed", kind: "range", getValue: (row) => row.owed },
  ];
  const columnFilters = useColumnFilters(fields);
  const rows = columnFilters.apply(group === "all" ? balances : balances.filter((row) => row.account_code.startsWith(group)));
  const columns: ColumnDef<AccountBalance>[] = [
    {
      key: "account_code",
      header: t("finance.accounts.column.code"),
      defaultWidth: 110,
      cell: (row) => <span className="font-mono">{row.account_code}</span>,
      filterCell: textFilter(columnFilters, "account_code", t("finance.accounts.column.code")),
      sortValue: (row) => row.account_code,
    },
    {
      key: "account_name",
      header: t("finance.accounts.column.name"),
      defaultWidth: 300,
      cell: (row) => row.account_name,
      filterCell: textFilter(columnFilters, "account_name", t("finance.accounts.column.name")),
      sortValue: (row) => row.account_name,
    },
    {
      key: "debit",
      header: t("finance.entries.line.debit"),
      defaultWidth: 130,
      headerClassName: "text-right",
      cellClassName: "text-right tabular-nums",
      cell: (row) => formatAmountCell(row.debit),
      sortValue: (row) => row.debit,
    },
    {
      key: "credit",
      header: t("finance.entries.line.credit"),
      defaultWidth: 130,
      headerClassName: "text-right",
      cellClassName: "text-right tabular-nums",
      cell: (row) => formatAmountCell(row.credit),
      sortValue: (row) => row.credit,
    },
    {
      key: "owed",
      header: t("finance.balances.owed"),
      defaultWidth: 150,
      headerClassName: "text-right",
      cellClassName: "text-right tabular-nums font-medium",
      cell: (row) => formatAmount(row.owed),
      filterCell: rangeFilter(columnFilters, "owed"),
      sortValue: (row) => row.owed,
    },
  ];
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("finance.balances.title")}</CardTitle>
        <p className="text-sm text-muted-foreground">{t("finance.balances.subtitle")}</p>
      </CardHeader>
      <CardContent className="p-0 pb-2">
        <LedgerTable
          tableKey="finance.balances"
          columns={columns}
          rows={rows}
          rowKey={(row) => row.account_code}
          isLoading={isLoading}
          loading="skeleton"
          emptyIcon={<Scale className="h-5 w-5" />}
          emptyTitle={t("finance.balances.emptyTitle")}
          emptyDescription={t("finance.balances.emptyDescription")}
          footer={(key) => (key === "account_name" ? t("finance.entries.total") : key === "owed" ? formatAmount(rows.reduce((sum, row) => sum + row.owed, 0)) : "")}
          toolbar={
            <>
              <FilterTabs
                value={group}
                onChange={setGroup}
                options={[
                  { value: "all", label: t("common.all") },
                  { value: "42", label: t("finance.balances.group42") },
                  { value: "43", label: t("finance.balances.group43") },
                  { value: "44", label: t("finance.balances.group44") },
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
