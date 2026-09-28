import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Pencil, Plus, Trash2 } from "lucide-react";
import { useAuth } from "../../../lib/auth";
import { useI18n } from "../../../lib/i18n";
import { ApiError } from "../../../lib/api";
import { useColumnFilters } from "../../../lib/useColumnFilters";
import { useTableColumns, type ColumnDef } from "../../../lib/useTableColumns";
import { Button } from "../../../components/ui/button";
import { Input } from "../../../components/ui/input";
import { Label } from "../../../components/ui/label";
import { Select } from "../../../components/ui/select";
import { Badge } from "../../../components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "../../../components/ui/card";
import { Table, TableHeader, TableBody, TableRow, TableCell, ResizableTableHead } from "../../../components/ui/table";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "../../../components/ui/dialog";
import { FilterTabs } from "../../../components/patterns/FilterTabs";
import { ColumnFilterRow } from "../../../components/patterns/ColumnFilterRow";
import { ColumnVisibilityMenu } from "../../../components/patterns/ColumnVisibilityMenu";
import { ProductSelect } from "../../../components/patterns/ProductSelect";
import { useProductCatalog } from "../../products/catalog";
import {
  createBarcode,
  deleteBarcode,
  listBarcodes,
  updateBarcode,
  BARCODES_QUERY_KEY,
  type BarcodeType,
  type ProductBarcode,
} from "./barcodesApi";

