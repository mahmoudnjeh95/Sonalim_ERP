import { useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Download, History, Info } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../../lib/auth";
import { ApiError } from "../../lib/api";
import { useI18n } from "../../lib/i18n";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Select } from "../../components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../../components/ui/table";
import { EmptyState } from "../../components/patterns/EmptyState";
import { TableLoadingRow } from "../../components/patterns/AppLoader";
import { listLocations } from "./api";
import { downloadMovementsReport, getMovementsReport, saveBlob, type MovementRow, type MovementsFilter } from "./stockDocumentsApi";

type Key = Parameters<ReturnType<typeof useI18n>["t"]>[0];

const TYPE_FILTERS = [
  "receipt",
  "issue",
  "return",
  "delivery",
  "adjustment",
  "transfer_in",
  "transfer_out",
  "sales_invoice",
  "sales_credit_note",
  "purchase_invoice",
  "purchase_credit_note",
];

/** What a line of the report is, in the manual's words: the document first, the raw move type otherwise. */
function kindOf(row: MovementRow) {
  return row.voucher_type ?? row.move_type;
}

export function MovementsReportTab() {
  const { t } = useI18n();
  const { session } = useAuth();
  const token = session!.token;
  const [filter, setFilter] = useState<MovementsFilter>({});
  const { data: rows = [], isLoading } = useQuery({
    queryKey: ["warehouse", "reports", "movements", filter],
    queryFn: () => getMovementsReport(token, filter),
  });
  const { data: locations = [] } = useQuery({ queryKey: ["warehouse", "locations"], queryFn: () => listLocations(token) });

  const groups = useMemo(() => {
    const byProduct = new Map<string, MovementRow[]>();
    rows.forEach((row) => byProduct.set(row.sku, [...(byProduct.get(row.sku) ?? []), row]));
    return [...byProduct.entries()].sort(([a], [b]) => a.localeCompare(b));
  }, [rows]);

  const exportMutation = useMutation({
    mutationFn: (format: "csv" | "xlsx") => downloadMovementsReport(token, filter, format).then((blob) => saveBlob(blob, `stock-movements.${format}`)),
    onError: (error) => toast.error(t("movements.exportError"), { description: error instanceof ApiError ? error.message : undefined }),
  });
  const label = (row: MovementRow) => {
    const kind = kindOf(row);
    const key = `movements.kind.${kind}` as Key;
    const translated = t(key);
    return translated === key ? kind : translated;
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-3">
        <div className="space-y-1.5">
          <Label htmlFor="mv_type">{t("movements.type")}</Label>
          <Select id="mv_type" value={filter.move_type ?? ""} onChange={(e) => setFilter((f) => ({ ...f, move_type: e.target.value || undefined }))}>
            <option value="">{t("common.all")}</option>
            {TYPE_FILTERS.map((type) => (
              <option key={type} value={type}>{t(`movements.kind.${type}` as Key)}</option>
            ))}
          </Select>
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="mv_location">{t("movements.location")}</Label>
          <Select id="mv_location" value={filter.location_id ?? ""} onChange={(e) => setFilter((f) => ({ ...f, location_id: e.target.value || undefined }))}>
            <option value="">{t("common.all")}</option>
            {locations.map((location) => (
              <option key={location.id} value={location.id}>{location.name}</option>
            ))}
          </Select>
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="mv_from">{t("movements.from")}</Label>
          <Input id="mv_from" type="date" value={filter.date_from ?? ""} onChange={(e) => setFilter((f) => ({ ...f, date_from: e.target.value || undefined }))} />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="mv_to">{t("movements.to")}</Label>
          <Input id="mv_to" type="date" value={filter.date_to ?? ""} onChange={(e) => setFilter((f) => ({ ...f, date_to: e.target.value || undefined }))} />
        </div>
        <Button variant="outline" size="sm" disabled={exportMutation.isPending} onClick={() => exportMutation.mutate("xlsx")}>
          <Download className="h-3.5 w-3.5" />
          Excel
        </Button>
        <Button variant="outline" size="sm" disabled={exportMutation.isPending} onClick={() => exportMutation.mutate("csv")}>
          <Download className="h-3.5 w-3.5" />
          CSV
        </Button>
      </div>

      <p className="flex items-start gap-2 text-sm text-muted-foreground">
        <Info className="mt-0.5 h-4 w-4 shrink-0" />
        {t("movements.informationalNote")}
      </p>

      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>{t("movements.product")}</TableHead>
            <TableHead>{t("movements.type")}</TableHead>
            <TableHead>{t("movements.document")}</TableHead>
            <TableHead>{t("movements.location")}</TableHead>
            <TableHead>{t("movements.partner")}</TableHead>
            <TableHead className="text-right">{t("movements.quantity")}</TableHead>
            <TableHead>{t("movements.date")}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {isLoading && <TableLoadingRow colSpan={7} />}
          {!isLoading && rows.length === 0 && (
            <TableRow>
              <TableCell colSpan={7} className="p-0">
                <EmptyState icon={<History className="h-5 w-5" />} title={t("movements.empty.title")} description={t("movements.empty.description")} />
              </TableCell>
            </TableRow>
          )}
          {groups.map(([sku, group]) => [
            <TableRow key={sku} className="bg-muted/50">
              <TableCell colSpan={7} className="font-medium">{sku} · {group[0].product}</TableCell>
            </TableRow>,
            ...group.map((row, index) => (
              <TableRow key={`${sku}-${index}`} className={row.informational ? "text-muted-foreground" : undefined}>
                <TableCell className="text-muted-foreground">{row.product}</TableCell>
                <TableCell>
                  <span className="flex flex-wrap items-center gap-2">
                    {label(row)}
                    {row.informational && <Badge>{t("movements.informational")}</Badge>}
                  </span>
                </TableCell>
                <TableCell className="font-mono text-xs">{row.voucher_number ?? row.reference ?? "—"}</TableCell>
                <TableCell>{row.location ?? "—"}</TableCell>
                <TableCell>{row.partner ?? "—"}</TableCell>
                <TableCell className={`text-right tabular-nums${row.informational ? " italic" : ""}`}>{Number(row.quantity)}</TableCell>
                <TableCell>{new Date(row.created_at).toLocaleDateString()}</TableCell>
              </TableRow>
            )),
          ])}
        </TableBody>
      </Table>
    </div>
  );
}
