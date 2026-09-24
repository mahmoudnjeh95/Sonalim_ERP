import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Download, PackageSearch } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../../lib/auth";
import { useI18n, type TranslationKey } from "../../lib/i18n";
import { Button } from "../../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { Table, TableHeader, TableBody, TableRow, TableCell, ResizableTableHead } from "../../components/ui/table";
import { EmptyState } from "../../components/patterns/EmptyState";
import { FilterTabs } from "../../components/patterns/FilterTabs";
import { ColumnFilterRow } from "../../components/patterns/ColumnFilterRow";
import { ColumnVisibilityMenu } from "../../components/patterns/ColumnVisibilityMenu";
import { DateRangeFilter } from "../../components/patterns/DateRangeFilter";
import { useColumnFilters, type FilterField } from "../../lib/useColumnFilters";
import { useTableColumns, type ColumnDef } from "../../lib/useTableColumns";
import { formatQuantity } from "../../lib/units";
import {
  exportConsumptionBySupplier,
  listConsumptionBySupplier,
  type ConsumptionCategory,
  type ConsumptionRow,
} from "../production/api";
import { listProducts } from "../warehouse/api";
import { TableLoadingRow } from "../../components/patterns/AppLoader";
import { listPartners } from "../partners/api";

const CONSUMPTION_QUERY_KEY = ["production", "consumption-by-supplier"] as const;

const CATEGORIES: ConsumptionCategory[] = ["film", "carton", "scotch", "ruban", "gasoil", "fuel"];
type CategoryFilter = "all" | ConsumptionCategory;

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

function firstOfMonthIso(): string {
  const date = new Date();
  return new Date(date.getFullYear(), date.getMonth(), 1).toISOString().slice(0, 10);
}

function monthLabel(iso: string): string {
  const [year, month] = iso.split("-");
  return `${year}-${month}`;
}

