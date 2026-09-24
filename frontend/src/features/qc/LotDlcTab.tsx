import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import { CalendarClock, ExternalLink } from "lucide-react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { useAuth } from "../../lib/auth";
import { ApiError } from "../../lib/api";
import { useI18n } from "../../lib/i18n";
import { useColumnFilters, type FilterField } from "../../lib/useColumnFilters";
import { useTableColumns, type ColumnDef } from "../../lib/useTableColumns";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { Table, TableBody, TableCell, TableHeader, TableRow, ResizableTableHead } from "../../components/ui/table";
import { EmptyState } from "../../components/patterns/EmptyState";
import { FilterTabs } from "../../components/patterns/FilterTabs";
import { ColumnFilterRow } from "../../components/patterns/ColumnFilterRow";
import { ColumnVisibilityMenu } from "../../components/patterns/ColumnVisibilityMenu";
import { listProducts } from "../production/api";
import {
  FINISHED_GOODS_LOT_SOURCE,
  LOTS_QUERY_KEY,
  SET_LOT_EXPIRY_PERMISSION,
  listLots,
  setLotExpiry,
  type Lot,
} from "../warehouse/api";
import { TableLoadingRow } from "../../components/patterns/AppLoader";

const PRODUCTS_QUERY_KEY = ["core", "products"] as const;

type DlcFilter = "awaiting" | "entered" | "all";

/**
 * The DLC of one lot: a date box and Save while the person may set it, the date alone
 * otherwise. A subcomponent because each row keeps its own draft date and mutation.
 *
 * The date cannot be picked before the day the lot was made -- the same rule the
 * backend enforces, offered here so a wrong date is not selectable in the first place.
 */
function DlcCell({ lot, canEdit }: { lot: Lot; canEdit: boolean }) {
  const { session } = useAuth();
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const [value, setValue] = useState(lot.expiry_date ?? "");
  useEffect(() => setValue(lot.expiry_date ?? ""), [lot.expiry_date]);

  const save = useMutation({
    mutationFn: () => setLotExpiry(session!.token, lot.id, value),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: LOTS_QUERY_KEY });
      toast.success(t("qc.lotDlc.saved"));
    },
    onError: (error) => {
      toast.error(t("qc.lotDlc.saveError"), { description: error instanceof ApiError ? error.message : undefined });
    },
  });

  if (!canEdit) return <span>{lot.expiry_date ?? "—"}</span>;
  return (
    <div className="flex items-center gap-2">
      <Input
        type="date"
        aria-label={`${t("qc.lotDlc.column.dlc")} ${lot.lot_number}`}
        value={value}
        min={lot.produced_at?.slice(0, 10)}
        onChange={(event) => setValue(event.target.value)}
        className="h-8 w-40"
      />
      <Button
        size="sm"
        disabled={!value || value === (lot.expiry_date ?? "") || save.isPending}
        onClick={() => save.mutate()}
      >
        {save.isPending ? t("common.saving") : t("common.save")}
      </Button>
    </div>
  );
}

/**
 * The finished-goods lots production has registered, and the DLC quality enters on them.
 *
 * Production files a lot with its number only. Until quality has entered the date the
 * lot is "awaiting DLC" -- the list this opens on -- and it leaves that list the moment it
 * has one. A date already entered can be corrected here too; the change is audited with
 * what it was.
 */
