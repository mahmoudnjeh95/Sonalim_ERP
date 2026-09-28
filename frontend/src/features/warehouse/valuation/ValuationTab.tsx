import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Coins, Layers } from "lucide-react";
import { useAuth } from "../../../lib/auth";
import { currentLocale, useI18n } from "../../../lib/i18n";
import { useColumnFilters } from "../../../lib/useColumnFilters";
import { useTableColumns, type ColumnDef } from "../../../lib/useTableColumns";
import { formatMoveReference, useReferenceKindLabels } from "../../../lib/stockMoveTypes";
import { Button } from "../../../components/ui/button";
import { Badge } from "../../../components/ui/badge";
import { Table, TableHeader, TableBody, TableRow, TableCell, TableHead, ResizableTableHead } from "../../../components/ui/table";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "../../../components/ui/dialog";
import { FilterTabs } from "../../../components/patterns/FilterTabs";
import { ColumnFilterRow } from "../../../components/patterns/ColumnFilterRow";
import { ColumnVisibilityMenu } from "../../../components/patterns/ColumnVisibilityMenu";
import { EmptyState } from "../../../components/patterns/EmptyState";
import { StatCard } from "../../../components/patterns/StatCard";
import { useProductCatalog } from "../../products/catalog";
import { costLayersQueryKey, getValuation, listCostLayers, VALUATION_QUERY_KEY, type ProductValuation } from "./api";

function formatMoney(amount: number) {
  return new Intl.NumberFormat(currentLocale(), { maximumFractionDigits: 0 }).format(amount);
}

function formatNumber(value: number) {
  return new Intl.NumberFormat(currentLocale(), { maximumFractionDigits: 3 }).format(value);
}