export function ConsumptionReportTab() {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const [category, setCategory] = useState<CategoryFilter>("all");
  const [customRange, setCustomRange] = useState<{ from: string; to: string } | null>(null);
  const [isExporting, setIsExporting] = useState(false);

  const defaultRange = useMemo(() => ({ from: firstOfMonthIso(), to: todayIso() }), []);
  const range = customRange ?? defaultRange;
  const isDefaultRange = range.from === defaultRange.from && range.to === defaultRange.to;

  const { data: rows = [], isLoading } = useQuery({
    queryKey: [...CONSUMPTION_QUERY_KEY, range.from, range.to, category],
    queryFn: () =>
      listConsumptionBySupplier(token, {
        date_from: range.from,
        date_to: range.to,
        category: category === "all" ? undefined : category,
      }),
  });
  const { data: products = [] } = useQuery({ queryKey: ["core", "products"], queryFn: () => listProducts(token) });
  const { data: suppliers = [] } = useQuery({ queryKey: ["core", "partners"], queryFn: () => listPartners(token) });

  const productName = (id: string | null) => (id && products.find((p) => p.id === id)?.name) || "—";
  const supplierName = (id: string | null) => (id && suppliers.find((s) => s.id === id)?.name) || "—";

  const fields: FilterField<ConsumptionRow>[] = [
    { key: "pc_pl", kind: "text", getValue: (row) => row.pc_pl },
    { key: "product", kind: "text", getValue: (row) => productName(row.product_id) },
    { key: "supplier", kind: "text", getValue: (row) => supplierName(row.supplier_id) },
    { key: "quantity", kind: "range", getValue: (row) => row.quantity },
    { key: "cost", kind: "range", getValue: (row) => row.cost },
  ];
  const columnFilters = useColumnFilters<ConsumptionRow>(fields);
  const filteredRows = columnFilters.apply(rows);

  const columns: ColumnDef<ConsumptionRow>[] = [
    {
      key: "category",
      header: t("analytics.consumptionReport.column.category"),
      defaultWidth: 110,
      cell: (row) => t(`analytics.consumptionReport.category.${row.category}` as TranslationKey),
      sortValue: (row) => row.category,
    },
    {
      key: "month",
      header: t("analytics.consumptionReport.column.month"),
      defaultWidth: 90,
      cell: (row) => monthLabel(row.month),
      sortValue: (row) => row.month,
    },
    {
      key: "pc_pl",
      header: t("analytics.consumptionReport.column.pcPl"),
      defaultWidth: 80,
      cell: (row) => row.pc_pl ?? "—",
      filterCell: {
        type: "text",
        value: columnFilters.text.pc_pl ?? "",
        onChange: (v) => columnFilters.setTextValue("pc_pl", v),
        placeholder: t("analytics.consumptionReport.column.pcPl"),
      },
    },
    {
      key: "product",
      header: t("analytics.consumptionReport.column.product"),
      defaultWidth: 220,
      cell: (row) => productName(row.product_id),
      filterCell: {
        type: "text",
        value: columnFilters.text.product ?? "",
        onChange: (v) => columnFilters.setTextValue("product", v),
        placeholder: t("analytics.consumptionReport.column.product"),
      },
      sortValue: (row) => productName(row.product_id),
    },
    {
      key: "supplier",
      header: t("analytics.consumptionReport.column.supplier"),
      defaultWidth: 200,
      cell: (row) => supplierName(row.supplier_id),
      filterCell: {
        type: "text",
        value: columnFilters.text.supplier ?? "",
        onChange: (v) => columnFilters.setTextValue("supplier", v),
        placeholder: t("analytics.consumptionReport.column.supplier"),
      },
      sortValue: (row) => supplierName(row.supplier_id),
    },
    {
      key: "quantity",
      header: t("analytics.consumptionReport.column.quantity"),
      defaultWidth: 120,
      cell: (row) => <span className="tabular-nums">{formatQuantity(row.quantity)}</span>,
      filterCell: {
        type: "range",
        min: columnFilters.range.quantity?.min ?? "",
        max: columnFilters.range.quantity?.max ?? "",
        onMinChange: (v) => columnFilters.setRangeValue("quantity", "min", v),
        onMaxChange: (v) => columnFilters.setRangeValue("quantity", "max", v),
      },
      sortValue: (row) => row.quantity,
    },
    {
      key: "cost",
      header: t("analytics.consumptionReport.column.cost"),
      defaultWidth: 140,
      cell: (row) =>
        row.priced ? (
          <span className="tabular-nums">{formatQuantity(row.cost)}</span>
        ) : (
          <span className="text-muted-foreground" title={t("analytics.consumptionReport.unpricedHint")}>
            —
          </span>
        ),
      filterCell: {
        type: "range",
        min: columnFilters.range.cost?.min ?? "",
        max: columnFilters.range.cost?.max ?? "",
        onMinChange: (v) => columnFilters.setRangeValue("cost", "min", v),
        onMaxChange: (v) => columnFilters.setRangeValue("cost", "max", v),
      },
      sortValue: (row) => (row.priced ? row.cost : null),
    },
  ];
  const { visibleColumns, colWidths, isVisible, toggleVisible, getWidth, setWidth, resetAll, sortDirectionFor, toggleSort, sortRows } =
    useTableColumns("analytics.consumptionReport", columns);
  const sortedRows = sortRows(filteredRows);

  async function handleExport() {
    setIsExporting(true);
    try {
      const blob = await exportConsumptionBySupplier(token, {
        date_from: range.from,
        date_to: range.to,
        category: category === "all" ? undefined : category,
      });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `consommation-${range.from}-${range.to}.xlsx`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch {
      toast.error(t("analytics.consumptionReport.exportError"));
    } finally {
      setIsExporting(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <CardTitle>{t("analytics.consumptionReport.title")}</CardTitle>
            <p className="mt-0.5 text-sm text-muted-foreground">{t("analytics.consumptionReport.subtitle")}</p>
          </div>
          <Button size="sm" variant="outline" onClick={handleExport} disabled={isExporting || rows.length === 0}>
            <Download className="h-3.5 w-3.5" />
            {isExporting ? t("common.saving") : t("analytics.consumptionReport.export")}
          </Button>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <FilterTabs
            value={category}
            onChange={(value) => setCategory(value as CategoryFilter)}
            options={[
              { value: "all", label: t("common.all") },
              ...CATEGORIES.map((value) => ({
                value,
                label: t(`analytics.consumptionReport.category.${value}` as TranslationKey),
              })),
            ]}
          />
          <DateRangeFilter
            from={range.from}
            to={range.to}
            onChange={setCustomRange}
            onReset={() => setCustomRange(null)}
            isDefault={isDefaultRange}
          />
          {columnFilters.isActive && (
            <Button variant="ghost" size="sm" onClick={columnFilters.reset}>
              {t("common.clearFilters")}
            </Button>
          )}
          <ColumnVisibilityMenu columns={columns} isVisible={isVisible} onToggle={toggleVisible} onReset={resetAll} />
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
            {!isLoading && sortedRows.length === 0 && (
              <TableRow>
                <TableCell colSpan={visibleColumns.length} className="p-0">
                  <EmptyState
                    icon={<PackageSearch className="h-5 w-5" />}
                    title={t("analytics.consumptionReport.empty.title")}
                    description={t("analytics.consumptionReport.empty.description")}
                  />
                </TableCell>
              </TableRow>
            )}
            {sortedRows.map((row, i) => (
              <TableRow key={`${row.category}-${row.month}-${row.product_id}-${row.supplier_id}-${i}`}>
                {visibleColumns.map((column) => (
                  <TableCell key={column.key} className={column.cellClassName}>
                    {column.cell(row)}
                  </TableCell>
                ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}
