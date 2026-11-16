import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { BookOpen } from "lucide-react";
import { useAuth } from "../../lib/auth";
import { currentLocale, useI18n } from "../../lib/i18n";
import { Label } from "../../components/ui/label";
import { Select } from "../../components/ui/select";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../../components/ui/table";
import { EmptyState } from "../../components/patterns/EmptyState";
import { listAccounts } from "./api";
import { getCashJournal, type CashJournalRow } from "./instrumentsApi";

const fmt = (value: string) => new Intl.NumberFormat(currentLocale(), { maximumFractionDigits: 2 }).format(Number(value));
const YEARS_SHOWN = 6;

export function CashJournalTab() {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const thisYear = new Date().getFullYear();
  const [year, setYear] = useState(thisYear);
  const [accountId, setAccountId] = useState("");

  const { data: accounts = [] } = useQuery({ queryKey: ["treasury", "accounts"], queryFn: () => listAccounts(token) });
  const cashAccounts = accounts.filter((a) => a.kind === "cash");

  const { data: journal } = useQuery({
    queryKey: ["treasury", "cash-journal", year, accountId],
    queryFn: () => getCashJournal(token, year, accountId || undefined),
  });

  const label = (row: CashJournalRow) => {
    if (!row.document_number) return row.label;
    return `${t(row.direction === "in" ? "treasury.journal.receiptNo" : "treasury.journal.disbursementNo")} ${row.document_number}`;
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("treasury.journal.title")}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-3">
          <div className="space-y-1.5">
            <Label htmlFor="j_year">{t("treasury.journal.year")}</Label>
            <Select id="j_year" value={String(year)} onChange={(e) => setYear(Number(e.target.value))}>
              {Array.from({ length: YEARS_SHOWN }, (_, offset) => thisYear - offset).map((y) => (
                <option key={y} value={y}>{y}</option>
              ))}
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="j_account">{t("treasury.journal.register")}</Label>
            <Select id="j_account" value={accountId} onChange={(e) => setAccountId(e.target.value)}>
              <option value="">{t("treasury.journal.allRegisters")}</option>
              {cashAccounts.map((a) => (
                <option key={a.id} value={a.id}>{a.name}</option>
              ))}
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label>{t("treasury.journal.opening")}</Label>
            <p className="pt-2 font-medium tabular-nums">{journal ? fmt(journal.opening_balance) : "—"}</p>
          </div>
        </div>
        {!journal || journal.rows.length === 0 ? (
          <EmptyState icon={<BookOpen className="h-5 w-5" />} title={t("treasury.journal.empty.title")} description={t("treasury.journal.empty.description")} />
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("treasury.column.date")}</TableHead>
                <TableHead>{t("treasury.journal.register")}</TableHead>
                <TableHead>{t("treasury.journal.label")}</TableHead>
                <TableHead className="text-right">{t("treasury.journal.in")}</TableHead>
                <TableHead className="text-right">{t("treasury.journal.out")}</TableHead>
                <TableHead className="text-right">{t("treasury.journal.finalBalance")}</TableHead>
                <TableHead>{t("treasury.column.partner")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {journal.rows.map((row, index) => (
                <TableRow key={index}>
                  <TableCell>{row.date}</TableCell>
                  <TableCell>{row.account_name}</TableCell>
                  <TableCell>{label(row)}</TableCell>
                  <TableCell className="text-right tabular-nums">{fmt(row.money_in)}</TableCell>
                  <TableCell className="text-right tabular-nums">{fmt(row.money_out)}</TableCell>
                  <TableCell className="text-right tabular-nums">{fmt(row.balance)}</TableCell>
                  <TableCell>{row.partner_name ?? "—"}</TableCell>
                </TableRow>
              ))}
              <TableRow>
                <TableCell colSpan={5} className="font-medium">{t("treasury.journal.closing")}</TableCell>
                <TableCell className="text-right font-medium tabular-nums">{fmt(journal.closing_balance)}</TableCell>
                <TableCell />
              </TableRow>
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}
