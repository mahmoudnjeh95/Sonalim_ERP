import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { FileSpreadsheet, FileText, PackageCheck, Plus, Settings2 } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../../lib/auth";
import { useI18n } from "../../lib/i18n";
import { ApiError } from "../../lib/api";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Select } from "../../components/ui/select";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { Table, TableHeader, TableBody, TableRow, TableCell, ResizableTableHead } from "../../components/ui/table";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "../../components/ui/dialog";
import { EmptyState } from "../../components/patterns/EmptyState";
import { StatusBadge } from "../../components/patterns/StatusBadge";
import { FilterTabs } from "../../components/patterns/FilterTabs";
import { ColumnFilterRow } from "../../components/patterns/ColumnFilterRow";
import { TableLoadingRow } from "../../components/patterns/AppLoader";
import { useColumnFilters, type FilterField } from "../../lib/useColumnFilters";
import { useTableColumns, type ColumnDef } from "../../lib/useTableColumns";
import { listPartners } from "../partners/api";
import { LedgerStatusBadge, LedgerStatusFilterTabs, matchesLedgerFilter, useLedgerStatuses, type LedgerStatusFilter } from "../finance/ledgerStatus";
import { PRODUCTS_QUERY_KEY } from "../products/catalog";
import { listProducts } from "../warehouse/api";
import { FromReceiptsDialog } from "./FromReceiptsDialog";
import { PurchaseInvoiceDetailDialog, PURCHASE_INVOICES_KEY } from "./PurchaseInvoiceDetailDialog";
import { PurchaseInvoiceFormDialog } from "./PurchaseInvoiceFormDialog";
import { formatXof } from "./invoiceFormat";
import {
  exportPurchaseInvoices,
  getInvoiceSettings,
  listPurchaseInvoices,
  setDefaultVatRate,
  type InvoiceFilters,
  type PurchaseInvoice,
  type PurchaseInvoiceDetail,
  type PurchaseInvoiceStatus,
} from "./invoicesApi";

type StatusFilter = "all" | "overdue" | PurchaseInvoiceStatus;
const SETTINGS_KEY = ["procurement", "purchase-invoice-settings"] as const;

function isOverdue(invoice: PurchaseInvoice) {
  return (
    (invoice.status === "validated" || invoice.status === "partially_paid") &&
    invoice.due_date !== null &&
    invoice.due_date < new Date().toISOString().slice(0, 10)
  );
}

