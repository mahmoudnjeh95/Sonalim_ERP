import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { PackageCheck } from "lucide-react";
import { toast } from "sonner";
import { ApiError } from "../../../lib/api";
import { useAuth } from "../../../lib/auth";
import { useI18n } from "../../../lib/i18n";
import { formatQuantity } from "../../../lib/units";
import { Button } from "../../../components/ui/button";
import { Checkbox } from "../../../components/ui/checkbox";
import { Input } from "../../../components/ui/input";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from "../../../components/ui/dialog";
import { RELEASE_STOCK_PERMISSION, getStockRelease, releaseStock, type ReleaseItem } from "./api";
import { AppLoader } from "../../../components/patterns/AppLoader";

const RELEASE_QUERY_KEY = ["production", "stock-release"] as const;
const EPSILON = 1e-6;

/** What is typed is a count of cartons or sacs, shown to three decimals at most. */
const shown = (value: number) => String(Math.round(value * 1000) / 1000);

/** Only what the line store can give, and only to a product that has somewhere to go, can be ticked. */
const canRelease = (item: ReleaseItem) => item.releasable > 0 && item.destination !== null;

/** Pieces in one counted unit: a carton's worth of packets, or 1 for a sac and anything counted one by one. */
const factorOf = (item: ReleaseItem) => item.packets_per_carton ?? 1;

/**
 * Moves the goods packed on one day from the line store, next to the production, to each
 * product's own store. The list comes from that day's packing reports: one row per finished
 * product, counted in cartons (or sacs) as the floor counts them. It opens on yesterday, or on
 * today once nothing from yesterday is left, and the day can be changed. Every releasable
 * product starts ticked; a supervisor unticks what is still waiting (for quality, for example)
 * or lowers a quantity. Nothing moves until the release is confirmed, and one line that cannot
 * move stops the whole release.
 */
