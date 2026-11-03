import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { BookOpen } from "lucide-react";
import { useAuth } from "../../lib/auth";
import { currentLocale, useI18n } from "../../lib/i18n";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Select } from "../../components/ui/select";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../../components/ui/table";
import { EmptyState } from "../../components/patterns/EmptyState";
import { listAccounts } from "./api";
import { getCashJournal } from "./instrumentsApi";

const fmt = (value: string) => new Intl.NumberFormat(currentLocale(), { maximumFractionDigits: 2 }).format(Number(value));

export function CashJournalTab() {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const [accountId, setAccountId] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");

  const { data: accounts = [] } = useQuery({ queryKey: ["treasury", "accounts"], queryFn: () => listAccounts(token) });
  const cashAccounts = accounts.filter((a) => a.kind === "cash");
  useEffect(() => {
    if (!accountId && cashAccounts.length > 0) setAccountId(cashAccounts[0].id);
  }, [accountId, cashAccounts]);

  const { data: journal } = useQuery({
    queryKey: ["treasury", "cash-journal", accountId, dateFrom, dateTo],
    queryFn: () => getCashJournal(token, accountId, dateFrom || undefined, dateTo || undefined),
    enabled: accountId !== "",
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("treasury.journal.title")}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-3">
          <div className="space-y-1.5">
            <Label htmlFor="j_account">{t("treasury.journal.register")}</Label>
            <Select id="j_account" value={accountId} onChange={(e) => setAccountId(e.target.value)}>
              {cashAccounts.map((a) => (
                <option key={a.id} value={a.id}>{a.name}</option>
              ))}
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="j_from">{t("treasury.journal.from")}</Label>
            <Input id="j_from" type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="j_to">{t("treasury.journal.to")}</Label>
            <Input id="j_to" type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} />
          </div>
        </div>
        {!journal || cashAccounts.length === 0 ? (
          <EmptyState icon={<BookOpen className="h-5 w-5" />} title={t("treasury.journal.empty.title")} description={t("treasury.journal.empty.description")} />
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("treasury.column.date")}</TableHead>
                <TableHead>{t("treasury.journal.label")}</TableHead>
                <TableHead className="text-right">{t("treasury.journal.in")}</TableHead>
                <TableHead className="text-right">{t("treasury.journal.out")}</TableHead>
                <TableHead className="text-right">{t("treasury.column.balance")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              <TableRow>
                <TableCell colSpan={4} className="text-muted-foreground">{t("treasury.journal.opening")}</TableCell>
                <TableCell className="text-right tabular-nums">{fmt(journal.opening_balance)}</TableCell>
              </TableRow>
              {journal.rows.map((row, index) => (
                <TableRow key={index}>
                  <TableCell>{row.date}</TableCell>
                  <TableCell>{row.label}</TableCell>
                  <TableCell className="text-right tabular-nums">{Number(row.money_in) ? fmt(row.money_in) : ""}</TableCell>
                  <TableCell className="text-right tabular-nums">{Number(row.money_out) ? fmt(row.money_out) : ""}</TableCell>
                  <TableCell className="text-right tabular-nums">{fmt(row.balance)}</TableCell>
                </TableRow>
              ))}
              <TableRow>
                <TableCell colSpan={4} className="font-medium">{t("treasury.journal.closing")}</TableCell>
                <TableCell className="text-right font-medium tabular-nums">{fmt(journal.closing_balance)}</TableCell>
              </TableRow>
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}
