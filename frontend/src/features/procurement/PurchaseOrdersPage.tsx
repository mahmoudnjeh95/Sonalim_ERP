import { useEffect, useState } from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { useFieldArray, useForm, type UseFormReturn } from "react-hook-form";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import { CheckCircle2, ClipboardList, History, Package, PackageCheck, Pencil, Plus, ShieldCheck, Ship, Trash2, XCircle } from "lucide-react";
import { toast } from "sonner";
import { z } from "zod";
import { useAuth } from "../../lib/auth";
import { useI18n } from "../../lib/i18n";
import { ApiError } from "../../lib/api";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Select } from "../../components/ui/select";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { Table, TableHeader, TableBody, TableRow, TableCell, ResizableTableHead } from "../../components/ui/table";
import { Skeleton } from "../../components/ui/skeleton";
import { Badge, type BadgeProps } from "../../components/ui/badge";
import { Dialog, DialogTrigger, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "../../components/ui/dialog";
import { StatCard } from "../../components/patterns/StatCard";
import { EmptyState } from "../../components/patterns/EmptyState";
import { FilterTabs } from "../../components/patterns/FilterTabs";
import { ColumnFilterRow } from "../../components/patterns/ColumnFilterRow";
import { ColumnVisibilityMenu } from "../../components/patterns/ColumnVisibilityMenu";
import { useColumnFilters, type FilterField } from "../../lib/useColumnFilters";
import { useTableColumns, type ColumnDef } from "../../lib/useTableColumns";
import { listPartners, type Partner } from "../partners/api";
import { listProducts, listUoms, listLocations, type Location } from "../warehouse/api";
import { listCurrencies } from "../settings/exchangeRatesApi";
import {
  approvePurchaseOrder,
  cancelPurchaseOrder,
  createPurchaseOrder,
  listPurchaseOrderLines,
  listPurchaseOrderReceiptLines,
  listPurchaseOrderReceipts,
  listPurchaseOrders,
  placePurchaseOrder,
  receiveAndConfirm,
  refusePurchaseOrder,
  updatePurchaseOrder,
  validatePurchaseOrder,
  type CreateReceiptLineInput,
  type PurchaseOrder,
  type PurchaseOrderLine,
  type PurchaseOrderReceipt,
  type PurchaseOrderStatus,
  type UpdatePurchaseOrderInput,
} from "./api";

const QUERY_KEY = ["procurement", "purchase-orders"] as const;
const PARTNERS_QUERY_KEY = ["core", "partners"] as const;
const PRODUCTS_QUERY_KEY = ["core", "products"] as const;
const UOMS_QUERY_KEY = ["core", "uoms"] as const;
const LOCATIONS_QUERY_KEY = ["warehouse", "locations"] as const;

const STATUS_FILTER_VALUES: PurchaseOrderStatus[] = [
  "draft",
  "validated",
  "approved",
  "ordered",
  "partially_received",
  "fully_received",
  "canceled",
  "refused",
];
type StatusFilter = "all" | PurchaseOrderStatus;

const STATUS_VARIANT: Record<PurchaseOrderStatus, BadgeProps["variant"]> = {
  draft: "default",
  validated: "primary",
  approved: "accent",
  ordered: "warning",
  partially_received: "warning",
  fully_received: "success",
  canceled: "outline",
  refused: "destructive",
};

function PurchaseOrderStatusBadge({ status }: { status: PurchaseOrderStatus }) {
  const { t } = useI18n();
  return (
    <Badge variant={STATUS_VARIANT[status]} dot>
      {t(`procurement.status.${status}` as Parameters<typeof t>[0])}
    </Badge>
  );
}

const lineSchema = z.object({
  product_id: z.string().min(1, "Required"),
  uom_id: z.string().min(1, "Required"),
  quantity_ordered: z.coerce.number().positive("Must be > 0"),
  unit_price: z.coerce.number().min(0).default(0),
});
const newOrderSchema = z.object({
  supplier_id: z.string().optional(),
  currency_code: z.string().min(1, "Required").default("EUR"),
  order_date: z.string().optional(),
  expected_date: z.string().optional(),
  notes: z.string().optional(),
  lines: z.array(lineSchema).min(1, "At least one line is required"),
});
type NewOrderForm = z.infer<typeof newOrderSchema>;

const editOrderSchema = z.object({
  supplier_id: z.string().optional(),
  currency_code: z.string().min(1, "Required"),
  order_date: z.string().optional(),
  expected_date: z.string().optional(),
  notes: z.string().optional(),
});
type EditOrderForm = z.infer<typeof editOrderSchema>;

const receiptLineSchema = z.object({
  purchase_order_line_id: z.string(),
  productLabel: z.string(),
  outstanding: z.coerce.number(),
  uomLabel: z.string(),
  quantity: z.coerce.number().min(0).default(0),
  lot_number: z.string().optional(),
});
const receiveSchema = z.object({
  location_id: z.string().min(1, "Required"),
  invoice_number: z.string().optional(),
  invoice_date: z.string().optional(),
  origin_country: z.string().optional(),
  carrier: z.string().optional(),
  base_cost: z.coerce.number().min(0).default(0),
  license_fee: z.coerce.number().min(0).default(0),
  insurance_fee: z.coerce.number().min(0).default(0),
  transit_fee: z.coerce.number().min(0).default(0),
  transport_fee: z.coerce.number().min(0).default(0),
  customs_duty: z.coerce.number().min(0).default(0),
  lines: z.array(receiptLineSchema),
});
type ReceiveForm = z.infer<typeof receiveSchema>;

export function PurchaseOrdersPage() {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [receivingId, setReceivingId] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [historyId, setHistoryId] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");

  const { data: orders = [], isLoading } = useQuery({
    queryKey: [...QUERY_KEY, statusFilter],
    queryFn: () => listPurchaseOrders(token, statusFilter === "all" ? undefined : statusFilter),
  });
  const { data: partners = [] } = useQuery({ queryKey: PARTNERS_QUERY_KEY, queryFn: () => listPartners(token) });
  const { data: products = [] } = useQuery({ queryKey: PRODUCTS_QUERY_KEY, queryFn: () => listProducts(token) });
  const { data: uoms = [] } = useQuery({ queryKey: UOMS_QUERY_KEY, queryFn: () => listUoms(token) });
  const { data: locations = [] } = useQuery({ queryKey: LOCATIONS_QUERY_KEY, queryFn: () => listLocations(token) });
  const { data: currencies = [] } = useQuery({ queryKey: ["core", "currencies"], queryFn: () => listCurrencies(token) });

  const suppliers = partners.filter((p) => p.kind === "supplier" || p.kind === "both");
  const supplierName = (id: string | null) => (id ? suppliers.find((p) => p.id === id)?.name ?? id : "—");
  const productName = (id: string) => products.find((p) => p.id === id)?.name ?? id;
  const uomCode = (id: string) => uoms.find((u) => u.id === id)?.code ?? id;

  const columnFilterFields: FilterField<PurchaseOrder>[] = [
    { key: "supplier", kind: "text", getValue: (o) => supplierName(o.supplier_id) },
    { key: "order_date", kind: "text", getValue: (o) => o.order_date },
    { key: "currency_code", kind: "text", getValue: (o) => o.currency_code },
  ];
  const columnFilters = useColumnFilters(columnFilterFields);
  const filteredOrders = columnFilters.apply(orders);

  const {
    register,
    control,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<NewOrderForm>({
    resolver: zodResolver(newOrderSchema),
    defaultValues: { supplier_id: "", currency_code: "EUR", order_date: "", expected_date: "", notes: "", lines: [] },
  });
  const { fields: lineFields, append: appendLine, remove: removeLine } = useFieldArray({ control, name: "lines" });

  const createMutation = useMutation({
    mutationFn: (input: NewOrderForm) =>
      createPurchaseOrder(token, {
        supplier_id: input.supplier_id || undefined,
        currency_code: input.currency_code,
        order_date: input.order_date || undefined,
        expected_date: input.expected_date || undefined,
        notes: input.notes || undefined,
        lines: input.lines.map((line) => ({
          product_id: line.product_id,
          uom_id: line.uom_id,
          quantity_ordered: line.quantity_ordered,
          unit_price: line.unit_price,
        })),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEY });
      setDialogOpen(false);
      reset({ supplier_id: "", currency_code: "EUR", order_date: "", expected_date: "", notes: "", lines: [] });
      toast.success(t("procurement.created"));
    },
    onError: (error) => {
      toast.error(t("procurement.createError"), { description: error instanceof ApiError ? error.message : undefined });
    },
  });

  const editForm = useForm<EditOrderForm>({ resolver: zodResolver(editOrderSchema) });

  const updateMutation = useMutation({
    mutationFn: ({ id, input }: { id: string; input: UpdatePurchaseOrderInput }) => updatePurchaseOrder(token, id, input),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEY });
      setEditingId(null);
      editForm.reset();
      toast.success(t("procurement.updated"));
    },
    onError: (error) => {
      toast.error(t("procurement.updateError"), { description: error instanceof ApiError ? error.message : undefined });
    },
  });

  function openEditDialog(order: PurchaseOrder | null) {
    if (!order) {
      setEditingId(null);
      return;
    }
    setEditingId(order.id);
    editForm.reset({
      supplier_id: order.supplier_id ?? "",
      currency_code: order.currency_code,
      order_date: order.order_date ?? "",
      expected_date: order.expected_date ?? "",
      notes: order.notes ?? "",
    });
  }

  function submitEdit(order: PurchaseOrder, input: EditOrderForm) {
    updateMutation.mutate({
      id: order.id,
      input: {
        supplier_id: input.supplier_id || undefined,
        currency_code: input.currency_code,
        order_date: input.order_date || undefined,
        expected_date: input.expected_date || undefined,
        notes: input.notes || undefined,
      },
    });
  }

  function transitionMutationFor(label: string, fn: (token: string, id: string) => Promise<PurchaseOrder>) {
    return {
      mutationFn: (id: string) => fn(token, id),
      onSuccess: () => {
        queryClient.invalidateQueries({ queryKey: QUERY_KEY });
        toast.success(label);
      },
      onError: (error: unknown) => {
        toast.error(t("procurement.transitionError"), { description: error instanceof ApiError ? error.message : undefined });
      },
    };
  }
  const validateMutation = useMutation(transitionMutationFor(t("procurement.action.validated"), validatePurchaseOrder));
  const approveMutation = useMutation(transitionMutationFor(t("procurement.action.approved"), approvePurchaseOrder));
  const placeOrderMutation = useMutation(transitionMutationFor(t("procurement.action.ordered"), placePurchaseOrder));
  const refuseMutation = useMutation(transitionMutationFor(t("procurement.action.refused"), refusePurchaseOrder));
  const cancelMutation = useMutation(transitionMutationFor(t("procurement.action.canceled"), cancelPurchaseOrder));

  const receiveForm = useForm<ReceiveForm>({
    resolver: zodResolver(receiveSchema),
    defaultValues: {
      location_id: "",
      invoice_number: "",
      invoice_date: "",
      origin_country: "",
      carrier: "",
      base_cost: 0,
      license_fee: 0,
      insurance_fee: 0,
      transit_fee: 0,
      transport_fee: 0,
      customs_duty: 0,
      lines: [],
    },
  });

  const receiveMutation = useMutation({
    mutationFn: async ({ orderId, input }: { orderId: string; input: ReceiveForm }) => {
      const lines: CreateReceiptLineInput[] = input.lines
        .filter((line) => line.quantity > 0)
        .map((line) => ({ purchase_order_line_id: line.purchase_order_line_id, quantity: line.quantity, lot_number: line.lot_number || undefined }));
      return receiveAndConfirm(token, orderId, {
        location_id: input.location_id,
        invoice_number: input.invoice_number || undefined,
        invoice_date: input.invoice_date || undefined,
        origin_country: input.origin_country || undefined,
        carrier: input.carrier || undefined,
        base_cost: input.base_cost,
        license_fee: input.license_fee,
        insurance_fee: input.insurance_fee,
        transit_fee: input.transit_fee,
        transport_fee: input.transport_fee,
        customs_duty: input.customs_duty,
        lines,
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEY });
      queryClient.invalidateQueries({ queryKey: ["warehouse", "stock"] });
      setReceivingId(null);
      toast.success(t("procurement.receipt.confirmed"));
    },
    onError: (error) => {
      toast.error(t("procurement.receipt.confirmError"), { description: error instanceof ApiError ? error.message : undefined });
    },
  });

  const draftCount = orders.filter((o) => o.status === "draft").length;
  const inFlightCount = orders.filter((o) => o.status === "ordered" || o.status === "partially_received").length;
  const fullyReceivedCount = orders.filter((o) => o.status === "fully_received").length;

  const columns: ColumnDef<PurchaseOrder>[] = [
    {
      key: "supplier",
      header: t("procurement.column.supplier"),
      defaultWidth: 180,
      cell: (order) => <span className="font-medium">{supplierName(order.supplier_id)}</span>,
      filterCell: {
        type: "text",
        value: columnFilters.text.supplier ?? "",
        onChange: (v) => columnFilters.setTextValue("supplier", v),
        placeholder: t("procurement.column.supplier"),
      },
    },
    {
      key: "order_date",
      header: t("procurement.column.orderDate"),
      defaultWidth: 140,
      cell: (order) => <span className="text-muted-foreground">{order.order_date ?? "—"}</span>,
      filterCell: {
        type: "text",
        value: columnFilters.text.order_date ?? "",
        onChange: (v) => columnFilters.setTextValue("order_date", v),
        placeholder: t("procurement.column.orderDate"),
      },
    },
    {
      key: "currency_code",
      header: t("procurement.column.currency"),
      defaultWidth: 120,
      cell: (order) => <span className="text-muted-foreground">{order.currency_code}</span>,
      filterCell: {
        type: "text",
        value: columnFilters.text.currency_code ?? "",
        onChange: (v) => columnFilters.setTextValue("currency_code", v),
        placeholder: t("procurement.column.currency"),
      },
    },
    { key: "status", header: t("procurement.column.status"), defaultWidth: 160, cell: (order) => <PurchaseOrderStatusBadge status={order.status} /> },
    {
      key: "action",
      header: t("procurement.column.action"),
      defaultWidth: 460,
      alwaysVisible: true,
      headerClassName: "text-right",
      cellClassName: "text-right",
      cell: (order) => (
        <OrderActions
          order={order}
          suppliers={suppliers}
          locations={locations}
          productName={productName}
          uomCode={uomCode}
          receivingId={receivingId}
          onOpenReceive={(open) => setReceivingId(open ? order.id : null)}
          receiveForm={receiveForm}
          editingId={editingId}
          onOpenEdit={(open) => openEditDialog(open ? order : null)}
          editForm={editForm}
          onSubmitEdit={(input) => submitEdit(order, input)}
          isUpdating={updateMutation.isPending && updateMutation.variables?.id === order.id}
          historyId={historyId}
          onOpenHistory={(open) => setHistoryId(open ? order.id : null)}
          onValidate={() => validateMutation.mutate(order.id)}
          onApprove={() => approveMutation.mutate(order.id)}
          onPlaceOrder={() => placeOrderMutation.mutate(order.id)}
          onRefuse={() => refuseMutation.mutate(order.id)}
          onCancel={() => cancelMutation.mutate(order.id)}
          onReceive={(input) => receiveMutation.mutate({ orderId: order.id, input })}
          isReceiving={receiveMutation.isPending && receiveMutation.variables?.orderId === order.id}
          pendingAction={
            (validateMutation.isPending && validateMutation.variables === order.id) ||
            (approveMutation.isPending && approveMutation.variables === order.id) ||
            (placeOrderMutation.isPending && placeOrderMutation.variables === order.id) ||
            (refuseMutation.isPending && refuseMutation.variables === order.id) ||
            (cancelMutation.isPending && cancelMutation.variables === order.id)
          }
        />
      ),
    },
  ];
  const { visibleColumns, colWidths, isVisible, toggleVisible, getWidth, setWidth, resetAll } = useTableColumns(
    "procurement.purchaseOrders",
    columns,
  );

  return (
    <div className="space-y-6">
      <motion.div initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25 }}>
        <h1 className="text-xl font-semibold tracking-tight">{t("procurement.title")}</h1>
        <p className="text-sm text-muted-foreground">{t("procurement.subtitle")}</p>
      </motion.div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <StatCard label={t("procurement.stat.draft")} value={draftCount} icon={<ClipboardList className="h-5 w-5" />} />
        <StatCard label={t("procurement.stat.inFlight")} value={inFlightCount} icon={<Ship className="h-5 w-5" />} accent="warning" />
        <StatCard label={t("procurement.stat.fullyReceived")} value={fullyReceivedCount} icon={<PackageCheck className="h-5 w-5" />} accent="success" />
      </div>

      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center gap-3">
            <div>
              <CardTitle>{t("procurement.table.title")}</CardTitle>
              <p className="mt-0.5 text-sm text-muted-foreground">{t("procurement.table.subtitle")}</p>
            </div>
            <FilterTabs
              value={statusFilter}
              onChange={setStatusFilter}
              options={[
                { value: "all", label: t("common.all") },
                ...STATUS_FILTER_VALUES.map((value) => ({ value, label: t(`procurement.status.${value}` as Parameters<typeof t>[0]) })),
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
                {t("procurement.new")}
              </Button>
            </DialogTrigger>
            <DialogContent className="max-w-2xl">
              <DialogHeader>
                <DialogTitle>{t("procurement.dialog.title")}</DialogTitle>
                <DialogDescription>{t("procurement.dialog.description")}</DialogDescription>
              </DialogHeader>
              <form className="space-y-4" onSubmit={handleSubmit((input) => createMutation.mutate(input))}>
                <div className="grid grid-cols-2 gap-3">
                  <div className="space-y-1.5">
                    <Label htmlFor="supplier_id">{t("procurement.field.supplier")}</Label>
                    <Select id="supplier_id" {...register("supplier_id")}>
                      <option value="">—</option>
                      {suppliers.map((supplier) => (
                        <option key={supplier.id} value={supplier.id}>
                          {supplier.name}
                        </option>
                      ))}
                    </Select>
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="currency_code">{t("procurement.field.currency")}</Label>
                    <Select id="currency_code" {...register("currency_code")}>
                      {currencies.map((currency) => (
                        <option key={currency.code} value={currency.code}>
                          {currency.code} — {currency.name}
                        </option>
                      ))}
                    </Select>
                    {errors.currency_code && <p className="text-sm text-destructive">{errors.currency_code.message}</p>}
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="order_date">{t("procurement.field.orderDate")}</Label>
                    <Input id="order_date" type="date" {...register("order_date")} />
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="expected_date">{t("procurement.field.expectedDate")}</Label>
                    <Input id="expected_date" type="date" {...register("expected_date")} />
                  </div>
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="notes">{t("procurement.field.notes")}</Label>
                  <Input id="notes" {...register("notes")} />
                </div>

                <div className="space-y-2 rounded-lg border border-border p-3">
                  <div className="flex items-center justify-between">
                    <Label>{t("procurement.field.lines")}</Label>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      onClick={() => appendLine({ product_id: "", uom_id: "", quantity_ordered: 0, unit_price: 0 })}
                    >
                      <Plus className="h-3.5 w-3.5" />
                      {t("procurement.addLine")}
                    </Button>
                  </div>
                  {lineFields.length > 0 && (
                    <div className="grid grid-cols-[minmax(0,1fr)_7rem_6rem_6rem_2rem] gap-2 px-1 text-xs font-medium text-muted-foreground">
                      <span>{t("procurement.field.product")}</span>
                      <span>{t("procurement.field.uom")}</span>
                      <span>{t("procurement.field.quantity")}</span>
                      <span>{t("procurement.field.unitPrice")}</span>
                      <span />
                    </div>
                  )}
                  <AnimatePresence initial={false}>
                    {lineFields.map((field, lineIndex) => (
                      <motion.div
                        key={field.id}
                        initial={{ opacity: 0, height: 0 }}
                        animate={{ opacity: 1, height: "auto" }}
                        exit={{ opacity: 0, height: 0 }}
                        transition={{ duration: 0.18 }}
                        className="grid grid-cols-[minmax(0,1fr)_7rem_6rem_6rem_2rem] items-center gap-2"
                      >
                        <Select {...register(`lines.${lineIndex}.product_id` as const)}>
                          <option value="">—</option>
                          {products.map((product) => (
                            <option key={product.id} value={product.id}>
                              {product.name}
                            </option>
                          ))}
                        </Select>
                        <Select className="w-28" {...register(`lines.${lineIndex}.uom_id` as const)}>
                          <option value="">—</option>
                          {uoms.map((uom) => (
                            <option key={uom.id} value={uom.id}>
                              {uom.code}
                            </option>
                          ))}
                        </Select>
                        <Input
                          type="number"
                          step="any"
                          className="w-24"
                          placeholder={t("procurement.field.quantity")}
                          {...register(`lines.${lineIndex}.quantity_ordered` as const)}
                        />
                        <Input
                          type="number"
                          step="any"
                          className="w-24"
                          placeholder={t("procurement.field.unitPrice")}
                          {...register(`lines.${lineIndex}.unit_price` as const)}
                        />
                        <Button type="button" variant="ghost" size="sm" onClick={() => removeLine(lineIndex)} aria-label={t("procurement.removeLine")}>
                          <Trash2 className="h-3.5 w-3.5" />
                        </Button>
                      </motion.div>
                    ))}
                  </AnimatePresence>
                  {lineFields.length === 0 && <p className="text-xs text-muted-foreground">{t("procurement.noLines")}</p>}
                  {errors.lines && <p className="text-sm text-destructive">{errors.lines.message ?? errors.lines.root?.message}</p>}
                </div>

                {createMutation.isError && (
                  <p className="text-sm text-destructive">
                    {createMutation.error instanceof ApiError ? createMutation.error.message : t("procurement.createError")}
                  </p>
                )}
                <Button type="submit" className="w-full" disabled={createMutation.isPending}>
                  {createMutation.isPending ? t("procurement.creating") : t("procurement.create")}
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
                  >
                    {column.header}
                  </ResizableTableHead>
                ))}
              </TableRow>
              <ColumnFilterRow cells={visibleColumns.map((column) => column.filterCell ?? { type: "blank" })} />
            </TableHeader>
            <TableBody>
              {isLoading &&
                Array.from({ length: 3 }).map((_, i) => (
                  <TableRow key={i}>
                    <TableCell colSpan={visibleColumns.length}>
                      <Skeleton className="h-5 w-full" />
                    </TableCell>
                  </TableRow>
                ))}
              {!isLoading && filteredOrders.length === 0 && (
                <TableRow>
                  <TableCell colSpan={visibleColumns.length} className="p-0">
                    <EmptyState
                      icon={<ClipboardList className="h-5 w-5" />}
                      title={t("procurement.empty.title")}
                      description={t("procurement.empty.description")}
                    />
                  </TableCell>
                </TableRow>
              )}
              <AnimatePresence initial={false}>
                {filteredOrders.map((order, i) => (
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
    </div>
  );
}

function OrderActions({
  order,
  suppliers,
  locations,
  productName,
  uomCode,
  receivingId,
  onOpenReceive,
  receiveForm,
  editingId,
  onOpenEdit,
  editForm,
  onSubmitEdit,
  isUpdating,
  historyId,
  onOpenHistory,
  onValidate,
  onApprove,
  onPlaceOrder,
  onRefuse,
  onCancel,
  onReceive,
  isReceiving,
  pendingAction,
}: {
  order: PurchaseOrder;
  suppliers: Partner[];
  locations: Location[];
  productName: (id: string) => string;
  uomCode: (id: string) => string;
  receivingId: string | null;
  onOpenReceive: (open: boolean) => void;
  receiveForm: UseFormReturn<ReceiveForm>;
  editingId: string | null;
  onOpenEdit: (open: boolean) => void;
  editForm: UseFormReturn<EditOrderForm>;
  onSubmitEdit: (input: EditOrderForm) => void;
  isUpdating: boolean;
  historyId: string | null;
  onOpenHistory: (open: boolean) => void;
  onValidate: () => void;
  onApprove: () => void;
  onPlaceOrder: () => void;
  onRefuse: () => void;
  onCancel: () => void;
  onReceive: (input: ReceiveForm) => void;
  isReceiving: boolean;
  pendingAction: boolean;
}) {
  const { session } = useAuth();
  const token = session!.token;
  const { t } = useI18n();
  const isReceiveDialogOpen = receivingId === order.id;
  const isHistoryDialogOpen = historyId === order.id;
  const canCancel = order.status !== "fully_received" && order.status !== "canceled" && order.status !== "refused";
  const canReceive = order.status === "ordered" || order.status === "partially_received";

  const { data: lines = [] } = useQuery({
    queryKey: ["procurement", "purchase-orders", order.id, "lines"],
    queryFn: () => listPurchaseOrderLines(token, order.id),
    enabled: isReceiveDialogOpen || isHistoryDialogOpen,
  });

  const { data: receipts = [] } = useQuery({
    queryKey: ["procurement", "purchase-orders", order.id, "receipts"],
    queryFn: () => listPurchaseOrderReceipts(token, order.id),
    enabled: isHistoryDialogOpen,
  });

  const { fields, replace } = useFieldArray({ control: receiveForm.control, name: "lines" });

  useEffect(() => {
    if (!isReceiveDialogOpen) return;
    const outstanding = lines.filter((line: PurchaseOrderLine) => line.quantity_received < line.quantity_ordered);
    replace(
      outstanding.map((line) => ({
        purchase_order_line_id: line.id,
        productLabel: productName(line.product_id),
        outstanding: line.quantity_ordered - line.quantity_received,
        uomLabel: uomCode(line.uom_id),
        quantity: 0,
        lot_number: "",
      })),
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isReceiveDialogOpen, lines]);

  return (
        <div className="flex justify-end gap-2">
          <Dialog open={editingId === order.id} onOpenChange={onOpenEdit}>
            <DialogTrigger asChild>
              <Button size="sm" variant="outline">
                <Pencil className="h-3.5 w-3.5" />
                {t("procurement.edit")}
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>{t("procurement.dialog.editTitle")}</DialogTitle>
                <DialogDescription>{t("procurement.dialog.editDescription")}</DialogDescription>
              </DialogHeader>
              <form className="space-y-4" onSubmit={editForm.handleSubmit(onSubmitEdit)}>
                <div className="space-y-1.5">
                  <Label htmlFor={`edit_supplier_${order.id}`}>{t("procurement.field.supplier")}</Label>
                  <Select id={`edit_supplier_${order.id}`} {...editForm.register("supplier_id")}>
                    <option value="">—</option>
                    {suppliers.map((supplier) => (
                      <option key={supplier.id} value={supplier.id}>
                        {supplier.name}
                      </option>
                    ))}
                  </Select>
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor={`edit_currency_${order.id}`}>{t("procurement.field.currency")}</Label>
                  <Input id={`edit_currency_${order.id}`} {...editForm.register("currency_code")} />
                  {editForm.formState.errors.currency_code && (
                    <p className="text-sm text-destructive">{editForm.formState.errors.currency_code.message}</p>
                  )}
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor={`edit_order_date_${order.id}`}>{t("procurement.field.orderDate")}</Label>
                  <Input id={`edit_order_date_${order.id}`} type="date" {...editForm.register("order_date")} />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor={`edit_expected_date_${order.id}`}>{t("procurement.field.expectedDate")}</Label>
                  <Input id={`edit_expected_date_${order.id}`} type="date" {...editForm.register("expected_date")} />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor={`edit_notes_${order.id}`}>{t("procurement.field.notes")}</Label>
                  <Input id={`edit_notes_${order.id}`} {...editForm.register("notes")} />
                </div>
                <Button type="submit" className="w-full" disabled={isUpdating}>
                  {isUpdating ? t("procurement.updating") : t("procurement.update")}
                </Button>
              </form>
            </DialogContent>
          </Dialog>
          <Dialog open={isHistoryDialogOpen} onOpenChange={onOpenHistory}>
            <DialogTrigger asChild>
              <Button size="sm" variant="ghost">
                <History className="h-3.5 w-3.5" />
                {t("procurement.viewReceipts")}
              </Button>
            </DialogTrigger>
            <DialogContent className="max-w-2xl">
              <DialogHeader>
                <DialogTitle>{t("procurement.receipt.history.title")}</DialogTitle>
                <DialogDescription>{t("procurement.receipt.history.description")}</DialogDescription>
              </DialogHeader>
              {receipts.length === 0 ? (
                <p className="text-sm text-muted-foreground">{t("procurement.receipt.history.empty")}</p>
              ) : (
                <div className="space-y-4">
                  {receipts.map((receipt) => (
                    <ReceiptHistoryCard
                      key={receipt.id}
                      receipt={receipt}
                      poLines={lines}
                      productName={productName}
                      uomCode={uomCode}
                      isOpen={isHistoryDialogOpen}
                    />
                  ))}
                </div>
              )}
            </DialogContent>
          </Dialog>
          {order.status === "draft" && (
            <Button size="sm" variant="outline" onClick={onValidate} disabled={pendingAction}>
              <ShieldCheck className="h-3.5 w-3.5" />
              {t("procurement.action.validate")}
            </Button>
          )}
          {order.status === "validated" && (
            <>
              <Button size="sm" variant="outline" onClick={onApprove} disabled={pendingAction}>
                <CheckCircle2 className="h-3.5 w-3.5" />
                {t("procurement.action.approve")}
              </Button>
              <Button size="sm" variant="ghost" onClick={onRefuse} disabled={pendingAction}>
                <XCircle className="h-3.5 w-3.5" />
                {t("procurement.action.refuse")}
              </Button>
            </>
          )}
          {order.status === "approved" && (
            <Button size="sm" variant="outline" onClick={onPlaceOrder} disabled={pendingAction}>
              <Package className="h-3.5 w-3.5" />
              {t("procurement.action.placeOrder")}
            </Button>
          )}
          {canReceive && (
            <Dialog open={isReceiveDialogOpen} onOpenChange={onOpenReceive}>
              <DialogTrigger asChild>
                <Button size="sm" variant="outline">
                  <PackageCheck className="h-3.5 w-3.5" />
                  {t("procurement.action.receive")}
                </Button>
              </DialogTrigger>
              <DialogContent className="max-w-2xl">
                <DialogHeader>
                  <DialogTitle>{t("procurement.receipt.dialog.title")}</DialogTitle>
                  <DialogDescription>{t("procurement.receipt.dialog.description")}</DialogDescription>
                </DialogHeader>
                <form className="space-y-4" onSubmit={receiveForm.handleSubmit(onReceive)}>
                  <div className="grid grid-cols-2 gap-3">
                    <div className="space-y-1.5">
                      <Label htmlFor={`receive_location_${order.id}`}>{t("procurement.field.location")}</Label>
                      <Select id={`receive_location_${order.id}`} {...receiveForm.register("location_id")}>
                        <option value="">—</option>
                        {locations.map((location) => (
                          <option key={location.id} value={location.id}>
                            {location.name}
                          </option>
                        ))}
                      </Select>
                      {receiveForm.formState.errors.location_id && (
                        <p className="text-sm text-destructive">{receiveForm.formState.errors.location_id.message}</p>
                      )}
                    </div>
                    <div className="space-y-1.5">
                      <Label htmlFor={`receive_invoice_${order.id}`}>{t("procurement.field.invoiceNumber")}</Label>
                      <Input id={`receive_invoice_${order.id}`} {...receiveForm.register("invoice_number")} />
                    </div>
                    <div className="space-y-1.5">
                      <Label htmlFor={`receive_invoice_date_${order.id}`}>{t("procurement.field.invoiceDate")}</Label>
                      <Input id={`receive_invoice_date_${order.id}`} type="date" {...receiveForm.register("invoice_date")} />
                    </div>
                    <div className="space-y-1.5">
                      <Label htmlFor={`receive_origin_${order.id}`}>{t("procurement.field.originCountry")}</Label>
                      <Input id={`receive_origin_${order.id}`} {...receiveForm.register("origin_country")} />
                    </div>
                    <div className="space-y-1.5">
                      <Label htmlFor={`receive_carrier_${order.id}`}>{t("procurement.field.carrier")}</Label>
                      <Input id={`receive_carrier_${order.id}`} {...receiveForm.register("carrier")} />
                    </div>
                  </div>

                  <div className="space-y-1.5 rounded-lg border border-border p-3">
                    <Label className="text-xs text-muted-foreground">{t("procurement.field.landedCost")}</Label>
                    <div className="grid grid-cols-3 gap-2">
                      <Input type="number" step="any" placeholder={t("procurement.field.baseCost")} {...receiveForm.register("base_cost")} />
                      <Input type="number" step="any" placeholder={t("procurement.field.licenseFee")} {...receiveForm.register("license_fee")} />
                      <Input type="number" step="any" placeholder={t("procurement.field.insuranceFee")} {...receiveForm.register("insurance_fee")} />
                      <Input type="number" step="any" placeholder={t("procurement.field.transitFee")} {...receiveForm.register("transit_fee")} />
                      <Input type="number" step="any" placeholder={t("procurement.field.transportFee")} {...receiveForm.register("transport_fee")} />
                      <Input type="number" step="any" placeholder={t("procurement.field.customsDuty")} {...receiveForm.register("customs_duty")} />
                    </div>
                  </div>

                  <div className="space-y-2 rounded-lg border border-border p-3">
                    <Label>{t("procurement.receipt.field.lines")}</Label>
                    {fields.length === 0 && <p className="text-xs text-muted-foreground">{t("procurement.receipt.noOutstandingLines")}</p>}
                    {fields.map((field, lineIndex) => (
                      <div key={field.id} className="flex items-center gap-2">
                        <span className="w-40 truncate text-sm">{field.productLabel}</span>
                        <span className="w-24 text-xs text-muted-foreground">
                          {t("procurement.receipt.outstanding")}: {field.outstanding} {field.uomLabel}
                        </span>
                        <Input
                          type="number"
                          step="any"
                          className="w-24"
                          placeholder={t("procurement.field.quantity")}
                          {...receiveForm.register(`lines.${lineIndex}.quantity` as const)}
                        />
                        <Input
                          className="w-32"
                          placeholder={t("procurement.field.lotNumber")}
                          {...receiveForm.register(`lines.${lineIndex}.lot_number` as const)}
                        />
                      </div>
                    ))}
                  </div>

                  <Button type="submit" className="w-full" disabled={isReceiving}>
                    {isReceiving ? t("procurement.receipt.confirming") : t("procurement.receipt.confirm")}
                  </Button>
                </form>
              </DialogContent>
            </Dialog>
          )}
          {canCancel && (
            <Button size="sm" variant="ghost" onClick={onCancel} disabled={pendingAction}>
              <XCircle className="h-3.5 w-3.5" />
              {t("procurement.action.cancel")}
            </Button>
          )}
        </div>
  );
}

function ReceiptHistoryCard({
  receipt,
  poLines,
  productName,
  uomCode,
  isOpen,
}: {
  receipt: PurchaseOrderReceipt;
  poLines: PurchaseOrderLine[];
  productName: (id: string) => string;
  uomCode: (id: string) => string;
  isOpen: boolean;
}) {
  const { session } = useAuth();
  const token = session!.token;
  const { t } = useI18n();

  const { data: receiptLines = [] } = useQuery({
    queryKey: ["procurement", "receipts", receipt.id, "lines"],
    queryFn: () => listPurchaseOrderReceiptLines(token, receipt.id),
    enabled: isOpen,
  });

  const lineLabel = (purchaseOrderLineId: string) => {
    const poLine = poLines.find((line) => line.id === purchaseOrderLineId);
    return poLine ? productName(poLine.product_id) : purchaseOrderLineId;
  };
  const lineUom = (purchaseOrderLineId: string) => {
    const poLine = poLines.find((line) => line.id === purchaseOrderLineId);
    return poLine ? uomCode(poLine.uom_id) : "";
  };

  return (
    <Card>
      <CardContent className="space-y-2 p-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <Badge variant={receipt.status === "confirmed" ? "success" : "default"} dot>
              {t(`procurement.receipt.status.${receipt.status}` as Parameters<typeof t>[0])}
            </Badge>
            <span className="text-sm text-muted-foreground">{receipt.invoice_number ?? "—"}</span>
          </div>
          <span className="text-sm tabular-nums text-muted-foreground">
            {receipt.invoice_date ?? "—"} · {receipt.carrier ?? "—"} · {receipt.total_cost.toLocaleString()} {t("procurement.receipt.totalCostSuffix")}
          </span>
        </div>
        <ul className="space-y-1 text-sm">
          {receiptLines.map((line) => (
            <li key={line.id} className="flex justify-between text-muted-foreground">
              <span>
                {lineLabel(line.purchase_order_line_id)}
                {line.lot_number ? ` · ${t("procurement.field.lotNumber")}: ${line.lot_number}` : ""}
              </span>
              <span className="tabular-nums">
                {line.quantity} {lineUom(line.purchase_order_line_id)}
              </span>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}