export function ReleaseStockDialog({ unitOf }: { unitOf: (uomId: string) => string }) {
  const { session, hasPermission } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  // null lets the server choose the day to open on.
  const [day, setDay] = useState<string | null>(null);
  const [picked, setPicked] = useState<Record<string, { on: boolean; quantity: string }>>({});

  const list = useQuery({ queryKey: [...RELEASE_QUERY_KEY, day], queryFn: () => getStockRelease(token, day), enabled: open });

  // The count a row is read in: cartons when the product has a carton tier, sacs for a sac, else its own unit.
  const unitLabel = (item: ReleaseItem) =>
    item.packets_per_carton
      ? t("production.board.release.unit.carton")
      : item.packaging_format === "sac"
        ? t("production.board.release.unit.sac")
        : unitOf(item.uom_id);

  // What the line store can release when the list arrives is what is offered, in full.
  useEffect(() => {
    if (!list.data) return;
    setPicked(
      Object.fromEntries(
        list.data.items.map((item) => [item.product_id, { on: canRelease(item), quantity: shown(item.releasable / factorOf(item)) }]),
      ),
    );
  }, [list.data]);

  const items = list.data?.items ?? [];
  const selectable = items.filter(canRelease);
  const chosen = items.filter((item) => picked[item.product_id]?.on);
  const countOf = (item: ReleaseItem) => Number(picked[item.product_id]?.quantity.replace(",", "."));
  const invalid = chosen.filter((item) => !(countOf(item) > 0) || countOf(item) > item.releasable / factorOf(item) + EPSILON);
  const allOn = selectable.length > 0 && selectable.every((item) => picked[item.product_id]?.on);

  // Ticked and left as offered means the whole releasable amount, so it is sent exactly and not as a rounded count.
  const piecesOf = (item: ReleaseItem) =>
    Math.abs(countOf(item) - Number(shown(item.releasable / factorOf(item)))) < EPSILON ? item.releasable : countOf(item) * factorOf(item);

  const release = useMutation({
    mutationFn: () => releaseStock(token, list.data!.day, chosen.map((item) => ({ product_id: item.product_id, quantity: piecesOf(item) }))),
    onSuccess: () => {
      toast.success(t("production.board.release.done"));
      void queryClient.invalidateQueries({ queryKey: ["warehouse", "stock"] });
      void queryClient.invalidateQueries({ queryKey: RELEASE_QUERY_KEY });
      setOpen(false);
      setDay(null); // the next opening looks at the day that has something left again
    },
    onError: (error) => {
      toast.error(t("production.board.release.failed"), { description: error instanceof ApiError ? error.message : undefined });
    },
  });

  if (!hasPermission(RELEASE_STOCK_PERMISSION)) return null;

  const setPick = (productId: string, change: Partial<{ on: boolean; quantity: string }>) =>
    setPicked((current) => ({ ...current, [productId]: { ...current[productId], ...change } }));

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (next) {
          setDay(null);
          // What was packed and what waits in the line store change as shifts are validated, so it is read afresh every time.
          void queryClient.invalidateQueries({ queryKey: RELEASE_QUERY_KEY });
        }
      }}
    >
      <DialogTrigger asChild>
        <Button size="sm" variant="outline" className="gap-1.5">
          <PackageCheck className="h-4 w-4" aria-hidden="true" />
          {t("production.board.release.button")}
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-4xl">
        <DialogHeader>
          <DialogTitle>{t("production.board.release.title")}</DialogTitle>
          <DialogDescription>
            {list.data?.line_store?.name ? `${list.data.line_store.name} · ` : ""}
            {t("production.board.release.desc")}
          </DialogDescription>
        </DialogHeader>

        <label className="flex items-center gap-2 text-sm">
          <span className="text-muted-foreground">{t("production.board.release.day")}</span>
          <Input
            type="date"
            className="h-8 w-40"
            max={list.data?.today}
            value={day ?? list.data?.day ?? ""}
            onChange={(event) => event.target.value && setDay(event.target.value)}
          />
        </label>

        {list.isLoading ? (
          <AppLoader size={96} className="py-4" />
        ) : list.isError ? (
          <p className="text-sm text-destructive">{list.error instanceof ApiError ? list.error.message : t("production.board.release.failed")}</p>
        ) : !list.data?.line_store ? (
          <p className="text-sm text-muted-foreground">{t("production.board.release.noLineStore")}</p>
        ) : items.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t("production.board.release.empty")}</p>
        ) : (
          <div className="max-h-[50vh] overflow-y-auto rounded-md border border-border">
            <table className="w-full text-sm">
              <thead className="bg-muted/60 text-left text-xs text-muted-foreground">
                <tr>
                  <th className="w-10 px-3 py-2">
                    <Checkbox
                      checked={allOn}
                      disabled={selectable.length === 0}
                      aria-label={t("production.board.release.selectAll")}
                      onCheckedChange={(on) =>
                        setPicked((current) => ({
                          ...current,
                          ...Object.fromEntries(selectable.map((item) => [item.product_id, { ...current[item.product_id], on: on === true }])),
                        }))
                      }
                    />
                  </th>
                  <th className="px-2 py-2">{t("production.board.release.col.product")}</th>
                  <th className="px-2 py-2 text-right">{t("production.board.release.col.packed")}</th>
                  <th className="px-2 py-2 text-right">{t("production.board.release.col.released")}</th>
                  <th className="w-44 px-2 py-2">{t("production.board.release.col.quantity")}</th>
                  <th className="px-2 py-2">{t("production.board.release.col.destination")}</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => {
                  const state = picked[item.product_id];
                  const factor = factorOf(item);
                  const unit = unitLabel(item);
                  const bad = state?.on && invalid.includes(item);
                  return (
                    <tr key={item.product_id} className="border-t border-border/70">
                      <td className="px-3 py-2">
                        <Checkbox
                          checked={state?.on ?? false}
                          disabled={!canRelease(item)}
                          aria-label={item.product_name}
                          onCheckedChange={(on) => setPick(item.product_id, { on: on === true })}
                        />
                      </td>
                      <td className="px-2 py-2 font-medium">{item.product_name}</td>
                      <td className="px-2 py-2 text-right tabular-nums">
                        {formatQuantity(item.packed / factor, unit)}
                        {factor !== 1 ? <span className="block text-xs text-muted-foreground">{formatQuantity(item.packed, unitOf(item.uom_id))}</span> : null}
                      </td>
                      <td className="px-2 py-2 text-right tabular-nums text-muted-foreground">
                        {item.released > 0 ? formatQuantity(item.released / factor, unit) : "—"}
                      </td>
                      <td className="px-2 py-2">
                        {canRelease(item) ? (
                          <div className="flex items-center gap-2">
                            <Input
                              inputMode="decimal"
                              className={`h-8 w-24 text-right tabular-nums ${bad ? "border-destructive" : ""}`}
                              value={state?.quantity ?? ""}
                              disabled={!state?.on}
                              aria-label={`${item.product_name} ${t("production.board.release.col.quantity")}`}
                              onChange={(event) => setPick(item.product_id, { quantity: event.target.value })}
                            />
                            <span className="text-xs text-muted-foreground">/ {formatQuantity(item.releasable / factor, unit)}</span>
                          </div>
                        ) : (
                          <span className="text-xs text-muted-foreground">
                            {item.remaining <= 0 ? t("production.board.release.alreadyReleased") : item.destination === null ? "" : t("production.board.release.notInLineStore")}
                          </span>
                        )}
                      </td>
                      <td className="px-2 py-2">
                        {item.destination ? (
                          item.destination.name
                        ) : (
                          <span className="text-destructive">{t("production.board.release.noDestination")}</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={() => setOpen(false)}>
            {t("production.board.release.cancel")}
          </Button>
          <Button onClick={() => release.mutate()} disabled={chosen.length === 0 || invalid.length > 0 || release.isPending}>
            {t("production.board.release.confirm")}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
