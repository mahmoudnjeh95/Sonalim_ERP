import { useState } from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm, type UseFormReturn } from "react-hook-form";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Copy, Eye, FileText, Pencil, Plus, Printer, Send, ShoppingCart, ThumbsDown, ThumbsUp } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { z } from "zod";
import { ApiError } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { formatXofWithCode } from "../../lib/currency";
import { useI18n } from "../../lib/i18n";
import { productRequiresIntegerQuantity } from "../../lib/units";
import { useColumnFilters, type FilterField } from "../../lib/useColumnFilters";
import { useTableColumns, type ColumnDef } from "../../lib/useTableColumns";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "../../components/ui/dialog";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Select } from "../../components/ui/select";
import { ResizableTableHead, Table, TableBody, TableCell, TableHeader, TableRow } from "../../components/ui/table";
import { ColumnFilterRow } from "../../components/patterns/ColumnFilterRow";
import { ColumnVisibilityMenu } from "../../components/patterns/ColumnVisibilityMenu";
import { EmptyState } from "../../components/patterns/EmptyState";
import { FilterTabs } from "../../components/patterns/FilterTabs";
import { StatCard } from "../../components/patterns/StatCard";
import { TableLoadingRow } from "../../components/patterns/AppLoader";
import { listOpportunities } from "../crm/opportunities/api";
import { listPartners } from "../partners/api";
import { useProductCatalog } from "../products/catalog";
import { listLocations, listUoms } from "../warehouse/api";
import { openDocument } from "../warehouse/printDocument";
import { newPricedLine, PricedLinesFields, pricedLineSchema, useSalesSettings, type PricedFormShape } from "./PricedLinesFields";
import {
  acceptQuote,
  convertQuote,
  createQuote,
  getQuoteStats,
  listQuotes,
  QUOTES_QUERY_KEY,
  refuseQuote,
  reviseQuote,
  sendQuote,
  updateQuote,
  type Quote,
  type QuoteStatus,
} from "./quotesApi";

type Key = Parameters<ReturnType<typeof useI18n>["t"]>[0];

const quoteSchema = z.object({
  partner_id: z.string().min(1, "Required"),
  location_id: z.string().optional(),
  quote_date: z.string().min(1, "Required"),
  valid_until: z.string().optional(),
  opportunity_id: z.string().optional(),
  note: z.string().optional(),
  discount_rate: z.coerce.number().min(0).max(100).default(0),
  lines: z.array(pricedLineSchema).min(1, "Add at least one line"),
});
type QuoteForm = z.infer<typeof quoteSchema>;

const STATUS_VARIANT: Record<QuoteStatus, "default" | "primary" | "success" | "destructive" | "warning" | "outline"> = {
  draft: "default",
  sent: "primary",
  accepted: "success",
  refused: "destructive",
  expired: "warning",
  superseded: "outline",
};

export function QuoteStatusBadge({ status }: { status: QuoteStatus }) {
  const { t } = useI18n();
  return (
    <Badge variant={STATUS_VARIANT[status]} dot>
      {t(`sales.quotes.status.${status}` as Key)}
    </Badge>
  );
}

const today = () => new Date().toISOString().slice(0, 10);
type StatusFilter = "all" | "draft" | "sent" | "accepted" | "refused" | "expired";

