import { useState } from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm, type UseFormReturn } from "react-hook-form";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import { CheckCircle2, PackageCheck, Pencil, Plus, ShoppingCart } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { z } from "zod";
import { useAuth } from "../../lib/auth";
import { useI18n } from "../../lib/i18n";
import { formatXofWithCode } from "../../lib/currency";
import { ApiError } from "../../lib/api";
import { productRequiresIntegerQuantity } from "../../lib/units";
import { listInvoices } from "../finance/api";
import { InvoiceDetailDialog } from "../finance/InvoiceDetailDialog";
import { Button } from "../../components/ui/button";
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
import { listLocations, listUoms } from "../warehouse/api";
import { listPickLists, PICK_LISTS_QUERY_KEY } from "../warehouse/fulfillment/api";
import { RESERVATIONS_QUERY_KEY } from "../warehouse/reservations/api";
import { listPartners } from "../partners/api";
import { useProductCatalog } from "../products/catalog";
import { listProductTags } from "../products/api";
import { confirmOrder, createIssueVoucherFromOrder, createOrder, listOrders, updateOrder, type SalesOrder, type SalesOrderStatus } from "./api";
import { TableLoadingRow } from "../../components/patterns/AppLoader";
import { ConfirmOrderCreditDialog } from "./ConfirmOrderCreditDialog";
import { newPricedLine, PricedLinesFields, pricedLineSchema, useSalesSettings, type PricedFormShape } from "./PricedLinesFields";

const newOrderSchema = z.object({
  partner_id: z.string().min(1, "Required"),
  location_id: z.string().min(1, "Required"),
  discount_rate: z.coerce.number().min(0).max(100).default(0),
  lines: z.array(pricedLineSchema).min(1, "Add at least one line"),
});
type NewOrderForm = z.infer<typeof newOrderSchema>;
type EditOrderForm = NewOrderForm;

const QUERY_KEY = ["sales", "orders"] as const;
const LOCATIONS_QUERY_KEY = ["warehouse", "locations"] as const;
const PARTNERS_QUERY_KEY = ["core", "partners"] as const;
const PRODUCT_TAGS_QUERY_KEY = ["core", "product-tags"] as const;
type StatusFilter = "all" | SalesOrderStatus;

function formatCurrency(amount: number) {
  return formatXofWithCode(amount);
}

