import { useState } from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import { BadgeDollarSign, CircleDollarSign, Pencil, Plus, Receipt, Send } from "lucide-react";
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
import {
  Dialog,
  DialogTrigger,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "../../components/ui/dialog";
import { StatCard } from "../../components/patterns/StatCard";
import { EmptyState } from "../../components/patterns/EmptyState";
import { StatusBadge } from "../../components/patterns/StatusBadge";
import { FilterTabs } from "../../components/patterns/FilterTabs";
import { ColumnFilterRow } from "../../components/patterns/ColumnFilterRow";
import { ColumnVisibilityMenu } from "../../components/patterns/ColumnVisibilityMenu";
import { HelpTooltip } from "../../components/patterns/HelpTooltip";
import { useColumnFilters, type FilterField } from "../../lib/useColumnFilters";
import { useTableColumns, type ColumnDef } from "../../lib/useTableColumns";
import { createInvoice, issueInvoice, listInvoices, payInvoice, updateInvoice, type Invoice, type InvoiceStatus } from "./api";
import { listCurrencies } from "../settings/exchangeRatesApi";
import { TableLoadingRow } from "../../components/patterns/AppLoader";
import { listPartners } from "../partners/api";

const newInvoiceSchema = z.object({
  partner_id: z.string().min(1, "Required"),
  amount: z.coerce.number().positive("Must be > 0"),
  currency: z.string().min(1, "Required").default("XOF"),
});
type NewInvoiceForm = z.infer<typeof newInvoiceSchema>;
type EditInvoiceForm = NewInvoiceForm;

const QUERY_KEY = ["finance", "invoices"] as const;
const PARTNERS_QUERY_KEY = ["core", "partners"] as const;
type StatusFilter = "all" | InvoiceStatus;

function formatCurrency(amount: number, currency: string) {
  try {
    return new Intl.NumberFormat(currentLocale(), { style: "currency", currency }).format(amount);
  } catch {
    return `${amount.toFixed(2)} ${currency}`;
  }
}

export function FinanceInvoicesPage() {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editDialogOpen, setEditDialogOpen] = useState(false);
  const [editingInvoice, setEditingInvoice] = useState<Invoice | null>(null);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");

  const { data: invoices = [], isLoading } = useQuery({ queryKey: QUERY_KEY, queryFn: () => listInvoices(token) });
  const { data: currencies = [] } = useQuery({ queryKey: ["core", "currencies"], queryFn: () => listCurrencies(token) });
  const { data: partners = [] } = useQuery({ queryKey: PARTNERS_QUERY_KEY, queryFn: () => listPartners(token) });
  const activePartners = partners.filter((p) => p.status === "active");
  const partnerName = (id: string) => partners.find((p) => p.id === id)?.name ?? "—";

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<NewInvoiceForm>({ resolver: zodResolver(newInvoiceSchema), defaultValues: { currency: "XOF" } });

  const createMutation = useMutation({
    mutationFn: (input: NewInvoiceForm) => createInvoice(token, input),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEY });
      setDialogOpen(false);
      reset({ currency: "XOF" });
      toast.success(t("finance.created"));
    },
    onError: (error) => {
      toast.error(t("finance.createError"), { description: error instanceof ApiError ? error.message : undefined });
    },
  });

  const issueMutation = useMutation({
    mutationFn: (id: string) => issueInvoice(token, id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEY });
      toast.success(t("finance.issued"));
    },
    onError: (error) => {
      toast.error(t("finance.issueError"), { description: error instanceof ApiError ? error.message : undefined });
    },
  });

  const payMutation = useMutation({
    mutationFn: (id: string) => payInvoice(token, id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEY });
      toast.success(t("finance.paidToast"));
    },
    onError: (error) => {
      toast.error(t("finance.markPaidError"), { description: error instanceof ApiError ? error.message : undefined });
    },
  });

  const {
    register: registerEdit,
    handleSubmit: handleEditSubmit,
    reset: resetEdit,
    formState: { errors: editErrors },
  } = useForm<EditInvoiceForm>({ resolver: zodResolver(newInvoiceSchema), defaultValues: { currency: "XOF" } });

  const updateMutation = useMutation({
    mutationFn: (input: EditInvoiceForm) => updateInvoice(token, editingInvoice!.id, input),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEY });
      setEditDialogOpen(false);
      setEditingInvoice(null);
      toast.success(t("finance.updated"));
    },
    onError: (error) => {
      toast.error(t("finance.updateError"), { description: error instanceof ApiError ? error.message : undefined });
    },
  });

  function openEditDialog(invoice: Invoice) {
    setEditingInvoice(invoice);
    resetEdit({
      partner_id: invoice.partner_id,
      amount: invoice.amount,
      currency: invoice.currency,
    });
    setEditDialogOpen(true);
  }

  const paidTotal = invoices.filter((i) => i.status === "paid").reduce((sum, i) => sum + i.amount, 0);
  const outstandingCount = invoices.filter((i) => i.status !== "paid").length;
  const statusFilteredInvoices = statusFilter === "all" ? invoices : invoices.filter((i) => i.status === statusFilter);

  const columnFilterFields: FilterField<Invoice>[] = [
    { key: "partner_id", kind: "text", getValue: (i) => partnerName(i.partner_id) },
    { key: "amount", kind: "range", getValue: (i) => i.amount },
  ];
  const columnFilters = useColumnFilters(columnFilterFields);
  const filteredInvoices = columnFilters.apply(statusFilteredInvoices);

  const columns: ColumnDef<Invoice>[] = [
    {
      key: "partner_id",
      header: t("finance.column.partner"),
      defaultWidth: 180,
      cell: (invoice) => <span className="font-medium">{partnerName(invoice.partner_id)}</span>,
      filterCell: {
        type: "text",
        value: columnFilters.text.partner_id ?? "",
        onChange: (v) => columnFilters.setTextValue("partner_id", v),
        placeholder: t("finance.column.partner"),
      },
      sortValue: (invoice) => partnerName(invoice.partner_id),
    },
    {
      key: "amount",
      header: t("finance.column.amount"),
      defaultWidth: 160,
      cell: (invoice) => <span className="tabular-nums">{formatCurrency(invoice.amount, invoice.currency)}</span>,
      filterCell: {
        type: "range",
        min: columnFilters.range.amount?.min ?? "",
        max: columnFilters.range.amount?.max ?? "",
        onMinChange: (v) => columnFilters.setRangeValue("amount", "min", v),
        onMaxChange: (v) => columnFilters.setRangeValue("amount", "max", v),
      },
      sortValue: (invoice) => invoice.amount,
    },
    {
      key: "status",
      header: (
        <span className="inline-flex items-center gap-1">
          {t("finance.column.status")}
          <HelpTooltip text={t("finance.help.status")} />
        </span>
      ),
      defaultWidth: 140,
      cell: (invoice) => <StatusBadge status={invoice.status} />,
      sortValue: (invoice) => invoice.status,
    },
    {
      key: "action",
      header: t("finance.column.action"),
      defaultWidth: 220,
      alwaysVisible: true,
      headerClassName: "text-right",
      cell: (invoice) => (
        <div className="flex justify-end gap-2">
          <Button size="sm" variant="outline" onClick={() => openEditDialog(invoice)}>
            <Pencil className="h-3.5 w-3.5" />
            {t("finance.edit")}
          </Button>
          {invoice.status === "draft" && (
            <Button
              size="sm"
              variant="outline"
              onClick={() => issueMutation.mutate(invoice.id)}
              disabled={issueMutation.isPending && issueMutation.variables === invoice.id}
            >
              <Send className="h-3.5 w-3.5" />
              {issueMutation.isPending && issueMutation.variables === invoice.id ? t("finance.issuing") : t("finance.issue")}
            </Button>
          )}
          {invoice.status === "issued" && (
            <Button
              size="sm"
              variant="outline"
              onClick={() => payMutation.mutate(invoice.id)}
              disabled={payMutation.isPending && payMutation.variables === invoice.id}
            >
              {payMutation.isPending && payMutation.variables === invoice.id ? t("finance.marking") : t("finance.markPaid")}
            </Button>
          )}
        </div>
      ),
    },
  ];
  const { visibleColumns, colWidths, isVisible, toggleVisible, getWidth, setWidth, resetAll, sortDirectionFor, toggleSort, sortRows } =
    useTableColumns("finance.invoices", columns);
  const sortedInvoices = sortRows(filteredInvoices);

  return (
    <div className="space-y-6">
      <motion.div initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25 }}>
        <h1 className="text-xl font-semibold tracking-tight">{t("finance.title")}</h1>
        <p className="text-sm text-muted-foreground">{t("finance.subtitle")}</p>
      </motion.div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <StatCard label={t("finance.stat.total")} value={invoices.length} icon={<Receipt className="h-5 w-5" />} />
        <StatCard label={t("finance.stat.outstanding")} value={outstandingCount} icon={<CircleDollarSign className="h-5 w-5" />} accent="warning" />
        <StatCard label={t("finance.stat.paid")} value={Math.round(paidTotal)} icon={<BadgeDollarSign className="h-5 w-5" />} accent="success" unit="XOF" />
      </div>

      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center gap-3">
            <div>
              <CardTitle>{t("finance.table.title")}</CardTitle>
              <p className="mt-0.5 text-sm text-muted-foreground">{t("finance.table.subtitle")}</p>
            </div>
            <FilterTabs
              value={statusFilter}
              onChange={setStatusFilter}
              options={[
                { value: "all", label: t("common.all") },
                { value: "draft", label: t("status.draft") },
                { value: "issued", label: t("status.issued") },
                { value: "paid", label: t("status.paid") },
              ]}
            />
            {columnFilters.isActive && (
              <Button variant="ghost" size="sm" onClick={columnFilters.reset}>
                {t("common.clearFilters")}
              </Button>
            )}
            <ColumnVisibilityMenu columns={columns} isVisible={isVisible} onToggle={toggleVisible} onReset={resetAll} />
          </div>
          <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
            <DialogTrigger asChild>
              <Button>
                <Plus className="h-4 w-4" />
                {t("finance.new")}
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>{t("finance.dialog.title")}</DialogTitle>
                <DialogDescription>{t("finance.dialog.description")}</DialogDescription>
              </DialogHeader>
              <form className="space-y-4" onSubmit={handleSubmit((input) => createMutation.mutate(input))}>
                <div className="space-y-1.5">
                  <Label htmlFor="partner_id">{t("finance.field.partnerId")}</Label>
                  <Select id="partner_id" {...register("partner_id")}>
                    <option value="">—</option>
                    {activePartners.map((partner) => (
                      <option key={partner.id} value={partner.id}>
                        {partner.name}
                      </option>
                    ))}
                  </Select>
                  {errors.partner_id && <p className="text-sm text-destructive">{errors.partner_id.message}</p>}
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div className="space-y-1.5">
                    <Label htmlFor="amount">{t("finance.field.amount")}</Label>
                    <Input id="amount" type="number" step="any" {...register("amount")} />
                    {errors.amount && <p className="text-sm text-destructive">{errors.amount.message}</p>}
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="currency">{t("finance.field.currency")}</Label>
                    <Select id="currency" {...register("currency")}>
                      {currencies.length === 0 && <option value="XOF">XOF</option>}
                      {currencies.map((currency) => (
                        <option key={currency.code} value={currency.code}>
                          {currency.code}
                        </option>
                      ))}
                    </Select>
                  </div>
                </div>
                {createMutation.isError && (
                  <p className="text-sm text-destructive">
                    {createMutation.error instanceof ApiError ? createMutation.error.message : t("finance.createError")}
                  </p>
                )}
                <Button type="submit" className="w-full" disabled={createMutation.isPending}>
                  {createMutation.isPending ? t("finance.creating") : t("finance.create")}
                </Button>
              </form>
            </DialogContent>
          </Dialog>
          <Dialog
            open={editDialogOpen}
            onOpenChange={(open) => {
              setEditDialogOpen(open);
              if (!open) setEditingInvoice(null);
            }}
          >
            <DialogContent>
              <DialogHeader>
                <DialogTitle>{t("finance.dialog.editTitle")}</DialogTitle>
                <DialogDescription>{t("finance.dialog.editDescription")}</DialogDescription>
              </DialogHeader>
              <form className="space-y-4" onSubmit={handleEditSubmit((input) => updateMutation.mutate(input))}>
                <div className="space-y-1.5">
                  <Label htmlFor="edit_partner_id">{t("finance.field.partnerId")}</Label>
                  <Select id="edit_partner_id" {...registerEdit("partner_id")}>
                    <option value="">—</option>
                    {partners.map((partner) => (
                      <option key={partner.id} value={partner.id}>
                        {partner.name}
                      </option>
                    ))}
                  </Select>
                  {editErrors.partner_id && <p className="text-sm text-destructive">{editErrors.partner_id.message}</p>}
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div className="space-y-1.5">
                    <Label htmlFor="edit_amount">{t("finance.field.amount")}</Label>
                    <Input id="edit_amount" type="number" step="any" {...registerEdit("amount")} />
                    {editErrors.amount && <p className="text-sm text-destructive">{editErrors.amount.message}</p>}
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="edit_currency">{t("finance.field.currency")}</Label>
                    <Select id="edit_currency" {...registerEdit("currency")}>
                      {currencies.length === 0 && <option value="XOF">XOF</option>}
                      {currencies.map((currency) => (
                        <option key={currency.code} value={currency.code}>
                          {currency.code}
                        </option>
                      ))}
                    </Select>
                  </div>
                </div>
                {updateMutation.isError && (
                  <p className="text-sm text-destructive">
                    {updateMutation.error instanceof ApiError ? updateMutation.error.message : t("finance.updateError")}
                  </p>
                )}
                <Button type="submit" className="w-full" disabled={updateMutation.isPending}>
                  {updateMutation.isPending ? t("finance.updating") : t("finance.update")}
                </Button>
              </form>
            </DialogContent>
          </Dialog>
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
              {!isLoading && filteredInvoices.length === 0 && (
                <TableRow>
                  <TableCell colSpan={visibleColumns.length} className="p-0">
                    <EmptyState
                      icon={<Receipt className="h-5 w-5" />}
                      title={t("finance.empty.title")}
                      description={t("finance.empty.description")}
                    />
                  </TableCell>
                </TableRow>
              )}
              <AnimatePresence initial={false}>
                {sortedInvoices.map((invoice, i) => (
                  <motion.tr
                    key={invoice.id}
                    layout
                    initial={{ opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0, transition: { delay: Math.min(i * 0.04, 0.3) } }}
                    exit={{ opacity: 0 }}
                    className="border-b border-border last:border-0 hover:bg-muted/50"
                  >
                    {visibleColumns.map((column) => (
                      <TableCell key={column.key} className={column.cellClassName}>
                        {column.cell(invoice)}
                      </TableCell>
                    ))}
                  </motion.tr>
                ))}
              </AnimatePresence>
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}