export function LotDlcTab() {
  const { session, hasPermission } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const canEdit = hasPermission(SET_LOT_EXPIRY_PERMISSION);
  const [filter, setFilter] = useState<DlcFilter>("awaiting");

  const { data: lots = [], isLoading } = useQuery({
    queryKey: [...LOTS_QUERY_KEY, FINISHED_GOODS_LOT_SOURCE],
    queryFn: () => listLots(token, { sourceType: FINISHED_GOODS_LOT_SOURCE }),
  });
  const { data: products = [] } = useQuery({ queryKey: PRODUCTS_QUERY_KEY, queryFn: () => listProducts(token) });
  const productName = (id: string) => products.find((p) => p.id === id)?.name ?? "—";

  const awaiting = lots.filter((lot) => lot.expiry_date === null).length;
  const byState = lots.filter((lot) =>
    filter === "all" ? true : filter === "awaiting" ? lot.expiry_date === null : lot.expiry_date !== null,
  );

  const filterFields: FilterField<Lot>[] = [
    { key: "lot", kind: "text", getValue: (lot) => lot.lot_number },
    { key: "product", kind: "text", getValue: (lot) => productName(lot.product_id) },
  ];
  const columnFilters = useColumnFilters(filterFields);
  const visible = columnFilters.apply(byState);

  const columns: ColumnDef<Lot>[] = [
    {
      key: "lot",
      header: t("qc.lotDlc.column.lot"),
      defaultWidth: 160,
      cell: (lot) => <span className="font-medium">{lot.lot_number}</span>,
      filterCell: {
        type: "text",
        value: columnFilters.text.lot ?? "",
        onChange: (v) => columnFilters.setTextValue("lot", v),
        placeholder: t("qc.lotDlc.column.lot"),
      },
      sortValue: (lot) => lot.lot_number,
    },
    {
      key: "product",
      header: t("qc.lotDlc.column.product"),
      defaultWidth: 240,
      cell: (lot) => productName(lot.product_id),
      filterCell: {
        type: "text",
        value: columnFilters.text.product ?? "",
        onChange: (v) => columnFilters.setTextValue("product", v),
        placeholder: t("qc.lotDlc.column.product"),
      },
      sortValue: (lot) => productName(lot.product_id),
    },
    {
      key: "produced",
      header: t("qc.lotDlc.column.produced"),
      defaultWidth: 130,
      cell: (lot) => lot.produced_at?.slice(0, 10) ?? "—",
      sortValue: (lot) => lot.produced_at ?? "",
    },
    {
      key: "dlc",
      header: t("qc.lotDlc.column.dlc"),
      defaultWidth: 320,
      alwaysVisible: true,
      cell: (lot) => <DlcCell lot={lot} canEdit={canEdit} />,
      sortValue: (lot) => lot.expiry_date ?? "",
    },
    {
      key: "report",
      header: t("qc.lotDlc.column.report"),
      defaultWidth: 110,
      headerClassName: "text-right",
      cellClassName: "text-right",
      cell: (lot) =>
        lot.source_id ? (
          <Link
            to={`/production?tab=conditionnement&report=${lot.source_id}`}
            aria-label={t("qc.lotDlc.openReport")}
            className="inline-flex items-center gap-1 text-sm text-primary hover:underline"
          >
            <ExternalLink className="h-3.5 w-3.5" />
            {t("qc.lotDlc.openReport")}
          </Link>
        ) : null,
    },
  ];
  const { visibleColumns, colWidths, isVisible, toggleVisible, getWidth, setWidth, resetAll, sortDirectionFor, toggleSort, sortRows } =
    useTableColumns("qc.lotDlc", columns);
  const rows = sortRows(visible);

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-center gap-3">
          <div>
            <CardTitle className="flex items-center gap-1.5">
              <CalendarClock className="h-4 w-4" />
              {t("qc.lotDlc.title")}
            </CardTitle>
            <p className="mt-0.5 text-sm text-muted-foreground">{t("qc.lotDlc.description")}</p>
          </div>
          <FilterTabs<DlcFilter>
            value={filter}
            onChange={setFilter}
            options={[
              { value: "awaiting", label: `${t("qc.lotDlc.filter.awaiting")} (${awaiting})` },
              { value: "entered", label: t("qc.lotDlc.filter.entered") },
              { value: "all", label: t("common.all") },
            ]}
          />
          {columnFilters.isActive && (
            <Button variant="ghost" size="sm" onClick={columnFilters.reset}>
              {t("common.clearFilters")}
            </Button>
          )}
          <ColumnVisibilityMenu columns={columns} isVisible={isVisible} onToggle={toggleVisible} onReset={resetAll} />
        </div>
        {!canEdit && <p className="text-xs text-muted-foreground">{t("qc.lotDlc.readOnly")}</p>}
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
                    icon={<CalendarClock className="h-5 w-5" />}
                    title={t("qc.lotDlc.empty.title")}
                    description={t("qc.lotDlc.empty.description")}
                  />
                </TableCell>
              </TableRow>
            )}
            <AnimatePresence initial={false}>
              {rows.map((lot) => (
                <motion.tr
                  key={lot.id}
                  layout
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0 }}
                  className="border-b border-border last:border-0 hover:bg-muted/50"
                >
                  {visibleColumns.map((column) => (
                    <TableCell key={column.key} className={column.cellClassName}>
                      {column.cell(lot)}
                    </TableCell>
                  ))}
                </motion.tr>
              ))}
            </AnimatePresence>
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}
