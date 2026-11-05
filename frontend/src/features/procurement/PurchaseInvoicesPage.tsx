import { useState } from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { Ban, CheckCheck, FileText, Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { z } from "zod";
import { useAuth } from "../../lib/auth";
import { currentLocale, useI18n } from "../../lib/i18n";
import { ApiError } from "../../lib/api";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Select } from "../../components/ui/select";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { Table, TableHeader, TableBody, TableRow, TableCell, ResizableTableHead } from "../../components/ui/table";
import { Dialog, DialogTrigger, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "../../components/ui/dialog";
import { EmptyState } from "../../components/patterns/EmptyState";
import { StatusBadge } from "../../components/patterns/StatusBadge";
import { FilterTabs } from "../../components/patterns/FilterTabs";
import { ColumnFilterRow } from "../../components/patterns/ColumnFilterRow";
import { TableLoadingRow } from "../../components/patterns/AppLoader";
import { useColumnFilters, type FilterField } from "../../lib/useColumnFilters";
import { useTableColumns, type ColumnDef } from "../../lib/useTableColumns";
import { listPartners } from "../partners/api";
import {
  cancelPurchaseInvoice,
  createPurchaseInvoice,
  listPurchaseInvoices,
  validatePurchaseInvoice,
  type PurchaseInvoice,
  type PurchaseInvoiceStatus,
} from "./invoicesApi";

const schema = z.object({
  partner_id: z.string().min(1, "Required"),
  supplier_invoice_number: z.string().min(1, "Required"),
  invoice_date: z.string().min(1, "Required"),
  due_date: z.string().optional(),
  amount: z.coerce.number().positive("Must be > 0"),
  currency: z.string().min(1).default("XOF"),
});
type FormValues = z.infer<typeof schema>;

const QUERY_KEY = ["procurement", "purchase-invoices"] as const;
type StatusFilter = "all" | "overdue" | PurchaseInvoiceStatus;

function formatMoney(value: string, currency: string) {
  const amount = Number(value);
  try {
    return new Intl.NumberFormat(currentLocale(), { style: "currency", currency, maximumFractionDigits: 0 }).format(amount);
  } catch {
    return `${amount} ${currency}`;
  }
}

function isOverdue(invoice: PurchaseInvoice) {
  return (
    (invoice.status === "validated" || invoice.status === "partially_paid") &&
    invoice.due_date !== null &&
    invoice.due_date < new Date().toISOString().slice(0, 10)
  );
}

export function PurchaseInvoicesPage() {
  const { session, hasPermission } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const canManage = hasPermission("procurement.manage_purchase_invoices");
  const [dialogOpen, setDialogOpen] = useState(false);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [lines, setLines] = useState<{ description: string; quantity: number; unit_price: number }[]>([]);

  const { data: invoices = [], isLoading } = useQuery({ queryKey: QUERY_KEY, queryFn: () => listPurchaseInvoices(token) });
  const { data: partners = [] } = useQuery({ queryKey: ["core", "partners"], queryFn: () => listPartners(token) });
  const suppliers = partners.filter((p) => p.status === "active");
  const partnerName = (id: string) => partners.find((p) => p.id === id)?.name ?? "—";

  const {
    register,
    handleSubmit,
    setValue,
    reset,
    formState: { errors },
  } = useForm<FormValues>({ resolver: zodResolver(schema), defaultValues: { currency: "XOF" } });

  function changeLines(next: { description: string; quantity: number; unit_price: number }[]) {
    setLines(next);
    const total = next.reduce((sum, l) => sum + (Number(l.quantity) || 0) * (Number(l.unit_price) || 0), 0);
    // With lines the header total is their sum, so the two can never disagree.
    if (total > 0) setValue("amount", Math.round(total * 100) / 100, { shouldValidate: true });
  }

  const onError = (fallbackKey: Parameters<typeof t>[0]) => (error: unknown) =>
    toast.error(t(fallbackKey), { description: error instanceof ApiError ? error.message : undefined });

  const createMutation = useMutation({
    mutationFn: (input: FormValues) =>
      createPurchaseInvoice(token, {
        ...input,
        due_date: input.due_date || undefined,
        lines: lines.filter((l) => l.description && l.quantity > 0),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEY });
      setDialogOpen(false);
      reset({ currency: "XOF" });
      setLines([]);
      toast.success(t("purchaseInvoice.created"));
    },
    onError: onError("purchaseInvoice.createError"),
  });
  const validateMutation = useMutation({
    mutationFn: (id: string) => validatePurchaseInvoice(token, id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEY });
      toast.success(t("purchaseInvoice.validatedToast"));
    },
    onError: onError("purchaseInvoice.validateError"),
  });
  const cancelMutation = useMutation({
    mutationFn: (id: string) => cancelPurchaseInvoice(token, id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEY });
      toast.success(t("purchaseInvoice.cancelledToast"));
    },
    onError: onError("purchaseInvoice.cancelError"),
  });

  const statusFiltered =
    statusFilter === "all"
      ? invoices
      : statusFilter === "overdue"
        ? invoices.filter(isOverdue)
        : invoices.filter((i) => i.status === statusFilter);

  const filterFields: FilterField<PurchaseInvoice>[] = [
    { key: "partner_id", kind: "text", getValue: (i) => partnerName(i.partner_id) },
    { key: "supplier_invoice_number", kind: "text", getValue: (i) => i.supplier_invoice_number },
    { key: "amount", kind: "range", getValue: (i) => Number(i.amount) },
  ];
  const columnFilters = useColumnFilters(filterFields);
  const filtered = columnFilters.apply(statusFiltered);

  const columns: ColumnDef<PurchaseInvoice>[] = [
    {
      key: "number",
      header: t("purchaseInvoice.column.number"),
      defaultWidth: 130,
      cell: (i) => <span className="font-mono text-xs">{i.number ?? "—"}</span>,
      sortValue: (i) => i.number ?? "",
    },
    {
      key: "partner_id",
      header: t("purchaseInvoice.column.supplier"),
      defaultWidth: 180,
      cell: (i) => <span className="font-medium">{partnerName(i.partner_id)}</span>,
      filterCell: {
        type: "text",
        value: columnFilters.text.partner_id ?? "",
        onChange: (v) => columnFilters.setTextValue("partner_id", v),
        placeholder: t("purchaseInvoice.column.supplier"),
      },
      sortValue: (i) => partnerName(i.partner_id),
    },
    {
      key: "supplier_invoice_number",
      header: t("purchaseInvoice.column.supplierRef"),
      defaultWidth: 150,
      cell: (i) => i.supplier_invoice_number,
      filterCell: {
        type: "text",
        value: columnFilters.text.supplier_invoice_number ?? "",
        onChange: (v) => columnFilters.setTextValue("supplier_invoice_number", v),
        placeholder: t("purchaseInvoice.column.supplierRef"),
      },
      sortValue: (i) => i.supplier_invoice_number,
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
      key: "amount",
      header: t("purchaseInvoice.column.amount"),
      defaultWidth: 140,
      cell: (i) => <span className="tabular-nums">{formatMoney(i.amount, i.currency)}</span>,
      filterCell: {
        type: "range",
        min: columnFilters.range.amount?.min ?? "",
        max: columnFilters.range.amount?.max ?? "",
        onMinChange: (v) => columnFilters.setRangeValue("amount", "min", v),
        onMaxChange: (v) => columnFilters.setRangeValue("amount", "max", v),
      },
      sortValue: (i) => Number(i.amount),
    },
    {
      key: "remaining",
      header: t("purchaseInvoice.column.remaining"),
      defaultWidth: 140,
      cell: (i) => <span className="tabular-nums">{formatMoney(i.remaining, i.currency)}</span>,
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
      key: "action",
      header: t("purchaseInvoice.column.action"),
      defaultWidth: 200,
      alwaysVisible: true,
      headerClassName: "text-right",
      cell: (i) =>
        canManage ? (
          <div className="flex justify-end gap-2">
            {i.status === "draft" && (
              <Button size="sm" variant="outline" onClick={() => validateMutation.mutate(i.id)} disabled={validateMutation.isPending}>
                <CheckCheck className="h-3.5 w-3.5" />
                {t("purchaseInvoice.validate")}
              </Button>
            )}
            {(i.status === "draft" || (i.status === "validated" && Number(i.amount_paid) === 0)) && (
              <Button size="sm" variant="outline" onClick={() => cancelMutation.mutate(i.id)} disabled={cancelMutation.isPending}>
                <Ban className="h-3.5 w-3.5" />
                {t("purchaseInvoice.cancel")}
              </Button>
            )}
          </div>
        ) : null,
    },
  ];
  const { visibleColumns, colWidths, getWidth, setWidth, sortDirectionFor, toggleSort, sortRows } = useTableColumns(
    "procurement.purchaseInvoices",
    columns,
  );
  const rows = sortRows(filtered);

  return (
    <div className="space-y-6">
      <motion.div initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25 }}>
        <h1 className="text-xl font-semibold tracking-tight">{t("purchaseInvoice.title")}</h1>
        <p className="text-sm text-muted-foreground">{t("purchaseInvoice.subtitle")}</p>
      </motion.div>

      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center gap-3">
            <CardTitle>{t("purchaseInvoice.table.title")}</CardTitle>
            <FilterTabs
              value={statusFilter}
              onChange={setStatusFilter}
              options={[
                { value: "all", label: t("common.all") },
                { value: "draft", label: t("status.draft") },
                { value: "validated", label: t("status.validated") },
                { value: "partially_paid", label: t("status.partially_paid") },
                { value: "paid", label: t("status.paid") },
                { value: "overdue", label: t("purchaseInvoice.overdue") },
              ]}
            />
            {columnFilters.isActive && (
              <Button variant="ghost" size="sm" onClick={columnFilters.reset}>
                {t("common.clearFilters")}
              </Button>
            )}
          </div>
          {canManage && (
            <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
              <DialogTrigger asChild>
                <Button>
                  <Plus className="h-4 w-4" />
                  {t("purchaseInvoice.new")}
                </Button>
              </DialogTrigger>
              <DialogContent>
                <DialogHeader>
                  <DialogTitle>{t("purchaseInvoice.dialog.title")}</DialogTitle>
                  <DialogDescription>{t("purchaseInvoice.dialog.description")}</DialogDescription>
                </DialogHeader>
                <form className="space-y-4" onSubmit={handleSubmit((input) => createMutation.mutate(input))}>
                  <div className="space-y-1.5">
                    <Label htmlFor="pi_partner">{t("purchaseInvoice.field.supplier")}</Label>
                    <Select id="pi_partner" {...register("partner_id")}>
                      <option value="">—</option>
                      {suppliers.map((p) => (
                        <option key={p.id} value={p.id}>
                          {p.name}
                        </option>
                      ))}
                    </Select>
                    {errors.partner_id && <p className="text-sm text-destructive">{errors.partner_id.message}</p>}
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="pi_ref">{t("purchaseInvoice.field.supplierRef")}</Label>
                    <Input id="pi_ref" {...register("supplier_invoice_number")} />
                    {errors.supplier_invoice_number && <p className="text-sm text-destructive">{errors.supplier_invoice_number.message}</p>}
                  </div>
                  <div className="grid grid-cols-2 gap-3">
                    <div className="space-y-1.5">
                      <Label htmlFor="pi_date">{t("purchaseInvoice.field.invoiceDate")}</Label>
                      <Input id="pi_date" type="date" {...register("invoice_date")} />
                      {errors.invoice_date && <p className="text-sm text-destructive">{errors.invoice_date.message}</p>}
                    </div>
                    <div className="space-y-1.5">
                      <Label htmlFor="pi_due">{t("purchaseInvoice.field.dueDate")}</Label>
                      <Input id="pi_due" type="date" {...register("due_date")} />
                    </div>
                  </div>
                  <div className="grid grid-cols-2 gap-3">
                    <div className="space-y-1.5">
                      <Label htmlFor="pi_amount">{t("purchaseInvoice.field.amount")}</Label>
                      <Input id="pi_amount" type="number" step="any" readOnly={lines.length > 0} {...register("amount")} />
                      {errors.amount && <p className="text-sm text-destructive">{errors.amount.message}</p>}
                    </div>
                    <div className="space-y-1.5">
                      <Label htmlFor="pi_currency">{t("purchaseInvoice.field.currency")}</Label>
                      <Input id="pi_currency" value="F CFA" disabled />
                    </div>
                  </div>
                  <div className="space-y-2">
                    <div className="flex items-center justify-between">
                      <Label>{t("purchaseInvoice.field.lines")}</Label>
                      <Button type="button" size="sm" variant="outline" onClick={() => changeLines([...lines, { description: "", quantity: 1, unit_price: 0 }])}>
                        <Plus className="h-3.5 w-3.5" />
                      </Button>
                    </div>
                    {lines.map((line, index) => (
                      <div key={index} className="grid grid-cols-[1fr_5rem_7rem_auto] gap-2">
                        <Input placeholder={t("purchaseInvoice.field.lineDescription")} value={line.description}
                          onChange={(e) => changeLines(lines.map((l, i) => (i === index ? { ...l, description: e.target.value } : l)))} />
                        <Input type="number" step="any" min="0" value={line.quantity}
                          onChange={(e) => changeLines(lines.map((l, i) => (i === index ? { ...l, quantity: Number(e.target.value) } : l)))} />
                        <Input type="number" step="any" min="0" value={line.unit_price}
                          onChange={(e) => changeLines(lines.map((l, i) => (i === index ? { ...l, unit_price: Number(e.target.value) } : l)))} />
                        <Button type="button" size="sm" variant="ghost" onClick={() => changeLines(lines.filter((_, i) => i !== index))}>
                          <Trash2 className="h-3.5 w-3.5" />
                        </Button>
                      </div>
                    ))}
                  </div>
                  <Button type="submit" className="w-full" disabled={createMutation.isPending}>
                    {createMutation.isPending ? t("purchaseInvoice.creating") : t("purchaseInvoice.create")}
                  </Button>
                </form>
              </DialogContent>
            </Dialog>
          )}
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
                <TableRow key={invoice.id}>
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
    </div>
  );
}