function BarcodeDialog({
  open,
  onOpenChange,
  editing,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  editing: ProductBarcode | null;
}) {
  const { t } = useI18n();
  const { session } = useAuth();
  const token = session!.token;
  const queryClient = useQueryClient();
  const { products } = useProductCatalog();

  const [productId, setProductId] = useState("");
  const [barcode, setBarcode] = useState("");
  const [barcodeType, setBarcodeType] = useState<BarcodeType>("gtin");
  const [unitsPerScan, setUnitsPerScan] = useState("1");
  const [label, setLabel] = useState("");

  useEffect(() => {
    if (!open) return;
    setProductId(editing?.product_id ?? "");
    setBarcode(editing?.barcode ?? "");
    setBarcodeType(editing?.barcode_type ?? "gtin");
    setUnitsPerScan(String(editing?.units_per_scan ?? 1));
    setLabel(editing?.label ?? "");
  }, [open, editing]);

  const mutation = useMutation({
    mutationFn: () => {
      const input = { barcode, barcode_type: barcodeType, units_per_scan: Number(unitsPerScan), label: label || null };
      return editing ? updateBarcode(token, editing.id, input) : createBarcode(token, { ...input, product_id: productId });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: BARCODES_QUERY_KEY });
      onOpenChange(false);
    },
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{editing ? t("warehouse.barcodes.dialog.editTitle") : t("warehouse.barcodes.dialog.title")}</DialogTitle>
          <DialogDescription>{t("warehouse.barcodes.dialog.description")}</DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <div className="space-y-1">
            <Label>{t("warehouse.barcodes.column.product")}</Label>
            <ProductSelect products={products} value={productId} onChange={(e) => setProductId(e.target.value)} disabled={editing !== null} />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <Label>{t("warehouse.barcodes.column.type")}</Label>
              <Select value={barcodeType} onChange={(e) => setBarcodeType(e.target.value as BarcodeType)}>
                <option value="gtin">{t("warehouse.barcodes.type.gtin")}</option>
                <option value="internal">{t("warehouse.barcodes.type.internal")}</option>
              </Select>
            </div>
            <div className="space-y-1">
              <Label>{t("warehouse.barcodes.column.unitsPerScan")}</Label>
              <Input type="number" min={0} step="any" value={unitsPerScan} onChange={(e) => setUnitsPerScan(e.target.value)} />
            </div>
          </div>
          <div className="space-y-1">
            <Label>{t("warehouse.barcodes.column.barcode")}</Label>
            <Input value={barcode} onChange={(e) => setBarcode(e.target.value)} className="font-mono" />
          </div>
          <div className="space-y-1">
            <Label>{t("warehouse.barcodes.column.label")}</Label>
            <Input value={label} onChange={(e) => setLabel(e.target.value)} placeholder={t("warehouse.barcodes.field.labelPlaceholder")} />
          </div>
          {mutation.isError && (
            <p className="text-sm text-destructive">
              {mutation.error instanceof ApiError ? mutation.error.message : t("warehouse.barcodes.dialog.error")}
            </p>
          )}
          <div className="flex justify-end">
            <Button
              onClick={() => mutation.mutate()}
              disabled={mutation.isPending || barcode.trim() === "" || unitsPerScan === "" || (!editing && productId === "")}
            >
              {t("common.save")}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

const TYPE_FILTERS = ["all", "gtin", "internal"] as const;
type TypeFilter = (typeof TYPE_FILTERS)[number];

export function BarcodesPanel() {
  const { t } = useI18n();
  const { session, hasPermission } = useAuth();
  const token = session!.token;
  const queryClient = useQueryClient();
  const { products } = useProductCatalog();
  const { data: barcodes = [] } = useQuery({ queryKey: BARCODES_QUERY_KEY, queryFn: () => listBarcodes(token) });

  const [typeFilter, setTypeFilter] = useState<TypeFilter>("all");
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<ProductBarcode | null>(null);

  const canManage = hasPermission("warehouse.manage_barcodes");
  const canAdmin = hasPermission("warehouse.admin_barcodes");
  const productName = (productId: string) => products.find((p) => p.id === productId)?.name ?? productId;

  const deleteMutation = useMutation({
    mutationFn: (barcodeId: string) => deleteBarcode(token, barcodeId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: BARCODES_QUERY_KEY }),
  });

  const columnFilters = useColumnFilters<ProductBarcode>([
    { key: "product", kind: "text", getValue: (row) => productName(row.product_id) },
    { key: "barcode", kind: "text", getValue: (row) => row.barcode },
    { key: "unitsPerScan", kind: "range", getValue: (row) => row.units_per_scan },
    { key: "label", kind: "text", getValue: (row) => row.label ?? "" },
  ]);
  const textFilter = (key: string, placeholder: string) => ({
    type: "text" as const,
    placeholder,
    value: columnFilters.text[key] ?? "",
    onChange: (v: string) => columnFilters.setTextValue(key, v),
  });

  const columns: ColumnDef<ProductBarcode>[] = [
    {
      key: "product",
      header: t("warehouse.barcodes.column.product"),
      cell: (row) => productName(row.product_id),
      filterCell: textFilter("product", t("warehouse.barcodes.column.product")),
    },
    {
      key: "barcode",
      header: t("warehouse.barcodes.column.barcode"),
      cell: (row) => <span className="font-mono text-xs">{row.barcode}</span>,
      filterCell: textFilter("barcode", t("warehouse.barcodes.column.barcode")),
    },
    {
      key: "type",
      header: t("warehouse.barcodes.column.type"),
      cell: (row) => <Badge variant="outline">{t(`warehouse.barcodes.type.${row.barcode_type}`)}</Badge>,
      filterCell: { type: "blank" },
    },
    {
      key: "unitsPerScan",
      header: t("warehouse.barcodes.column.unitsPerScan"),
      cell: (row) => row.units_per_scan,
      filterCell: {
        type: "range",
        min: columnFilters.range.unitsPerScan?.min ?? "",
        max: columnFilters.range.unitsPerScan?.max ?? "",
        onMinChange: (v) => columnFilters.setRangeValue("unitsPerScan", "min", v),
        onMaxChange: (v) => columnFilters.setRangeValue("unitsPerScan", "max", v),
      },
    },
    {
      key: "label",
      header: t("warehouse.barcodes.column.label"),
      cell: (row) => row.label ?? "—",
      filterCell: textFilter("label", t("warehouse.barcodes.column.label")),
    },
    {
      key: "actions",
      header: "",
      alwaysVisible: true,
      cell: (row) => (
        <div className="flex justify-end gap-1">
          {canAdmin && (
            <Button
              variant="ghost"
              size="sm"
              aria-label={t("common.edit")}
              onClick={() => {
                setEditing(row);
                setDialogOpen(true);
              }}
            >
              <Pencil className="h-3.5 w-3.5" />
            </Button>
          )}
          {canManage && (
            <Button variant="ghost" size="sm" aria-label={t("common.delete")} onClick={() => deleteMutation.mutate(row.id)}>
              <Trash2 className="h-3.5 w-3.5" />
            </Button>
          )}
        </div>
      ),
      filterCell: { type: "blank" },
    },
  ];

  const { visibleColumns, colWidths, isVisible, toggleVisible, getWidth, setWidth, resetAll } = useTableColumns(
    "warehouse.productBarcodes",
    columns,
  );
  const rows = columnFilters.apply(typeFilter === "all" ? barcodes : barcodes.filter((b) => b.barcode_type === typeFilter));

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("warehouse.barcodes.title")}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <p className="text-sm text-muted-foreground">{t("warehouse.barcodes.description")}</p>
        <div className="flex flex-wrap items-center gap-2">
          <FilterTabs
            value={typeFilter}
            onChange={setTypeFilter}
            options={TYPE_FILTERS.map((v) => ({ value: v, label: v === "all" ? t("common.all") : t(`warehouse.barcodes.type.${v}`) }))}
          />
          {columnFilters.isActive && (
            <Button variant="ghost" size="sm" onClick={columnFilters.reset}>
              {t("common.clearFilters")}
            </Button>
          )}
          <ColumnVisibilityMenu columns={columns} isVisible={isVisible} onToggle={toggleVisible} onReset={resetAll} />
          <div className="flex-1" />
          {canManage && (
            <Button
              size="sm"
              onClick={() => {
                setEditing(null);
                setDialogOpen(true);
              }}
            >
              <Plus className="h-3.5 w-3.5" />
              {t("warehouse.barcodes.new")}
            </Button>
          )}
        </div>
        {rows.length === 0 ? (
          <p className="py-6 text-center text-sm text-muted-foreground">{t("warehouse.barcodes.empty")}</p>
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
                <TableRow key={row.id}>
                  {visibleColumns.map((column) => (
                    <TableCell key={column.key}>{column.cell(row)}</TableCell>
                  ))}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
      <BarcodeDialog open={dialogOpen} onOpenChange={setDialogOpen} editing={editing} />
    </Card>
  );
}
