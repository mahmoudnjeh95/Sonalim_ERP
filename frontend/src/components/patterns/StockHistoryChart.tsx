import { Bar, BarChart, CartesianGrid, Tooltip, XAxis, YAxis } from "recharts";
import { InteractiveChart } from "../charts/InteractiveChart";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "../ui/card";
import { useI18n } from "../../lib/i18n";
import { signedMoveQuantity } from "../../lib/stockMoveTypes";
import type { StockMove } from "../../features/warehouse/api";

function dayKey(iso: string): string {
  return iso.slice(0, 10);
}

function dayLabel(key: string, language: string): string {
  return new Date(key).toLocaleDateString(language === "fr" ? "fr-FR" : "en-US", { day: "2-digit", month: "short" });
}

/**
 * Small added-vs-used rollup for a product's stock-move history -- one bar
 * per day, added stacked above zero and used stacked below it, so a glance
 * shows whether a raw material is building up or draining. Buckets whatever
 * `moves` it's given (the caller has already scoped it to one product), so
 * it's just as usable for a regrind output as for any other stock line.
 */
export function StockHistoryChart({ moves, unit }: { moves: StockMove[]; unit?: string | null }) {
  const { t, language } = useI18n();

  const byDay = new Map<string, { added: number; used: number }>();
  for (const move of moves) {
    const key = dayKey(move.created_at);
    const bucket = byDay.get(key) ?? { added: 0, used: 0 };
    const signed = signedMoveQuantity(move);
    if (signed >= 0) bucket.added += signed;
    else bucket.used += signed;
    byDay.set(key, bucket);
  }
  const data = Array.from(byDay.entries())
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([key, bucket]) => ({ period: dayLabel(key, language), ...bucket }));

  if (data.length === 0) return null;

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("warehouse.stockHistory.chart.title")}</CardTitle>
        <CardDescription>{t("warehouse.stockHistory.chart.description")}</CardDescription>
      </CardHeader>
      <CardContent>
        <InteractiveChart height={180}>
          <BarChart data={data}>
            <CartesianGrid strokeDasharray="3 3" stroke="hsl(214 20% 92%)" vertical={false} />
            <XAxis dataKey="period" tick={{ fontSize: 12, fill: "hsl(215 16% 47%)" }} axisLine={false} tickLine={false} />
            <YAxis tick={{ fontSize: 12, fill: "hsl(215 16% 47%)" }} axisLine={false} tickLine={false} />
            <Tooltip
              formatter={(value) => `${Number(value) > 0 ? "+" : ""}${value}${unit ? ` ${unit}` : ""}`}
              contentStyle={{ borderRadius: 10, border: "1px solid hsl(214 20% 88%)", fontSize: 13, fontFamily: "Inter, sans-serif" }}
            />
            <Bar dataKey="added" name={t("warehouse.stockHistory.chart.added")} stackId="stock" fill="hsl(152 69% 31%)" radius={[4, 4, 0, 0]} />
            <Bar dataKey="used" name={t("warehouse.stockHistory.chart.used")} stackId="stock" fill="hsl(0 72% 51%)" radius={[0, 0, 4, 4]} />
          </BarChart>
        </InteractiveChart>
      </CardContent>
    </Card>
  );
}
