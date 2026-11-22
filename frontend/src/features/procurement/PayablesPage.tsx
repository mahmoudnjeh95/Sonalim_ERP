import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { FileSpreadsheet, Landmark } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../../lib/auth";
import { useI18n } from "../../lib/i18n";
import { ApiError } from "../../lib/api";
import { Button } from "../../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../../components/ui/table";
import { EmptyState } from "../../components/patterns/EmptyState";
import { TableLoadingRow } from "../../components/patterns/AppLoader";
import { formatXof } from "./invoiceFormat";
import { PAYABLES_KEY, exportPayablesAging, getPayablesAging, getSupplierStatement } from "./invoicesApi";

const BUCKETS = ["not_due", "1_30", "31_60", "61_90", "over_90"] as const;

export function PayablesPage() {
  const { session } = useAuth();
  const { t, language } = useI18n();
  const token = session!.token;
  const [partnerId, setPartnerId] = useState<string | null>(null);

  const aging = useQuery({ queryKey: [...PAYABLES_KEY, "aging"], queryFn: () => getPayablesAging(token) });
  const statement = useQuery({
    queryKey: [...PAYABLES_KEY, "statement", partnerId],
    queryFn: () => getSupplierStatement(token, partnerId!),
    enabled: partnerId !== null,
  });
  const rows = aging.data ?? [];
  const total = rows.reduce((sum, row) => sum + Number(row.remaining), 0);
  const overdue = rows.reduce((sum, row) => sum + Number(row.overdue), 0);

  async function exportAging(format: "csv" | "xlsx") {
    try {
      const blob = await exportPayablesAging(token, format, language);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `payables-aging.${format}`;
      link.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      toast.error(t("payables.exportError"), { description: error instanceof ApiError ? error.message : undefined });
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">{t("payables.title")}</h1>
          <p className="text-sm text-muted-foreground">{t("payables.subtitle")}</p>
        </div>
        <Button variant="outline" onClick={() => exportAging("xlsx")} disabled={rows.length === 0}>
          <FileSpreadsheet className="mr-2 h-4 w-4" /> {t("payables.export")}
        </Button>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <Card><CardHeader><CardTitle className="text-sm">{t("payables.totalOwed")}</CardTitle></CardHeader>
          <CardContent className="text-2xl font-semibold">{formatXof(total)}</CardContent></Card>
        <Card><CardHeader><CardTitle className="text-sm">{t("payables.totalOverdue")}</CardTitle></CardHeader>
          <CardContent className="text-2xl font-semibold text-destructive">{formatXof(overdue)}</CardContent></Card>
      </div>

      <Card>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("payables.column.supplier")}</TableHead>
                <TableHead className="text-right">{t("payables.column.remaining")}</TableHead>
                {BUCKETS.map((bucket) => (
                  <TableHead key={bucket} className="text-right">{t(`payables.bucket.${bucket}`)}</TableHead>
                ))}
                <TableHead className="text-right">{t("payables.column.maxDays")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {aging.isLoading ? (
                <TableLoadingRow colSpan={8} />
              ) : rows.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={8}>
                    <EmptyState icon={<Landmark className="h-5 w-5" />} title={t("payables.empty.title")} description={t("payables.empty.description")} />
                  </TableCell>
                </TableRow>
              ) : (
                rows.map((row) => (
                  <TableRow key={row.partner_id} className="cursor-pointer" data-state={row.partner_id === partnerId ? "selected" : undefined}
                    onClick={() => setPartnerId(row.partner_id)}>
                    <TableCell className="font-medium">{row.partner_name ?? row.partner_id}</TableCell>
                    <TableCell className="text-right">{formatXof(row.remaining)}</TableCell>
                    {BUCKETS.map((bucket) => (
                      <TableCell key={bucket} className="text-right">{formatXof(row[`bucket_${bucket}`])}</TableCell>
                    ))}
                    <TableCell className="text-right">{row.max_days_overdue}</TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {partnerId && (
        <Card>
          <CardHeader>
            <CardTitle>{t("payables.statement.title")} {statement.data?.partner_name ?? ""}</CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t("payables.statement.date")}</TableHead>
                  <TableHead>{t("payables.statement.document")}</TableHead>
                  <TableHead className="text-right">{t("payables.statement.paidOrCredited")}</TableHead>
                  <TableHead className="text-right">{t("payables.statement.invoiced")}</TableHead>
                  <TableHead className="text-right">{t("payables.statement.balance")}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {statement.isLoading ? (
                  <TableLoadingRow colSpan={5} />
                ) : (
                  <>
                    <TableRow>
                      <TableCell colSpan={4} className="text-muted-foreground">{t("payables.statement.opening")}</TableCell>
                      <TableCell className="text-right">{formatXof(statement.data?.opening_balance)}</TableCell>
                    </TableRow>
                    {(statement.data?.lines ?? []).map((line, index) => (
                      <TableRow key={index}>
                        <TableCell>{line.date}</TableCell>
                        <TableCell>
                          {t(`payables.kind.${line.kind}`)} {line.reference}
                          {line.against ? <span className="text-muted-foreground"> · {line.against}</span> : null}
                        </TableCell>
                        <TableCell className="text-right">{Number(line.debit) ? formatXof(line.debit) : ""}</TableCell>
                        <TableCell className="text-right">{Number(line.credit) ? formatXof(line.credit) : ""}</TableCell>
                        <TableCell className="text-right">{formatXof(line.balance)}</TableCell>
                      </TableRow>
                    ))}
                  </>
                )}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