export function QuotesPage() {
  const { session, hasPermission } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const canManage = hasPermission("sales.manage_quotes");
  const canOrder = hasPermission("sales.manage_orders");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<Quote | null>(null);
  const [detailId, setDetailId] = useState<string | null>(null);

  const { data: quotes = [], isLoading } = useQuery({ queryKey: QUOTES_QUERY_KEY, queryFn: () => listQuotes(token) });
  const { data: stats } = useQuery({ queryKey: [...QUOTES_QUERY_KEY, "stats"], queryFn: () => getQuoteStats(token) });
  const { data: partners = [] } = useQuery({ queryKey: ["core", "partners"], queryFn: () => listPartners(token) });
  const { data: locations = [] } = useQuery({ queryKey: ["warehouse", "locations"], queryFn: () => listLocations(token) });
  const { data: uoms = [] } = useQuery({ queryKey: ["core", "uoms"], queryFn: () => listUoms(token) });
  const canSeeOpportunities = hasPermission("crm.view_opportunities");
  const { data: opportunities = [] } = useQuery({
    queryKey: ["crm", "opportunities"],
    queryFn: () => listOpportunities(token),
    enabled: canSeeOpportunities,
  });
  const { catalog } = useProductCatalog();
  const products = catalog.filter((product) => product.is_sellable);
  const customers = partners.filter((p) => (p.kind === "customer" || p.kind === "both") && p.status === "active");
  const defaultVat = Number(useSalesSettings().data?.default_vat_rate ?? 18);
  const detail = quotes.find((quote) => quote.id === detailId) ?? null;

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: QUOTES_QUERY_KEY });
  };
  const fail = (key: Key) => (error: unknown) => toast.error(t(key), { description: error instanceof ApiError ? error.message : undefined });

  const form = useForm<QuoteForm>({
    resolver: zodResolver(quoteSchema),
    defaultValues: { partner_id: "", location_id: "", quote_date: today(), valid_until: "", opportunity_id: "", note: "", discount_rate: 0, lines: [newPricedLine(18)] },
  });
  const partnerId = form.watch("partner_id");

  function openCreate() {
    setEditing(null);
    form.reset({ partner_id: "", location_id: "", quote_date: today(), valid_until: "", opportunity_id: "", note: "", discount_rate: 0, lines: [newPricedLine(defaultVat)] });
    setFormOpen(true);
  }

  function openEdit(quote: Quote) {
    setEditing(quote);
    form.reset({
      partner_id: quote.partner_id,
      location_id: quote.location_id ?? "",
      quote_date: quote.quote_date,
      valid_until: quote.valid_until,
      opportunity_id: quote.opportunity_id ?? "",
      note: quote.note ?? "",
      discount_rate: Number(quote.discount_rate),
      lines: quote.lines.map((line) => ({
        product_id: line.product_id,
        quantity: Number(line.quantity),
        unit_price: Number(line.unit_price),
        discount_rate: Number(line.discount_rate),
        vat_rate: Number(line.vat_rate),
        tax_code: line.tax_code ?? null,
        tax_manual: true,
        price_list_id: line.price_list_id,
      })),
    });
    setFormOpen(true);
  }

  const saveMutation = useMutation({
    mutationFn: (input: QuoteForm) => {
      const body = {
        partner_id: input.partner_id,
        location_id: input.location_id || null,
        quote_date: input.quote_date,
        valid_until: input.valid_until || null,
        opportunity_id: input.opportunity_id || null,
        note: input.note || null,
        discount_rate: input.discount_rate,
        lines: input.lines.map((line) => ({
          product_id: line.product_id,
          quantity: line.quantity,
          unit_price: line.unit_price,
          discount_rate: line.discount_rate,
          vat_rate: line.vat_rate,
          tax_code: line.tax_code ?? null,
          price_list_id: line.price_list_id ?? null,
        })),
      };
      return editing ? updateQuote(token, editing.id, body) : createQuote(token, body);
    },
    onSuccess: (quote) => {
      invalidate();
      setFormOpen(false);
      setDetailId(quote.id);
      toast.success(t(editing ? "sales.quotes.updated" : "sales.quotes.created"));
    },
    onError: fail("sales.quotes.saveError"),
  });

  const actionMutation = useMutation({
    mutationFn: ({ quote, action, reason }: { quote: Quote; action: "send" | "accept" | "refuse" | "revise"; reason?: string | null }) => {
      if (action === "send") return sendQuote(token, quote.id);
      if (action === "accept") return acceptQuote(token, quote.id);
      if (action === "refuse") return refuseQuote(token, quote.id, reason ?? null);
      return reviseQuote(token, quote.id);
    },
    onSuccess: (quote, { action }) => {
      invalidate();
      setDetailId(quote.id);
      toast.success(t(`sales.quotes.done.${action}` as Key));
    },
    onError: fail("sales.quotes.actionError"),
  });

  const [convertLocation, setConvertLocation] = useState("");
  const [convertShipDate, setConvertShipDate] = useState("");
  const convertMutation = useMutation({
    mutationFn: (quote: Quote) =>
      convertQuote(token, quote.id, { location_id: convertLocation || quote.location_id, requested_ship_date: convertShipDate || null }),
    onSuccess: () => {
      invalidate();
      queryClient.invalidateQueries({ queryKey: ["sales", "orders"] });
      toast.success(t("sales.quotes.done.convert"));
      navigate("/sales");
    },
    onError: fail("sales.quotes.actionError"),
  });

  function print(quote: Quote, printNow: boolean) {
    const money = (value: string | number) => formatXofWithCode(Number(value));
    const ok = openDocument(
      {
        title: `${t("sales.quotes.document")} ${quote.display_number}`,
        fields: [
          [t("sales.field.partnerId"), quote.partner_name ?? "—"],
          [t("sales.quotes.field.date"), quote.quote_date],
          [t("sales.quotes.field.validUntil"), quote.valid_until],
          [t("sales.pricing.documentDiscount"), `${Number(quote.discount_rate)} %`],
        ],
        headers: [
          t("sales.field.productId"),
          t("sales.field.qty"),
          t("sales.field.unitPrice"),
          t("sales.pricing.discountPct"),
          t("sales.pricing.vatPct"),
          t("sales.pricing.exclTax"),
        ],
        rows: quote.lines.map((line) => [
          `${line.sku} — ${line.product_name}`,
          Number(line.quantity),
          money(line.unit_price),
          `${Number(line.discount_rate)} %`,
          `${Number(line.vat_rate)} %`,
          money(line.net_amount),
        ]),
        footer: [
          `${t("sales.pricing.gross")} : ${money(quote.totals.gross)}`,
          `${t("sales.pricing.discount")} : ${money(quote.totals.discount)}`,
          `${t("sales.pricing.exclTax")} : ${money(quote.totals.excl_tax)}`,
          `${t("sales.pricing.vat")} : ${money(quote.totals.vat)}`,
          `${t("sales.pricing.inclTax")} : ${money(quote.totals.incl_tax)}`,
          quote.note ? `\n${quote.note}` : "",
        ].join("\n"),
      },
      { print: printNow },
    );
    if (!ok) toast.error(t("sales.quotes.popupBlocked"));
  }

  const statusFiltered = statusFilter === "all" ? quotes : quotes.filter((quote) => quote.status === statusFilter);
  const filterFields: FilterField<Quote>[] = [
    { key: "number", kind: "text", getValue: (q) => q.display_number },
    { key: "partner", kind: "text", getValue: (q) => q.partner_name ?? "" },
    { key: "quote_date", kind: "text", getValue: (q) => q.quote_date },
    { key: "total", kind: "range", getValue: (q) => Number(q.totals.incl_tax) },
  ];
  const columnFilters = useColumnFilters(filterFields);
  const filtered = columnFilters.apply(statusFiltered);

  const columns: ColumnDef<Quote>[] = [
    {
      key: "number",
      header: t("sales.quotes.column.number"),
      defaultWidth: 170,
      cell: (q) => (
        <button type="button" className="font-medium text-primary underline-offset-2 hover:underline" onClick={() => setDetailId(q.id)}>
          {q.display_number}
        </button>
      ),
      filterCell: { type: "text", value: columnFilters.text.number ?? "", onChange: (v) => columnFilters.setTextValue("number", v), placeholder: t("sales.quotes.column.number") },
      sortValue: (q) => `${q.number}-${String(q.revision).padStart(3, "0")}`,
    },
    {
      key: "partner",
      header: t("sales.column.partner"),
      defaultWidth: 190,
      cell: (q) => q.partner_name ?? "—",
      filterCell: { type: "text", value: columnFilters.text.partner ?? "", onChange: (v) => columnFilters.setTextValue("partner", v), placeholder: t("sales.column.partner") },
      sortValue: (q) => q.partner_name ?? "",
    },
    {
      key: "quote_date",
      header: t("sales.quotes.field.date"),
      defaultWidth: 120,
      cell: (q) => q.quote_date,
      filterCell: { type: "text", value: columnFilters.text.quote_date ?? "", onChange: (v) => columnFilters.setTextValue("quote_date", v), placeholder: "2026-" },
      sortValue: (q) => q.quote_date,
    },
    { key: "valid_until", header: t("sales.quotes.field.validUntil"), defaultWidth: 120, cell: (q) => q.valid_until, sortValue: (q) => q.valid_until },
    {
      key: "total",
      header: t("sales.pricing.inclTax"),
      defaultWidth: 150,
      cellClassName: "tabular-nums",
      cell: (q) => formatXofWithCode(Number(q.totals.incl_tax)),
      filterCell: {
        type: "range",
        min: columnFilters.range.total?.min ?? "",
        max: columnFilters.range.total?.max ?? "",
        onMinChange: (v) => columnFilters.setRangeValue("total", "min", v),
        onMaxChange: (v) => columnFilters.setRangeValue("total", "max", v),
      },
      sortValue: (q) => Number(q.totals.incl_tax),
    },
    { key: "status", header: t("sales.column.status"), defaultWidth: 130, cell: (q) => <QuoteStatusBadge status={q.status} />, sortValue: (q) => q.status },
    {
      key: "order",
      header: t("sales.quotes.column.order"),
      defaultWidth: 110,
      cell: (q) => (q.order_id ? <span className="text-success">{t("sales.quotes.ordered")}</span> : <span className="text-muted-foreground">—</span>),
    },
    {
      key: "action",
      header: t("sales.column.action"),
      defaultWidth: 110,
      alwaysVisible: true,
      headerClassName: "text-right",
      cell: (q) => (
        <div className="flex justify-end">
          <Button size="sm" variant="outline" onClick={() => setDetailId(q.id)}>
            <Eye className="h-3.5 w-3.5" />
            {t("sales.quotes.open")}
          </Button>
        </div>
      ),
    },
  ];
  const table = useTableColumns("sales.quotes", columns);
  const rows = table.sortRows(filtered);
  const conversion = stats?.conversion_rate;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">{t("sales.quotes.title")}</h1>
        <p className="text-sm text-muted-foreground">{t("sales.quotes.subtitle")}</p>
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <StatCard label={t("sales.quotes.stat.open")} value={Math.round(Number(stats?.open_value ?? 0))} unit="XOF" icon={<FileText className="h-5 w-5" />} />
        <StatCard label={t("sales.quotes.stat.accepted")} value={Math.round(Number(stats?.accepted_value ?? 0))} unit="XOF" accent="success" icon={<CheckCircle2 className="h-5 w-5" />} />
        <StatCard
          label={t("sales.quotes.stat.conversion")}
          value={conversion == null ? null : Number(conversion)}
          unit="%"
          decimals={1}
          accent="accent"
          icon={<ShoppingCart className="h-5 w-5" />}
        />
      </div>

      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center gap-3">
            <CardTitle>{t("sales.quotes.table")}</CardTitle>
            <FilterTabs
              value={statusFilter}
              onChange={setStatusFilter}
              options={[
                { value: "all", label: t("common.all") },
                { value: "draft", label: t("sales.quotes.status.draft") },
                { value: "sent", label: t("sales.quotes.status.sent") },
                { value: "accepted", label: t("sales.quotes.status.accepted") },
                { value: "refused", label: t("sales.quotes.status.refused") },
                { value: "expired", label: t("sales.quotes.status.expired") },
              ]}
            />
            {columnFilters.isActive && (
              <Button variant="ghost" size="sm" onClick={columnFilters.reset}>
                {t("common.clearFilters")}
              </Button>
            )}
            <ColumnVisibilityMenu columns={columns} isVisible={table.isVisible} onToggle={table.toggleVisible} onReset={table.resetAll} />
            {canManage && (
              <Button className="ml-auto" onClick={openCreate}>
                <Plus className="h-4 w-4" />
                {t("sales.quotes.new")}
              </Button>
            )}
          </div>
        </CardHeader>
        <CardContent className="overflow-x-auto p-0">
          <Table colWidths={table.colWidths}>
            <TableHeader>
              <TableRow>
                {table.visibleColumns.map((column) => (
                  <ResizableTableHead
                    key={column.key}
                    width={table.getWidth(column.key)}
                    onResize={(width) => table.setWidth(column.key, width)}
                    className={column.headerClassName}
                    sortDirection={table.sortDirectionFor(column.key)}
                    onSort={column.sortValue ? () => table.toggleSort(column.key) : undefined}
                  >
                    {column.header}
                  </ResizableTableHead>
                ))}
              </TableRow>
              <ColumnFilterRow cells={table.visibleColumns.map((column) => column.filterCell ?? { type: "blank" })} />
            </TableHeader>
            <TableBody>
              {isLoading && <TableLoadingRow colSpan={table.visibleColumns.length} />}
              {!isLoading && rows.length === 0 && (
                <TableRow>
                  <TableCell colSpan={table.visibleColumns.length} className="p-0">
                    <EmptyState icon={<FileText className="h-5 w-5" />} title={t("sales.quotes.empty.title")} description={t("sales.quotes.empty.description")} />
                  </TableCell>
                </TableRow>
              )}
              {rows.map((quote) => (
                <TableRow key={quote.id}>
                  {table.visibleColumns.map((column) => (
                    <TableCell key={column.key} className={column.cellClassName}>
                      {column.cell(quote)}
                    </TableCell>
                  ))}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <Dialog open={formOpen} onOpenChange={setFormOpen}>
        <DialogContent className="max-h-[90vh] max-w-3xl overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{editing ? `${t("sales.quotes.editTitle")} ${editing.display_number}` : t("sales.quotes.new")}</DialogTitle>
            <DialogDescription>{t("sales.quotes.formHint")}</DialogDescription>
          </DialogHeader>
          <form className="space-y-4" onSubmit={form.handleSubmit((input) => saveMutation.mutate(input))}>
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="space-y-1.5">
                <Label htmlFor="quote_partner">{t("sales.field.partnerId")}</Label>
                <Select id="quote_partner" disabled={!!editing} {...form.register("partner_id")}>
                  <option value="">—</option>
                  {customers.map((partner) => (
                    <option key={partner.id} value={partner.id}>
                      {partner.name}
                    </option>
                  ))}
                </Select>
                {form.formState.errors.partner_id && <p className="text-sm text-destructive">{form.formState.errors.partner_id.message}</p>}
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="quote_location">{t("sales.field.location")}</Label>
                <Select id="quote_location" {...form.register("location_id")}>
                  <option value="">—</option>
                  {locations.map((location) => (
                    <option key={location.id} value={location.id}>
                      {location.name}
                    </option>
                  ))}
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="quote_date">{t("sales.quotes.field.date")}</Label>
                <Input id="quote_date" type="date" {...form.register("quote_date")} />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="quote_valid">{t("sales.quotes.field.validUntil")}</Label>
                <Input id="quote_valid" type="date" {...form.register("valid_until")} />
                <p className="text-xs text-muted-foreground">{t("sales.quotes.validityHint")}</p>
              </div>
              {canSeeOpportunities && (
                <div className="space-y-1.5 sm:col-span-2">
                  <Label htmlFor="quote_opportunity">{t("sales.quotes.field.opportunity")}</Label>
                  <Select id="quote_opportunity" {...form.register("opportunity_id")}>
                    <option value="">—</option>
                    {opportunities
                      .filter((opportunity) => !partnerId || opportunity.partner_id === partnerId)
                      .map((opportunity) => (
                        <option key={opportunity.id} value={opportunity.id}>
                          {opportunity.name}
                        </option>
                      ))}
                  </Select>
                </div>
              )}
            </div>
            <PricedLinesFields
              form={form as unknown as UseFormReturn<PricedFormShape>}
              products={products}
              idPrefix="quote"
              quantityStep={(productId) => (productRequiresIntegerQuantity(productId, products, uoms) ? "1" : "any")}
            />
            <div className="space-y-1.5">
              <Label htmlFor="quote_note">{t("sales.quotes.field.note")}</Label>
              <Input id="quote_note" {...form.register("note")} />
            </div>
            <Button type="submit" className="w-full" disabled={saveMutation.isPending}>
              {editing ? t("sales.update") : t("sales.quotes.create")}
            </Button>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog open={!!detail} onOpenChange={(open) => !open && setDetailId(null)}>
        <DialogContent className="max-h-[90vh] max-w-3xl overflow-y-auto">
          {detail && (
            <>
              <DialogHeader>
                <DialogTitle className="flex flex-wrap items-center gap-2">
                  {t("sales.quotes.document")} {detail.display_number} <QuoteStatusBadge status={detail.status} />
                </DialogTitle>
                <DialogDescription>
                  {detail.partner_name} · {t("sales.quotes.field.date")} {detail.quote_date} · {t("sales.quotes.field.validUntil")} {detail.valid_until}
                </DialogDescription>
              </DialogHeader>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b text-left text-muted-foreground">
                      <th className="py-1.5 pr-2">{t("sales.field.productId")}</th>
                      <th className="py-1.5 pr-2 text-right">{t("sales.field.qty")}</th>
                      <th className="py-1.5 pr-2 text-right">{t("sales.field.unitPrice")}</th>
                      <th className="py-1.5 pr-2 text-right">{t("sales.pricing.discountPct")}</th>
                      <th className="py-1.5 pr-2 text-right">{t("sales.pricing.vatPct")}</th>
                      <th className="py-1.5 text-right">{t("sales.pricing.exclTax")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {detail.lines.map((line) => (
                      <tr key={line.id} className="border-b last:border-0">
                        <td className="py-1.5 pr-2">{line.product_name}</td>
                        <td className="py-1.5 pr-2 text-right tabular-nums">{Number(line.quantity)}</td>
                        <td className="py-1.5 pr-2 text-right tabular-nums">{formatXofWithCode(Number(line.unit_price))}</td>
                        <td className="py-1.5 pr-2 text-right tabular-nums">{Number(line.discount_rate)} %</td>
                        <td className="py-1.5 pr-2 text-right tabular-nums">{Number(line.vat_rate)} %</td>
                        <td className="py-1.5 text-right tabular-nums">{formatXofWithCode(Number(line.net_amount))}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <dl className="ml-auto grid w-full max-w-xs grid-cols-2 gap-x-4 gap-y-1 text-sm">
                <dt className="text-muted-foreground">{t("sales.pricing.discount")}</dt>
                <dd className="text-right tabular-nums">− {formatXofWithCode(Number(detail.totals.discount))}</dd>
                <dt className="text-muted-foreground">{t("sales.pricing.exclTax")}</dt>
                <dd className="text-right tabular-nums">{formatXofWithCode(Number(detail.totals.excl_tax))}</dd>
                <dt className="text-muted-foreground">{t("sales.pricing.vat")}</dt>
                <dd className="text-right tabular-nums">{formatXofWithCode(Number(detail.totals.vat))}</dd>
                <dt className="font-medium">{t("sales.pricing.inclTax")}</dt>
                <dd className="text-right font-medium tabular-nums">{formatXofWithCode(Number(detail.totals.incl_tax))}</dd>
              </dl>
              {detail.note && <p className="text-sm text-muted-foreground">{detail.note}</p>}
              {detail.refusal_reason && (
                <p className="text-sm text-destructive">
                  {t("sales.quotes.refusalReason")} : {detail.refusal_reason}
                </p>
              )}
              <div className="flex flex-wrap gap-2 border-t pt-3">
                <Button size="sm" variant="outline" onClick={() => print(detail, false)}>
                  <Eye className="h-3.5 w-3.5" />
                  {t("sales.quotes.preview")}
                </Button>
                <Button size="sm" variant="outline" onClick={() => print(detail, true)}>
                  <Printer className="h-3.5 w-3.5" />
                  {t("sales.quotes.print")}
                </Button>
                {canManage && detail.status === "draft" && (
                  <Button size="sm" variant="outline" onClick={() => { setDetailId(null); openEdit(detail); }}>
                    <Pencil className="h-3.5 w-3.5" />
                    {t("sales.edit")}
                  </Button>
                )}
                {canManage && detail.status === "draft" && (
                  <Button size="sm" onClick={() => actionMutation.mutate({ quote: detail, action: "send" })} disabled={actionMutation.isPending}>
                    <Send className="h-3.5 w-3.5" />
                    {t("sales.quotes.send")}
                  </Button>
                )}
                {canManage && (detail.status === "draft" || detail.status === "sent") && (
                  <>
                    <Button size="sm" variant="outline" onClick={() => actionMutation.mutate({ quote: detail, action: "accept" })} disabled={actionMutation.isPending}>
                      <ThumbsUp className="h-3.5 w-3.5" />
                      {t("sales.quotes.accept")}
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={actionMutation.isPending}
                      onClick={() => {
                        const reason = window.prompt(t("sales.quotes.refusePrompt"));
                        if (reason !== null) actionMutation.mutate({ quote: detail, action: "refuse", reason });
                      }}
                    >
                      <ThumbsDown className="h-3.5 w-3.5" />
                      {t("sales.quotes.refuse")}
                    </Button>
                  </>
                )}
                {canManage && ["draft", "sent", "refused", "expired"].includes(detail.status) && (
                  <Button size="sm" variant="outline" onClick={() => actionMutation.mutate({ quote: detail, action: "revise" })} disabled={actionMutation.isPending}>
                    <Copy className="h-3.5 w-3.5" />
                    {t("sales.quotes.revise")}
                  </Button>
                )}
              </div>
              {canManage && canOrder && detail.status === "accepted" && !detail.order_id && (
                <div className="grid gap-2 rounded-md border p-3 sm:grid-cols-[1fr_1fr_auto] sm:items-end">
                  <div className="space-y-1.5">
                    <Label htmlFor="convert_location">{t("sales.field.location")}</Label>
                    <Select id="convert_location" value={convertLocation || detail.location_id || ""} onChange={(e) => setConvertLocation(e.target.value)}>
                      <option value="">—</option>
                      {locations.map((location) => (
                        <option key={location.id} value={location.id}>
                          {location.name}
                        </option>
                      ))}
                    </Select>
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="convert_ship">{t("sales.quotes.field.shipDate")}</Label>
                    <Input id="convert_ship" type="date" value={convertShipDate} onChange={(e) => setConvertShipDate(e.target.value)} />
                  </div>
                  <Button onClick={() => convertMutation.mutate(detail)} disabled={convertMutation.isPending}>
                    <ShoppingCart className="h-4 w-4" />
                    {t("sales.quotes.convert")}
                  </Button>
                </div>
              )}
              {detail.order_id && <p className="text-sm text-success">{t("sales.quotes.orderedHint")}</p>}
            </>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
