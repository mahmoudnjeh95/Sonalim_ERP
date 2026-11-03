import { useQuery } from "@tanstack/react-query";
import { Download } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../../lib/auth";
import { ApiError } from "../../lib/api";
import { currentLocale, useI18n } from "../../lib/i18n";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../../components/ui/table";
import { downloadValuedStock, getValuedStock } from "./stockDocumentsApi";

const num = (value: string | null, digits = 0) =>
  value === null ? "—" : new Intl.NumberFormat(currentLocale(), { maximumFractionDigits: digits }).format(Number(value));

export function ValuedStockTab() {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const { data } = useQuery({ queryKey: ["warehouse", "valuation"], queryFn: () => getValuedStock(token) });

  async function download(format: "csv" | "xlsx") {
    try {
      const blob = await downloadValuedStock(token, format);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `valued-stock.${format}`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : t("valuation.exportError"));
    }
  }

  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>{t("valuation.title")}</CardTitle>
          <p className="mt-0.5 text-sm text-muted-foreground">
            {t("valuation.total")}: <span className="font-medium tabular-nums">{num(data?.total_value ?? "0")} F CFA</span>
            {data && data.missing_cost_count > 0 && ` · ${data.missing_cost_count} ${t("valuation.missingCost")}`}
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={() => download("csv")}>
            <Download className="h-3.5 w-3.5" /> CSV
          </Button>
          <Button variant="outline" size="sm" onClick={() => download("xlsx")}>
            <Download className="h-3.5 w-3.5" /> Excel
          </Button>
        </div>
      </CardHeader>
      <CardContent className="p-0">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t("inventory.column.product")}</TableHead>
              <TableHead className="text-right">{t("valuation.quantity")}</TableHead>
              <TableHead className="text-right">{t("valuation.avgCost")}</TableHead>
              <TableHead className="text-right">{t("valuation.value")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {(data?.items ?? []).map((item) => (
              <TableRow key={item.product_id}>
                <TableCell>
                  <span className="font-medium">{item.name}</span>
                  <span className="block text-xs text-muted-foreground">{item.sku}</span>
                </TableCell>
                <TableCell className={`text-right tabular-nums ${item.negative ? "text-destructive" : ""}`}>{num(item.quantity, 2)}</TableCell>
                <TableCell className="text-right tabular-nums">
                  {item.missing_cost ? <Badge variant="warning">{t("valuation.noCost")}</Badge> : num(item.avg_cost, 2)}
                  {item.cost_source === "catalog" && <span className="ml-1 text-xs text-muted-foreground">({t("valuation.catalog")})</span>}
                </TableCell>
                <TableCell className="text-right tabular-nums">{num(item.value)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}