export function SalesOrdersPage() {
  const { session, hasPermission } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editDialogOpen, setEditDialogOpen] = useState(false);
  const [editingOrder, setEditingOrder] = useState<SalesOrder | null>(null);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [invoiceDetailId, setInvoiceDetailId] = useState<string | null>(null);
  // Confirming goes through the credit check dialog first (finance's credit control).
  const [confirmingOrder, setConfirmingOrder] = useState<SalesOrder | null>(null);

  const { data: orders = [], isLoading } = useQuery({ queryKey: QUERY_KEY, queryFn: () => listOrders(token) });
  // Invoices follow the deliveries, so an order can have several; shown only to those who may see invoices.
  const canSeeInvoices = hasPermission("finance.view_invoices");
  const { data: invoices = [] } = useQuery({ queryKey: ["finance", "invoices"], queryFn: () => listInvoices(token), enabled: canSeeInvoices });
  const invoicesOf = (orderId: string) => invoices.filter((invoice) => invoice.source_order_id === orderId);
  const { data: locations = [] } = useQuery({ queryKey: LOCATIONS_QUERY_KEY, queryFn: () => listLocations(token) });
  const { data: partners = [] } = useQuery({ queryKey: PARTNERS_QUERY_KEY, queryFn: () => listPartners(token) });
  // Shipping issues the stock too, so a voucher is only for an order nobody has started picking.
  // Without this data we can't tell, so no button.
  const canSeeFulfillmentHolds =
    hasPermission("warehouse.manage_vouchers") && hasPermission("warehouse.view_moves") && hasPermission("warehouse.view_fulfillment");
  const pickListsQuery = useQuery({
    queryKey: PICK_LISTS_QUERY_KEY,
    queryFn: () => listPickLists(token),
    enabled: canSeeFulfillmentHolds,
  });
  const canIssueVoucher = (order: SalesOrder) => {
    if (order.status !== "confirmed" || !canSeeFulfillmentHolds) return false;
    if (!pickListsQuery.data || pickListsQuery.isFetching) return false;
    // Posting the voucher takes the order over from a pick list nobody started; once picking began, it stays with fulfillment.
    return !pickListsQuery.data.some(
      (pickList) => pickList.source_type === "sales_order" && pickList.source_id === order.id && pickList.status !== "cancelled" && pickList.status !== "open",
    );
  };
  const { catalog } = useProductCatalog();
  const allProducts = catalog;
  const { data: uoms = [] } = useQuery({ queryKey: ["core", "uoms"], queryFn: () => listUoms(token) });
  const { data: productTags = [] } = useQuery({ queryKey: PRODUCT_TAGS_QUERY_KEY, queryFn: () => listProductTags(token) });
  const products = allProducts.filter((product) => product.is_sellable);
  // What a customer can buy: sellable products, finished goods listed first
  // and grouped by category so a packet of spaghetti is never hunted for
  // between the semolina and the film reels.
  const catalogProducts = products;

  // "Sold by sac" is marked with the "sac" product tag (Products > Étiquettes),
  // the same tag pickers use for CARTON/FILM/SCOTCH — not a separate field.
  // Anything without that tag ships in a carton, so that's the default.
  const sacTagId = productTags.find((tag) => tag.name.trim().toLowerCase() === "sac")?.id;
  const packagingWord = (productId: string | null | undefined) => {
    const product = productId ? products.find((p) => p.id === productId) : undefined;
    const isSac = !!sacTagId && !!product?.tag_ids?.includes(sacTagId);
    return isSac ? t("production.classifications.packagingFormat.sac") : t("production.classifications.packagingFormat.carton");
  };
  const defaultVat = Number(useSalesSettings().data?.default_vat_rate ?? 18);
  const emptyOrder = (): NewOrderForm => ({ partner_id: "", location_id: "", discount_rate: 0, lines: [newPricedLine(defaultVat)] });
  const customers = partners.filter((p) => p.kind === "customer" || p.kind === "both");
  const activeCustomers = customers.filter((p) => p.status === "active");
  const partnerName = (id: string) => partners.find((p) => p.id === id)?.name ?? "—";

  const createForm = useForm<NewOrderForm>({
    resolver: zodResolver(newOrderSchema),
    defaultValues: { partner_id: "", location_id: "", discount_rate: 0, lines: [newPricedLine(18)] },
  });
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = createForm;

  const createMutation = useMutation({
    mutationFn: (input: NewOrderForm) => createOrder(token, input),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEY });
      setDialogOpen(false);
      reset(emptyOrder());
      toast.success(t("sales.created"));
    },
    onError: (error) => {
      toast.error(t("sales.createError"), { description: error instanceof ApiError ? error.message : undefined });
    },
  });

  const issueVoucherMutation = useMutation({
    mutationFn: (order: SalesOrder) => createIssueVoucherFromOrder(token, order.id, order.location_id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["warehouse", "vouchers"] });
      toast.success(t("sales.issueVoucherCreated"));
      navigate("/warehouse?tab=vouchers");
    },
    onError: (error) => {
      toast.error(t("sales.issueVoucherError"), { description: error instanceof ApiError ? error.message : undefined });
    },
  });

  const confirmMutation = useMutation({
    mutationFn: ({ orderId, override }: { orderId: string; override: boolean }) => confirmOrder(token, orderId, override),
    onSuccess: () => {
      setConfirmingOrder(null);
      queryClient.invalidateQueries({ queryKey: QUERY_KEY });
      queryClient.invalidateQueries({ queryKey: RESERVATIONS_QUERY_KEY });
      queryClient.invalidateQueries({ queryKey: PICK_LISTS_QUERY_KEY });
      toast.success(t("sales.confirmedToast"), { description: t("sales.confirmedDesc") });
    },
    onError: (error) => {
      toast.error(t("sales.confirmError"), { description: error instanceof ApiError ? error.message : undefined });
    },
  });

  const editForm = useForm<EditOrderForm>({
    resolver: zodResolver(newOrderSchema),
    defaultValues: { partner_id: "", location_id: "", discount_rate: 0, lines: [newPricedLine(18)] },
  });
  const {
    register: registerEdit,
    handleSubmit: handleEditSubmit,
    reset: resetEdit,
    formState: { errors: editErrors },
  } = editForm;

  const updateMutation = useMutation({
    mutationFn: (input: EditOrderForm) => updateOrder(token, editingOrder!.id, input),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEY });
      setEditDialogOpen(false);
      setEditingOrder(null);
      toast.success(t("sales.updated"));
    },
    onError: (error) => {
      toast.error(t("sales.updateError"), { description: error instanceof ApiError ? error.message : undefined });
    },
  });

  function openEditDialog(order: SalesOrder) {
    setEditingOrder(order);
    resetEdit({
      partner_id: order.partner_id,
      location_id: order.location_id,
      discount_rate: order.discount_rate ?? 0,
      lines: order.lines.map((line) => ({
        product_id: line.product_id,
        quantity: line.quantity,
        unit_price: line.unit_price,
        discount_rate: line.discount_rate ?? 0,
        vat_rate: line.vat_rate ?? 0,
        price_list_id: line.price_list_id ?? null,
      })),
    });
    setEditDialogOpen(true);
  }

  const confirmedCount = orders.filter((o) => o.status === "confirmed").length;
  const totalValue = orders.reduce((sum, o) => sum + o.total_amount, 0);
  const statusFilteredOrders = statusFilter === "all" ? orders : orders.filter((o) => o.status === statusFilter);

  const columnFilterFields: FilterField<SalesOrder>[] = [
    { key: "partner_id", kind: "text", getValue: (o) => partnerName(o.partner_id) },
    { key: "lines", kind: "range", getValue: (o) => o.lines.length },
    { key: "total_amount", kind: "range", getValue: (o) => o.total_amount },
  ];
  const columnFilters = useColumnFilters(columnFilterFields);
  const filteredOrders = columnFilters.apply(statusFilteredOrders);

  const columns: ColumnDef<SalesOrder>[] = [
    {
      key: "partner_id",
      header: t("sales.column.partner"),
      defaultWidth: 180,
      cell: (order) => <span className="font-medium">{partnerName(order.partner_id)}</span>,
      filterCell: {
        type: "text",
        value: columnFilters.text.partner_id ?? "",
        onChange: (v) => columnFilters.setTextValue("partner_id", v),
        placeholder: t("sales.column.partner"),
      },
      sortValue: (order) => partnerName(order.partner_id),
    },
    {
      key: "lines",
      header: t("sales.column.lines"),
      defaultWidth: 140,
      cell: (order) => (
        <span className="text-muted-foreground">
          {order.lines.length} {order.lines.length === 1 ? t("sales.line") : t("sales.linesPlural")}
        </span>
      ),
      filterCell: {
        type: "range",
        min: columnFilters.range.lines?.min ?? "",
        max: columnFilters.range.lines?.max ?? "",
        onMinChange: (v) => columnFilters.setRangeValue("lines", "min", v),
        onMaxChange: (v) => columnFilters.setRangeValue("lines", "max", v),
      },
      sortValue: (order) => order.lines.length,
    },
    {
      key: "total_amount",
      header: t("sales.column.total"),
      defaultWidth: 140,
      cell: (order) => <span className="tabular-nums">{formatCurrency(order.total_amount)}</span>,
      filterCell: {
        type: "range",
        min: columnFilters.range.total_amount?.min ?? "",
        max: columnFilters.range.total_amount?.max ?? "",
        onMinChange: (v) => columnFilters.setRangeValue("total_amount", "min", v),
        onMaxChange: (v) => columnFilters.setRangeValue("total_amount", "max", v),
      },
      sortValue: (order) => order.total_amount,
    },
    {
      key: "status",
      header: (
        <span className="inline-flex items-center gap-1">
          {t("sales.column.status")}
          <HelpTooltip text={t("sales.help.status")} />
        </span>
      ),
      defaultWidth: 140,
      cell: (order) => <StatusBadge status={order.status} />,
      sortValue: (order) => order.status,
    },
    ...(canSeeInvoices
      ? [
          {
            key: "invoices",
            header: t("sales.column.invoices"),
            defaultWidth: 170,
            cell: (order: SalesOrder) => {
              const own = invoicesOf(order.id);
              if (own.length === 0) return <span className="text-muted-foreground">{order.status === "draft" ? "—" : t("sales.invoices.none")}</span>;
              return (
                <div className="flex flex-wrap gap-x-2">
                  {own.map((invoice) => (
                    <button key={invoice.id} type="button" className="text-primary underline-offset-2 hover:underline" onClick={() => setInvoiceDetailId(invoice.id)}>
                      {invoice.number ?? t("sales.invoices.unnumbered")}
                    </button>
                  ))}
                </div>
              );
            },
          } satisfies ColumnDef<SalesOrder>,
        ]
      : []),
    {
      key: "action",
      header: t("sales.column.action"),
      defaultWidth: 200,
      alwaysVisible: true,
      headerClassName: "text-right",
      cell: (order) => (
        <div className="flex justify-end gap-2">
          <Button size="sm" variant="outline" onClick={() => openEditDialog(order)}>
            <Pencil className="h-3.5 w-3.5" />
            {t("sales.edit")}
          </Button>
          {canIssueVoucher(order) && (
            <Button
              size="sm"
              variant="outline"
              onClick={() => issueVoucherMutation.mutate(order)}
              disabled={issueVoucherMutation.isPending && issueVoucherMutation.variables?.id === order.id}
            >
              <PackageCheck className="h-3.5 w-3.5" />
              {t("sales.issueVoucher")}
            </Button>
          )}
          {order.status === "draft" && (
            <Button
              size="sm"
              variant="outline"
              onClick={() => setConfirmingOrder(order)}
              disabled={confirmMutation.isPending && confirmMutation.variables?.orderId === order.id}
            >
              {confirmMutation.isPending && confirmMutation.variables?.orderId === order.id ? t("sales.confirming") : t("sales.confirm")}
            </Button>
          )}
        </div>
      ),
    },
  ];
  const { visibleColumns, colWidths, isVisible, toggleVisible, getWidth, setWidth, resetAll, sortDirectionFor, toggleSort, sortRows } =
    useTableColumns("sales.orders", columns);
  const sortedOrders = sortRows(filteredOrders);

  return (
    <div className="space-y-6">
      <motion.div initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25 }}>
        <h1 className="text-xl font-semibold tracking-tight">{t("sales.title")}</h1>
        <p className="text-sm text-muted-foreground">{t("sales.subtitle")}</p>
      </motion.div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <StatCard label={t("sales.stat.total")} value={orders.length} icon={<ShoppingCart className="h-5 w-5" />} />
        <StatCard label={t("sales.stat.confirmed")} value={confirmedCount} icon={<CheckCircle2 className="h-5 w-5" />} accent="success" />
        <StatCard label={t("sales.stat.pipelineValue")} value={Math.round(totalValue)} icon={<ShoppingCart className="h-5 w-5" />} accent="accent" unit="XOF" />
      </div>

      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center gap-3">
            <div>
              <CardTitle>{t("sales.table.title")}</CardTitle>
              <p className="mt-0.5 text-sm text-muted-foreground">{t("sales.table.subtitle")}</p>
            </div>
            <FilterTabs
              value={statusFilter}
              onChange={setStatusFilter}
              options={[
                { value: "all", label: t("common.all") },
                { value: "draft", label: t("status.draft") },
                { value: "confirmed", label: t("status.confirmed") },
                { value: "shipped", label: t("status.shipped") },
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
                {t("sales.new")}
              </Button>
            </DialogTrigger>
            <DialogContent className="max-h-[90vh] max-w-3xl overflow-y-auto">
              <DialogHeader>
                <DialogTitle>{t("sales.dialog.title")}</DialogTitle>
                <DialogDescription>{t("sales.dialog.description")}</DialogDescription>
              </DialogHeader>
              <form className="space-y-4" onSubmit={handleSubmit((input) => createMutation.mutate(input))}>
                <div className="space-y-1.5">
                  <Label htmlFor="partner_id">{t("sales.field.partnerId")}</Label>
                  <Select id="partner_id" {...register("partner_id")}>
                    <option value="">—</option>
                    {activeCustomers.map((partner) => (
                      <option key={partner.id} value={partner.id}>
                        {partner.name}
                      </option>
                    ))}
                  </Select>
                  {errors.partner_id && <p className="text-sm text-destructive">{errors.partner_id.message}</p>}
                </div>

                <div className="space-y-1.5">
                  <Label htmlFor="location_id">{t("sales.field.location")}</Label>
                  <Select id="location_id" {...register("location_id")}>
                    <option value="">—</option>
                    {locations.map((location) => (
                      <option key={location.id} value={location.id}>
                        {location.name}
                      </option>
                    ))}
                  </Select>
                  {errors.location_id && <p className="text-sm text-destructive">{errors.location_id.message}</p>}
                </div>

                <PricedLinesFields
                  form={createForm as unknown as UseFormReturn<PricedFormShape>}
                  products={catalogProducts}
                  idPrefix="order"
                  quantityLabel={(productId) => `${t("sales.field.qty")} (${packagingWord(productId)})`}
                  quantityStep={(productId) => (productRequiresIntegerQuantity(productId, products, uoms) ? "1" : "any")}
                />

                {createMutation.isError && (
                  <p className="text-sm text-destructive">
                    {createMutation.error instanceof ApiError ? createMutation.error.message : t("sales.createError")}
                  </p>
                )}
                <Button type="submit" className="w-full" disabled={createMutation.isPending}>
                  {createMutation.isPending ? t("sales.creating") : t("sales.create")}
                </Button>
              </form>
            </DialogContent>
          </Dialog>
          <Dialog
            open={editDialogOpen}
            onOpenChange={(open) => {
              setEditDialogOpen(open);
              if (!open) setEditingOrder(null);
            }}
          >
            <DialogContent className="max-h-[90vh] max-w-3xl overflow-y-auto">
              <DialogHeader>
                <DialogTitle>{t("sales.dialog.editTitle")}</DialogTitle>
                <DialogDescription>{t("sales.dialog.editDescription")}</DialogDescription>
              </DialogHeader>
              <form className="space-y-4" onSubmit={handleEditSubmit((input) => updateMutation.mutate(input))}>
                <div className="space-y-1.5">
                  <Label htmlFor="edit_partner_id">{t("sales.field.partnerId")}</Label>
                  <Select id="edit_partner_id" {...registerEdit("partner_id")}>
                    <option value="">—</option>
                    {customers.map((partner) => (
                      <option key={partner.id} value={partner.id}>
                        {partner.name}
                      </option>
                    ))}
                  </Select>
                  {editErrors.partner_id && <p className="text-sm text-destructive">{editErrors.partner_id.message}</p>}
                </div>

                <div className="space-y-1.5">
                  <Label htmlFor="edit_location_id">{t("sales.field.location")}</Label>
                  <Select id="edit_location_id" {...registerEdit("location_id")}>
                    <option value="">—</option>
                    {locations.map((location) => (
                      <option key={location.id} value={location.id}>
                        {location.name}
                      </option>
                    ))}
                  </Select>
                  {editErrors.location_id && <p className="text-sm text-destructive">{editErrors.location_id.message}</p>}
                </div>

                <PricedLinesFields
                  form={editForm as unknown as UseFormReturn<PricedFormShape>}
                  products={catalogProducts}
                  idPrefix="edit_order"
                  quantityLabel={(productId) => `${t("sales.field.qty")} (${packagingWord(productId)})`}
                  quantityStep={(productId) => (productRequiresIntegerQuantity(productId, products, uoms) ? "1" : "any")}
                />

                {updateMutation.isError && (
                  <p className="text-sm text-destructive">
                    {updateMutation.error instanceof ApiError ? updateMutation.error.message : t("sales.updateError")}
                  </p>
                )}
                <Button type="submit" className="w-full" disabled={updateMutation.isPending}>
                  {updateMutation.isPending ? t("sales.updating") : t("sales.update")}
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
              {!isLoading && filteredOrders.length === 0 && (
                <TableRow>
                  <TableCell colSpan={visibleColumns.length} className="p-0">
                    <EmptyState
                      icon={<ShoppingCart className="h-5 w-5" />}
                      title={t("sales.empty.title")}
                      description={t("sales.empty.description")}
                    />
                  </TableCell>
                </TableRow>
              )}
              <AnimatePresence initial={false}>
                {sortedOrders.map((order, i) => (
                  <motion.tr
                    key={order.id}
                    layout
                    initial={{ opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0, transition: { delay: Math.min(i * 0.04, 0.3) } }}
                    exit={{ opacity: 0 }}
                    className="border-b border-border last:border-0 hover:bg-muted/50"
                  >
                    {visibleColumns.map((column) => (
                      <TableCell key={column.key} className={column.cellClassName}>
                        {column.cell(order)}
                      </TableCell>
                    ))}
                  </motion.tr>
                ))}
              </AnimatePresence>
            </TableBody>
          </Table>
        </CardContent>
      </Card>
      <InvoiceDetailDialog invoiceId={invoiceDetailId} onClose={() => setInvoiceDetailId(null)} />
      {confirmingOrder && (
        <ConfirmOrderCreditDialog
          order={confirmingOrder}
          customerName={partnerName(confirmingOrder.partner_id)}
          pending={confirmMutation.isPending}
          onConfirm={(override) => confirmMutation.mutate({ orderId: confirmingOrder.id, override })}
          onClose={() => setConfirmingOrder(null)}
        />
      )}
    </div>
  );
}