export function PurchaseInvoicesPage() {
  const { session, hasPermission } = useAuth();
  const { t, language } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const canManage = hasPermission("procurement.manage_purchase_invoices");
  const canConfigure = hasPermission("procurement.admin_purchase_invoices");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [supplierFilter, setSupplierFilter] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<PurchaseInvoiceDetail | null>(null);
  const [receiptsOpen, setReceiptsOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [detailId, setDetailId] = useState<string | null>(null);

  const filters: InvoiceFilters = {
    partner_id: supplierFilter || undefined,
    date_from: dateFrom || undefined,
    date_to: dateTo || undefined,
    status: statusFilter !== "all" && statusFilter !== "overdue" ? statusFilter : undefined,
    overdue: statusFilter === "overdue" || undefined,
  };
  const { data: invoices = [], isLoading } = useQuery({
    queryKey: [...PURCHASE_INVOICES_KEY, "list", supplierFilter, dateFrom, dateTo],
    queryFn: () => listPurchaseInvoices(token, { partner_id: filters.partner_id, date_from: filters.date_from, date_to: filters.date_to }),
  });
  const { data: partners = [] } = useQuery({ queryKey: ["core", "partners"], queryFn: () => listPartners(token) });
  const { data: products = [] } = useQuery({ queryKey: PRODUCTS_QUERY_KEY, queryFn: () => listProducts(token), enabled: canManage });
  const { data: settings } = useQuery({ queryKey: SETTINGS_KEY, queryFn: () => getInvoiceSettings(token) });
  const defaultVat = Number(settings?.default_vat_rate ?? 18);
  const suppliers = partners.filter((p) => p.status === "active" && p.kind !== "customer");
  const partnerName = (id: string) => partners.find((p) => p.id === id)?.name ?? "—";

  async function exportList(format: "csv" | "xlsx") {
    try {
      const blob = await exportPurchaseInvoices(token, format, language, filters);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `${language === "en" ? "purchase-invoices" : "factures-achat"}.${format}`;
      link.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      toast.error(t("purchaseInvoice.exportError"), { description: error instanceof ApiError ? error.message : undefined });
    }
  }

  const ledgerStatuses = useLedgerStatuses("procurement", invoices.map((i) => i.id));
  const [ledgerFilter, setLedgerFilter] = useState<LedgerStatusFilter>("all");
  const statusFiltered = (
    statusFilter === "all"
      ? invoices
      : statusFilter === "overdue"
        ? invoices.filter(isOverdue)
        : invoices.filter((i) => i.status === statusFilter)
  ).filter((i) => matchesLedgerFilter(ledgerFilter, ledgerStatuses[i.id]));

  const filterFields: FilterField<PurchaseInvoice>[] = [
    { key: "number", kind: "text", getValue: (i) => i.number ?? "" },
    { key: "partner_id", kind: "text", getValue: (i) => partnerName(i.partner_id) },
    { key: "supplier_invoice_number", kind: "text", getValue: (i) => i.supplier_invoice_number },
    { key: "total_incl_tax", kind: "range", getValue: (i) => Number(i.total_incl_tax) },
    { key: "remaining", kind: "range", getValue: (i) => Number(i.remaining) },
  ];
  const columnFilters = useColumnFilters(filterFields);
  const filtered = columnFilters.apply(statusFiltered);

  const textFilter = (key: string, placeholder: string) => ({
    type: "text" as const,
    value: columnFilters.text[key] ?? "",
    onChange: (v: string) => columnFilters.setTextValue(key, v),
    placeholder,
  });
  const rangeFilter = (key: string) => ({
    type: "range" as const,
    min: columnFilters.range[key]?.min ?? "",
    max: columnFilters.range[key]?.max ?? "",
    onMinChange: (v: string) => columnFilters.setRangeValue(key, "min", v),
    onMaxChange: (v: string) => columnFilters.setRangeValue(key, "max", v),
  });

  const columns: ColumnDef<PurchaseInvoice>[] = [
    {
      key: "number",
      header: t("purchaseInvoice.column.number"),
      defaultWidth: 140,
      cell: (i) => <span className="font-mono text-xs">{i.number ?? "—"}</span>,
      filterCell: textFilter("number", t("purchaseInvoice.column.number")),
      sortValue: (i) => i.number ?? "",
    },
    {
      key: "partner_id",
      header: t("purchaseInvoice.column.supplier"),
      defaultWidth: 180,
      cell: (i) => <span className="font-medium">{partnerName(i.partner_id)}</span>,
      filterCell: textFilter("partner_id", t("purchaseInvoice.column.supplier")),
      sortValue: (i) => partnerName(i.partner_id),
    },
    {
      key: "supplier_invoice_number",
      header: t("purchaseInvoice.column.supplierRef"),
      defaultWidth: 150,
      cell: (i) => i.supplier_invoice_number,
      filterCell: textFilter("supplier_invoice_number", t("purchaseInvoice.column.supplierRef")),
      sortValue: (i) => i.supplier_invoice_number,
    },
    {
      key: "invoice_date",
      header: t("purchaseInvoice.field.invoiceDate"),
      defaultWidth: 120,
      cell: (i) => i.invoice_date,
      sortValue: (i) => i.invoice_date,
    },
    {
      key: "due_date",
      header: t("purchaseInvoice.column.dueDate"),
      defaultWidth: 130,
      cell: (i) => (
        <span className={isOverdue(i) ? "font-medium text-destructive" : undefined}>
          {i.due_date ?? "—"}
          {isOverdue(i) && ` · ${t("purchaseInvoice.overdue")}`}
        </span>
      ),
      sortValue: (i) => i.due_date ?? "",
    },
    {
      key: "total_incl_tax",
      header: t("purchaseInvoice.total.incl"),
      defaultWidth: 140,
      headerClassName: "text-right",
      cellClassName: "text-right",
      cell: (i) => <span className="tabular-nums">{formatXof(i.total_incl_tax)}</span>,
      filterCell: rangeFilter("total_incl_tax"),
      sortValue: (i) => Number(i.total_incl_tax),
    },
    {
      key: "remaining",
      header: t("purchaseInvoice.column.remaining"),
      defaultWidth: 140,
      headerClassName: "text-right",
      cellClassName: "text-right",
      cell: (i) => (
        <span className="tabular-nums">
          {formatXof(i.remaining)}
          {Number(i.supplier_credit) > 0 && (
            <span className="block text-xs text-amber-700 dark:text-amber-300">
              {t("purchaseInvoice.total.supplierCredit")} {formatXof(i.supplier_credit)}
            </span>
          )}
        </span>
      ),
      filterCell: rangeFilter("remaining"),
      sortValue: (i) => Number(i.remaining),
    },
    {
      key: "status",
      header: t("purchaseInvoice.column.status"),
      defaultWidth: 140,
      cell: (i) => <StatusBadge status={i.status} />,
      sortValue: (i) => i.status,
    },
    {
      key: "ledger",
      header: t("finance.ledgerStatus.column"),
      defaultWidth: 200,
      cell: (i) => <LedgerStatusBadge status={ledgerStatuses[i.id]} />,
      sortValue: (i) => ledgerStatuses[i.id]?.status ?? "",
    },
    {
      key: "action",
      header: t("purchaseInvoice.column.action"),
      defaultWidth: 110,
      alwaysVisible: true,
      headerClassName: "text-right",
      cellClassName: "text-right",
      cell: (i) => (
        <Button size="sm" variant="outline" onClick={() => setDetailId(i.id)}>
          {t("purchaseInvoice.open")}
        </Button>
      ),
    },
  ];
  const { visibleColumns, colWidths, getWidth, setWidth, sortDirectionFor, toggleSort, sortRows } = useTableColumns(
    "procurement.purchaseInvoices",
    columns,
  );
  const rows = sortRows(filtered);

  function openSaved(invoice: PurchaseInvoiceDetail) {
    queryClient.invalidateQueries({ queryKey: PURCHASE_INVOICES_KEY });
    queryClient.invalidateQueries({ queryKey: ["procurement", "invoiceable-receipts"] });
    setFormOpen(false);
    setReceiptsOpen(false);
    setEditing(null);
    setDetailId(invoice.id);
  }

  return (
    <div className="space-y-6">
      <motion.div initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25 }}>
        <h1 className="text-xl font-semibold tracking-tight">{t("purchaseInvoice.title")}</h1>
        <p className="text-sm text-muted-foreground">{t("purchaseInvoice.subtitle")}</p>
      </motion.div>

      <Card>
        <CardHeader className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <CardTitle>{t("purchaseInvoice.table.title")}</CardTitle>
            <div className="flex flex-wrap gap-2">
              <Button size="sm" variant="outline" onClick={() => exportList("xlsx")}>
                <FileSpreadsheet className="h-3.5 w-3.5" />
                Excel
              </Button>
              <Button size="sm" variant="outline" onClick={() => exportList("csv")}>CSV</Button>
              {canConfigure && (
                <Button size="sm" variant="outline" onClick={() => setSettingsOpen(true)}>
                  <Settings2 className="h-3.5 w-3.5" />
                  {t("purchaseInvoice.settings.title")}
                </Button>
              )}
              {canManage && (
                <>
                  <Button size="sm" variant="outline" onClick={() => setReceiptsOpen(true)}>
                    <PackageCheck className="h-3.5 w-3.5" />
                    {t("purchaseInvoice.fromReceipts.open")}
                  </Button>
                  <Button size="sm" onClick={() => { setEditing(null); setFormOpen(true); }}>
                    <Plus className="h-4 w-4" />
                    {t("purchaseInvoice.new")}
                  </Button>
                </>
              )}
            </div>
          </div>
          <div className="flex flex-wrap items-end gap-3">
            <FilterTabs
              value={statusFilter}
              onChange={setStatusFilter}
              options={[
                { value: "all", label: t("common.all") },
                { value: "draft", label: t("status.draft") },
                { value: "validated", label: t("status.validated") },
                { value: "partially_paid", label: t("status.partially_paid") },
                { value: "paid", label: t("status.paid") },
                { value: "cancelled", label: t("status.cancelled") },
                { value: "overdue", label: t("purchaseInvoice.overdue") },
              ]}
            />
            <LedgerStatusFilterTabs value={ledgerFilter} onChange={setLedgerFilter} />
            <div className="space-y-1">
              <Label htmlFor="pi_filter_supplier" className="text-xs">{t("purchaseInvoice.field.supplier")}</Label>
              <Select id="pi_filter_supplier" className="h-8" value={supplierFilter} onChange={(e) => setSupplierFilter(e.target.value)}>
                <option value="">{t("common.all")}</option>
                {suppliers.map((p) => (
                  <option key={p.id} value={p.id}>{p.name}</option>
                ))}
              </Select>
            </div>
            <div className="space-y-1">
              <Label htmlFor="pi_filter_from" className="text-xs">{t("purchaseInvoice.filter.from")}</Label>
              <Input id="pi_filter_from" className="h-8" type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} />
            </div>
            <div className="space-y-1">
              <Label htmlFor="pi_filter_to" className="text-xs">{t("purchaseInvoice.filter.to")}</Label>
              <Input id="pi_filter_to" className="h-8" type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} />
            </div>
            {(columnFilters.isActive || supplierFilter || dateFrom || dateTo) && (
              <Button variant="ghost" size="sm" onClick={() => { columnFilters.reset(); setSupplierFilter(""); setDateFrom(""); setDateTo(""); }}>
                {t("common.clearFilters")}
              </Button>
            )}
          </div>
        </CardHeader>
        <CardContent className="p-0">
          <Table colWidths={colWidths}>
            <TableHeader>
              <TableRow>
                {visibleColumns.map((column) => (
                  <ResizableTableHead
                    key={column.key}
                    width={getWidth(column.key)}
                    onResize={(width) => setWidth(column.key, width)}
                    className={column.headerClassName}
                    sortDirection={sortDirectionFor(column.key)}
                    onSort={column.sortValue ? () => toggleSort(column.key) : undefined}
                  >
                    {column.header}
                  </ResizableTableHead>
                ))}
              </TableRow>
              <ColumnFilterRow cells={visibleColumns.map((column) => column.filterCell ?? { type: "blank" })} />
            </TableHeader>
            <TableBody>
              {isLoading && <TableLoadingRow colSpan={visibleColumns.length} />}
              {!isLoading && rows.length === 0 && (
                <TableRow>
                  <TableCell colSpan={visibleColumns.length} className="p-0">
                    <EmptyState
                      icon={<FileText className="h-5 w-5" />}
                      title={t("purchaseInvoice.empty.title")}
                      description={t("purchaseInvoice.empty.description")}
                    />
                  </TableCell>
                </TableRow>
              )}
              {rows.map((invoice) => (
                <TableRow key={invoice.id} className="cursor-pointer" onDoubleClick={() => setDetailId(invoice.id)}>
                  {visibleColumns.map((column) => (
                    <TableCell key={column.key} className={column.cellClassName}>
                      {column.cell(invoice)}
                    </TableCell>
                  ))}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <PurchaseInvoiceFormDialog
        open={formOpen}
        onOpenChange={(open) => { setFormOpen(open); if (!open) setEditing(null); }}
        invoice={editing}
        suppliers={suppliers}
        products={products}
        defaultVat={defaultVat}
        onSaved={openSaved}
      />
      <FromReceiptsDialog open={receiptsOpen} onOpenChange={setReceiptsOpen} suppliers={suppliers} onCreated={openSaved} />
      <PurchaseInvoiceDetailDialog
        invoiceId={detailId}
        onOpenChange={(open) => { if (!open) setDetailId(null); }}
        partnerName={partnerName}
        onEdit={(invoice) => { setDetailId(null); setEditing(invoice); setFormOpen(true); }}
      />
      <SettingsDialog open={settingsOpen} onOpenChange={setSettingsOpen} current={settings?.default_vat_rate} />
    </div>
  );
}

function SettingsDialog({ open, onOpenChange, current }: { open: boolean; onOpenChange: (open: boolean) => void; current?: string }) {
  const { session } = useAuth();
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const [rate, setRate] = useState("");
  useEffect(() => {
    if (open) setRate(current ? String(Number(current)) : "18");
  }, [open, current]);
  const mutation = useMutation({
    mutationFn: () => setDefaultVatRate(session!.token, Number(rate)),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: SETTINGS_KEY });
      onOpenChange(false);
      toast.success(t("purchaseInvoice.settings.saved"));
    },
    onError: (error: unknown) =>
      toast.error(t("purchaseInvoice.settings.error"), { description: error instanceof ApiError ? error.message : undefined }),
  });
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("purchaseInvoice.settings.title")}</DialogTitle>
          <DialogDescription>{t("purchaseInvoice.settings.description")}</DialogDescription>
        </DialogHeader>
        <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); mutation.mutate(); }}>
          <div className="space-y-1.5">
            <Label htmlFor="pi_default_vat">{t("purchaseInvoice.settings.defaultVat")}</Label>
            <Input id="pi_default_vat" type="number" step="any" min="0" max="100" value={rate} onChange={(e) => setRate(e.target.value)} />
          </div>
          <Button type="submit" className="w-full" disabled={rate === "" || mutation.isPending}>{t("purchaseInvoice.save")}</Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}