function LayersDialog({ productId, productName, onClose }: { productId: string | null; productName: string; onClose: () => void }) {
  const { t } = useI18n();
  const { session } = useAuth();
  const token = session!.token;
  const referenceKindLabels = useReferenceKindLabels();
  const { data: layers = [] } = useQuery({
    queryKey: productId ? costLayersQueryKey(productId) : ["warehouse", "valuation", "none"],
    queryFn: () => listCostLayers(token, productId!),
    enabled: productId !== null,
  });

  return (
    <Dialog open={productId !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle>
            {t("warehouse.valuation.layers.title")} · {productName}
          </DialogTitle>
          <DialogDescription>{t("warehouse.valuation.layers.description")}</DialogDescription>
        </DialogHeader>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t("warehouse.valuation.layers.received")}</TableHead>
              <TableHead>{t("warehouse.valuation.layers.source")}</TableHead>
              <TableHead>{t("warehouse.valuation.layers.remaining")}</TableHead>
              <TableHead>{t("warehouse.valuation.column.unitCost")}</TableHead>
              <TableHead>{t("warehouse.valuation.column.value")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {layers.map((layer) => {
              const { label, suffix } = formatMoveReference(layer.reference, referenceKindLabels);
              return (
                <TableRow key={layer.id}>
                  <TableCell>{new Date(layer.received_at).toLocaleDateString()}</TableCell>
                  <TableCell title={layer.reference}>{suffix ? `${label} …${suffix}` : label}</TableCell>
                  <TableCell>
                    {formatNumber(layer.quantity_remaining)}
                    <span className="text-muted-foreground"> / {formatNumber(layer.quantity_in)}</span>
                  </TableCell>
                  <TableCell>{layer.unit_cost !== null ? `${formatMoney(layer.unit_cost)} F CFA` : t("warehouse.valuation.unvalued")}</TableCell>
                  <TableCell>
                    {layer.unit_cost !== null ? `${formatMoney(layer.unit_cost * layer.quantity_remaining)} F CFA` : "—"}
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </DialogContent>
    </Dialog>
  );
}

const COVERAGE_FILTERS = ["all", "valued", "unvalued"] as const;
type CoverageFilter = (typeof COVERAGE_FILTERS)[number];

export function ValuationTab() {
  const { t } = useI18n();
  const { session } = useAuth();
  const token = session!.token;
  const { products } = useProductCatalog();
  const { data: valuations = [] } = useQuery({ queryKey: VALUATION_QUERY_KEY, queryFn: () => getValuation(token) });

  const [coverageFilter, setCoverageFilter] = useState<CoverageFilter>("all");
  const [openProductId, setOpenProductId] = useState<string | null>(null);
  const productName = (id: string) => products.find((p) => p.id === id)?.name ?? id;

  const columnFilters = useColumnFilters<ProductValuation>([
    { key: "product", kind: "text", getValue: (row) => productName(row.product_id) },
    { key: "quantity", kind: "range", getValue: (row) => row.quantity },
    { key: "unitCost", kind: "range", getValue: (row) => row.average_unit_cost },
    { key: "value", kind: "range", getValue: (row) => row.value },
    { key: "unvalued", kind: "range", getValue: (row) => row.unvalued_quantity },
  ]);
  const rangeFilter = (key: string) => ({
    type: "range" as const,
    min: columnFilters.range[key]?.min ?? "",
    max: columnFilters.range[key]?.max ?? "",
    onMinChange: (v: string) => columnFilters.setRangeValue(key, "min", v),
    onMaxChange: (v: string) => columnFilters.setRangeValue(key, "max", v),
  });

  const columns: ColumnDef<ProductValuation>[] = [
    {
      key: "product",
      header: t("warehouse.valuation.column.product"),
      cell: (row) => productName(row.product_id),
      filterCell: {
        type: "text",
        placeholder: t("warehouse.valuation.column.product"),
        value: columnFilters.text.product ?? "",
        onChange: (v) => columnFilters.setTextValue("product", v),
      },
    },
    { key: "quantity", header: t("warehouse.valuation.column.quantity"), cell: (row) => formatNumber(row.quantity), filterCell: rangeFilter("quantity") },
    {
      key: "unitCost",
      header: t("warehouse.valuation.column.unitCost"),
      cell: (row) => (row.average_unit_cost !== null ? `${formatMoney(row.average_unit_cost)} F CFA` : "—"),
      filterCell: rangeFilter("unitCost"),
    },
    { key: "value", header: t("warehouse.valuation.column.value"), cell: (row) => `${formatMoney(row.value)} F CFA`, filterCell: rangeFilter("value") },
    {
      key: "unvalued",
      header: t("warehouse.valuation.column.unvalued"),
      cell: (row) => (row.unvalued_quantity > 0 ? <Badge variant="warning">{formatNumber(row.unvalued_quantity)}</Badge> : "—"),
      filterCell: rangeFilter("unvalued"),
    },
    {
      key: "actions",
      header: "",
      alwaysVisible: true,
      cell: (row) => (
        <Button variant="ghost" size="sm" onClick={() => setOpenProductId(row.product_id)}>
          <Layers className="h-3.5 w-3.5" />
          {t("warehouse.valuation.action.layers")}
        </Button>
      ),
      filterCell: { type: "blank" },
    },
  ];

  const { visibleColumns, colWidths, isVisible, toggleVisible, getWidth, setWidth, resetAll } = useTableColumns(
    "warehouse.valuation",
    columns,
  );
  const byCoverage =
    coverageFilter === "all"
      ? valuations
      : valuations.filter((v) => (coverageFilter === "unvalued" ? v.unvalued_quantity > 0 : v.unvalued_quantity === 0));
  const rows = columnFilters.apply(byCoverage);
  const totalValue = valuations.reduce((sum, v) => sum + v.value, 0);
  const unvaluedProducts = valuations.filter((v) => v.unvalued_quantity > 0).length;

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2">
        <StatCard label={t("warehouse.valuation.stat.total")} value={Math.round(totalValue)} icon={<Coins className="h-5 w-5" />} unit="F CFA" accent="primary" />
        <StatCard label={t("warehouse.valuation.stat.unvaluedProducts")} value={unvaluedProducts} icon={<Layers className="h-5 w-5" />} accent="warning" />
      </div>
      <p className="text-sm text-muted-foreground">{t("warehouse.valuation.description")}</p>
      <div className="flex flex-wrap items-center gap-2">
        <FilterTabs
          value={coverageFilter}
          onChange={setCoverageFilter}
          options={COVERAGE_FILTERS.map((v) => ({ value: v, label: v === "all" ? t("common.all") : t(`warehouse.valuation.filter.${v}`) }))}
        />
        {columnFilters.isActive && (
          <Button variant="ghost" size="sm" onClick={columnFilters.reset}>
            {t("common.clearFilters")}
          </Button>
        )}
        <ColumnVisibilityMenu columns={columns} isVisible={isVisible} onToggle={toggleVisible} onReset={resetAll} />
      </div>

      {rows.length === 0 ? (
        <EmptyState icon={<Coins className="h-5 w-5" />} title={t("warehouse.valuation.empty.title")} description={t("warehouse.valuation.empty.description")} />
      ) : (
        <Table colWidths={colWidths}>
          <TableHeader>
            <TableRow>
              {visibleColumns.map((column) => (
                <ResizableTableHead key={column.key} width={getWidth(column.key)} onResize={(width) => setWidth(column.key, width)}>
                  {column.header}
                </ResizableTableHead>
              ))}
            </TableRow>
            <ColumnFilterRow cells={visibleColumns.map((column) => column.filterCell ?? { type: "blank" })} />
          </TableHeader>
          <TableBody>
            {rows.map((row) => (
              <TableRow key={row.product_id}>
                {visibleColumns.map((column) => (
                  <TableCell key={column.key}>{column.cell(row)}</TableCell>
                ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}

      <LayersDialog productId={openProductId} productName={openProductId ? productName(openProductId) : ""} onClose={() => setOpenProductId(null)} />
    </div>
  );
}
