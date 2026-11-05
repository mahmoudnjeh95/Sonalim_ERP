import { Fragment, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Download } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../../lib/auth";
import { ApiError } from "../../lib/api";
import { currentLocale, useI18n } from "../../lib/i18n";
import { Button } from "../../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../../components/ui/table";
import { FilterTabs } from "../../components/patterns/FilterTabs";
import { StatusBadge } from "../../components/patterns/StatusBadge";
import { listPartners } from "../partners/api";
import { downloadInvoiceReport, getInvoiceReport, type ReportInvoice } from "./statementsApi";

const fmt = (value: string) => new Intl.NumberFormat(currentLocale(), { maximumFractionDigits: 0 }).format(Number(value));

function InvoiceRow({ invoice }: { invoice: ReportInvoice }) {
  return (
    <TableRow>
      <TableCell className="pl-8 font-mono text-xs">{invoice.number ?? invoice.invoice_id.slice(-8)}</TableCell>
      <TableCell>{invoice.invoice_date}</TableCell>
      <TableCell className="text-right tabular-nums">{fmt(invoice.amount)}</TableCell>
      <TableCell className="text-right tabular-nums">{fmt(invoice.paid)}</TableCell>
      <TableCell className="text-right tabular-nums">{fmt(invoice.remaining)}</TableCell>
      <TableCell><StatusBadge status={invoice.status} /></TableCell>
    </TableRow>
  );
}

export function InvoiceReportsTab() {
  const { session } = useAuth();
  const { t, language } = useI18n();
  const token = session!.token;
  const [kind, setKind] = useState<"sales" | "purchase">("sales");

  const { data } = useQuery({ queryKey: ["treasury", "invoice-report", kind], queryFn: () => getInvoiceReport(token, kind) });
  const { data: partners = [] } = useQuery({ queryKey: ["core", "partners"], queryFn: () => listPartners(token) });
  const name = (id: string) => partners.find((p) => p.id === id)?.name ?? "—";

  async function download(format: "csv" | "xlsx") {
    try {
      const blob = await downloadInvoiceReport(token, kind, format, language);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `${kind}-invoice-status.${format}`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : t("treasury.reports.exportError"));
    }
  }

  const documentNoun = t(kind === "sales" ? "treasury.reports.ofReceipt" : "treasury.reports.ofDisbursement");
  const noDocument = t(kind === "sales" ? "treasury.reports.noReceipt" : "treasury.reports.noDisbursement");

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center gap-3">
            <CardTitle>{t("treasury.reports.title")}</CardTitle>
            <FilterTabs
              value={kind}
              onChange={setKind}
              options={[
                { value: "sales", label: t("treasury.reports.sales") },
                { value: "purchase", label: t("treasury.reports.purchase") },
              ]}
            />
          </div>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" onClick={() => download("csv")}>
              <Download className="h-3.5 w-3.5" /> CSV
            </Button>
            <Button variant="outline" size="sm" onClick={() => download("xlsx")}>
              <Download className="h-3.5 w-3.5" /> {t("treasury.reports.exportData")}
            </Button>
          </div>
        </CardHeader>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("treasury.column.number")}</TableHead>
                <TableHead>{t("treasury.column.date")}</TableHead>
                <TableHead className="text-right">{t("treasury.reports.invoiced")}</TableHead>
                <TableHead className="text-right">{t("treasury.reports.paid")}</TableHead>
                <TableHead className="text-right">{t("treasury.reports.remaining")}</TableHead>
                <TableHead>{t("treasury.column.status")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {(data?.groups ?? []).map((group) => (
                <Fragment key={group.partner_id}>
                  <TableRow className="bg-muted/60">
                    <TableCell colSpan={6} className="font-semibold">{group.partner_name ?? name(group.partner_id)}</TableCell>
                  </TableRow>
                  {group.documents.map((document) => (
                    <Fragment key={document.document_id}>
                      <TableRow className="bg-muted/30">
                        <TableCell colSpan={6} className="pl-4 text-sm font-medium">
                          {documentNoun} {document.number} ({t("treasury.reports.netToPay")} : {fmt(document.net_to_pay)}, {t("treasury.document.withheld")} : {fmt(document.withheld)})
                        </TableCell>
                      </TableRow>
                      {document.invoices.map((invoice) => <InvoiceRow key={invoice.invoice_id} invoice={invoice} />)}
                    </Fragment>
                  ))}
                  {group.without_document.length > 0 && (
                    <TableRow className="bg-muted/30">
                      <TableCell colSpan={6} className="pl-4 text-sm font-medium">{noDocument}</TableCell>
                    </TableRow>
                  )}
                  {group.without_document.map((invoice) => <InvoiceRow key={invoice.invoice_id} invoice={invoice} />)}
                </Fragment>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t("treasury.reports.aging")}</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("treasury.column.partner")}</TableHead>
                <TableHead className="text-right">{t("treasury.reports.invoiced")}</TableHead>
                <TableHead className="text-right">{t("treasury.reports.paid")}</TableHead>
                <TableHead className="text-right">{t("treasury.reports.remaining")}</TableHead>
                <TableHead className="text-right">0–30</TableHead>
                <TableHead className="text-right">31–60</TableHead>
                <TableHead className="text-right">61–90</TableHead>
                <TableHead className="text-right">90+</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {(data?.partners ?? []).map((p) => (
                <TableRow key={`${p.partner_id}-${p.currency}`}>
                  <TableCell className="font-medium">
                    {name(p.partner_id)} <span className="text-xs text-muted-foreground">{p.currency}</span>
                  </TableCell>
                  <TableCell className="text-right tabular-nums">{fmt(p.invoiced)}</TableCell>
                  <TableCell className="text-right tabular-nums">{fmt(p.paid)}</TableCell>
                  <TableCell className="text-right font-medium tabular-nums">{fmt(p.remaining)}</TableCell>
                  <TableCell className="text-right tabular-nums">{fmt(p["bucket_0-30"])}</TableCell>
                  <TableCell className="text-right tabular-nums">{fmt(p["bucket_31-60"])}</TableCell>
                  <TableCell className="text-right tabular-nums">{fmt(p["bucket_61-90"])}</TableCell>
                  <TableCell className="text-right tabular-nums">{fmt(p["bucket_90+"])}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}
