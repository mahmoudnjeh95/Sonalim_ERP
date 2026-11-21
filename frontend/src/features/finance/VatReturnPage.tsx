import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useI18n } from "../../lib/i18n";
import { useAuth } from "../../lib/auth";
import { Badge } from "../../components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../../components/ui/table";
import { DateRangeFilter } from "../../components/patterns/DateRangeFilter";
import { formatAmount, monthEndIso, monthStartIso } from "./ledgerFormat";
import { VAT_RETURN_KEY, getVatReturn, type VatReturn, type VatReturnRow } from "./ledgerApi";

/** The VAT return of a period: collected and deductible VAT per tax code, the net due, and a check against the ledger. */
export function VatReturnPage() {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const defaultRange = { from: monthStartIso(), to: monthEndIso() };
  const [range, setRange] = useState(defaultRange);
  const { data, isLoading } = useQuery({
    queryKey: VAT_RETURN_KEY(range.from, range.to),
    queryFn: () => getVatReturn(token, range.from, range.to),
  });
  const net = data?.net_vat_due ?? 0;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">{t("finance.vat.title")}</h1>
          <p className="text-sm text-muted-foreground">{t("finance.vat.subtitle")}</p>
        </div>
        <DateRangeFilter
          from={range.from}
          to={range.to}
          onChange={setRange}
          onReset={() => setRange(defaultRange)}
          isDefault={range.from === defaultRange.from && range.to === defaultRange.to}
        />
      </div>

      <div className="grid gap-3 sm:grid-cols-3">
        <Stat label={t("finance.vat.collected")} value={data?.totals.collected.vat} />
        <Stat label={t("finance.vat.deductible")} value={data?.totals.deductible.vat} />
        <Stat label={net >= 0 ? t("finance.vat.netDue") : t("finance.vat.credit")} value={data ? Math.abs(net) : undefined} strong />
      </div>

      <Section title={t("finance.vat.collectedTitle")} rows={data?.collected} totals={data?.totals.collected} isLoading={isLoading} />
      <Section title={t("finance.vat.deductibleTitle")} rows={data?.deductible} totals={data?.totals.deductible} isLoading={isLoading} />
      {data && <LedgerCheck report={data} />}
    </div>
  );
}

function Stat({ label, value, strong }: { label: string; value: number | undefined; strong?: boolean }) {
  return (
    <Card>
      <CardContent className="space-y-1 p-4">
        <p className="text-sm text-muted-foreground">{label}</p>
        <p className={`tabular-nums ${strong ? "text-2xl font-semibold" : "text-xl font-medium"}`}>
          {value === undefined ? "—" : `${formatAmount(value)} F CFA`}
        </p>
      </CardContent>
    </Card>
  );
}

function Section({
  title,
  rows,
  totals,
  isLoading,
}: {
  title: string;
  rows: VatReturnRow[] | undefined;
  totals: { base: number; vat: number } | undefined;
  isLoading: boolean;
}) {
  const { t } = useI18n();
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
      </CardHeader>
      <CardContent className="p-0 pb-2">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t("taxes.column.code")}</TableHead>
              <TableHead className="text-right">{t("taxes.column.rate")}</TableHead>
              <TableHead className="text-right">{t("finance.vat.base")}</TableHead>
              <TableHead className="text-right">{t("finance.vat.vat")}</TableHead>
              <TableHead className="text-right">{t("finance.vat.documents")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading && (
              <TableRow>
                <TableCell colSpan={5} className="text-muted-foreground">
                  {t("taxes.loading")}
                </TableCell>
              </TableRow>
            )}
            {!isLoading && !rows?.length && (
              <TableRow>
                <TableCell colSpan={5} className="text-muted-foreground">
                  {t("finance.vat.empty")}
                </TableCell>
              </TableRow>
            )}
            {rows?.map((row) => (
              <TableRow key={`${row.tax_code ?? "-"}:${row.rate ?? "-"}`}>
                <TableCell>
                  <span className="font-mono">{row.tax_code ?? t("finance.vat.noCode")}</span>
                  {row.exempt && (
                    <Badge variant="outline" className="ml-2">
                      {t("taxes.exempt")}
                    </Badge>
                  )}
                </TableCell>
                <TableCell className="text-right tabular-nums">{row.rate === null ? "—" : `${row.rate} %`}</TableCell>
                <TableCell className="text-right tabular-nums">{formatAmount(row.base)}</TableCell>
                <TableCell className="text-right tabular-nums">{formatAmount(row.vat)}</TableCell>
                <TableCell className="text-right tabular-nums">{row.documents}</TableCell>
              </TableRow>
            ))}
            {totals && !!rows?.length && (
              <TableRow className="font-medium">
                <TableCell colSpan={2}>{t("finance.entries.total")}</TableCell>
                <TableCell className="text-right tabular-nums">{formatAmount(totals.base)}</TableCell>
                <TableCell className="text-right tabular-nums">{formatAmount(totals.vat)}</TableCell>
                <TableCell />
              </TableRow>
            )}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}

function LedgerCheck({ report }: { report: VatReturn }) {
  const { t } = useI18n();
  const directions = ["collected", "deductible"] as const;
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("finance.vat.ledgerTitle")}</CardTitle>
        <p className="text-sm text-muted-foreground">{t("finance.vat.ledgerHint")}</p>
      </CardHeader>
      <CardContent className="p-0 pb-2">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead />
              <TableHead>{t("finance.vat.accounts")}</TableHead>
              <TableHead className="text-right">{t("finance.vat.register")}</TableHead>
              <TableHead className="text-right">{t("finance.vat.ledger")}</TableHead>
              <TableHead className="text-right">{t("finance.vat.difference")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {directions.map((direction) => {
              const check = report.ledger[direction];
              return (
                <TableRow key={direction}>
                  <TableCell>{t(direction === "collected" ? "finance.vat.collected" : "finance.vat.deductible")}</TableCell>
                  <TableCell className="font-mono">{check.accounts.join(", ") || "—"}</TableCell>
                  <TableCell className="text-right tabular-nums">{formatAmount(report.totals[direction].vat)}</TableCell>
                  <TableCell className="text-right tabular-nums">{formatAmount(check.movement)}</TableCell>
                  <TableCell className={`text-right tabular-nums ${check.difference ? "text-amber-700 dark:text-amber-400" : ""}`}>
                    {formatAmount(check.difference)}
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}
