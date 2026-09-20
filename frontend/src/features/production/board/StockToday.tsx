import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { useAuth } from "../../../lib/auth";
import { useI18n } from "../../../lib/i18n";
import { formatQuantity } from "../../../lib/units";
import { Button } from "../../../components/ui/button";
import { Skeleton } from "../../../components/ui/skeleton";
import { outlineIcon } from "../../../components/patterns/outlineIcon";
import PalletSvg from "../../../assets/icons/warehouse/pallet.svg?react";
import EmptyNoStock from "../../../assets/illustrations/empty-states/empty-no-stock.svg?react";
import storageImage from "../../../assets/illustrations/production/stage-stockage.webp";
import { listLocations, listProducts, listStock, listUoms } from "../../warehouse/api";
import { DASHBOARD_SETTINGS_QUERY_KEY, getDashboardSettings, type StoreRole } from "./api";
import { BlockError, MissingState } from "./BoardStates";

const PalletIcon = outlineIcon(PalletSvg);

const QUERY_KEYS = {
  stock: ["warehouse", "stock"] as const,
  locations: ["warehouse", "locations"] as const,
  products: ["core", "products"] as const,
  uoms: ["core", "uoms"] as const,
};

/**
 * Finished product waiting in the line store next to what is already in the
 * final store. Which stores are which is configured in Production settings;
 * only sellable products count, so raw material sitting in a store never
 * inflates it. Quantities stay in each product's own unit, per unit.
 */
export function StockToday() {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;

  const settings = useQuery({ queryKey: DASHBOARD_SETTINGS_QUERY_KEY, queryFn: () => getDashboardSettings(token) });
  const stock = useQuery({ queryKey: QUERY_KEYS.stock, queryFn: () => listStock(token) });
  const locations = useQuery({ queryKey: QUERY_KEYS.locations, queryFn: () => listLocations(token) });
  const products = useQuery({ queryKey: QUERY_KEYS.products, queryFn: () => listProducts(token) });
  const uoms = useQuery({ queryKey: QUERY_KEYS.uoms, queryFn: () => listUoms(token) });

  const queries = [settings, stock, locations, products, uoms];
  const failed = queries.find((q) => q.isError);
  const loading = queries.some((q) => q.isLoading);

  const shell = (children: React.ReactNode) => (
    <section className="rounded-xl border border-border bg-white p-4 shadow-soft">
      <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold text-primary">
        <PalletIcon className="h-4 w-4" aria-hidden="true" />
        {t("production.board.stock.title")}
      </h3>
      {children}
    </section>
  );

  if (failed) return shell(<BlockError onRetry={() => queries.forEach((q) => void q.refetch())} />);
  if (loading || !settings.data || !stock.data || !locations.data || !products.data || !uoms.data) return shell(<Skeleton className="h-40 w-full" />);

  const roles = new Map<string, StoreRole>(settings.data.store_roles.map((r) => [r.location_id, r.role]));
  if (roles.size === 0) {
    return shell(
      <MissingState
        illustration={<EmptyNoStock className="h-14 w-14" />}
        title={t("production.board.stock.notSet.title")}
        description={t("production.board.stock.notSet.desc")}
        action={
          <Button asChild variant="outline" size="sm">
            <Link to="/production?tab=settings">{t("production.board.settings.title")}</Link>
          </Button>
        }
      />,
    );
  }

  const productById = new Map(products.data.map((p) => [p.id, p]));
  const uomById = new Map(uoms.data.map((u) => [u.id, u]));

  const totalsFor = (role: StoreRole) => {
    const byUnit = new Map<string, { unit: string; total: number }>();
    for (const item of stock.data) {
      if (roles.get(item.location_id) !== role || item.quantity_on_hand <= 0) continue;
      const product = productById.get(item.product_id);
      if (!product?.is_sellable) continue;
      const uom = uomById.get(product.uom_id);
      const key = uom?.id ?? "?";
      const entry = byUnit.get(key) ?? { unit: uom?.symbol || uom?.code || "", total: 0 };
      entry.total += item.quantity_on_hand;
      byUnit.set(key, entry);
    }
    return [...byUnit.values()];
  };

  const side = (role: StoreRole, label: string, grey: boolean) => {
    const totals = totalsFor(role);
    const names = locations.data.filter((l) => roles.get(l.id) === role).map((l) => l.name).join(", ");
    return (
      <div className="flex-1">
        <img src={storageImage} alt="" className={`h-32 w-full rounded-xl border border-border bg-white object-contain ${grey ? "opacity-70 grayscale" : ""}`} />
        <p className="mt-2 text-xs text-muted-foreground">{label}</p>
        {names ? <p className="truncate text-xs text-muted-foreground/80">{names}</p> : null}
        {totals.length ? (
          <div className="space-y-0.5">
            {totals.map((row) => (
              <p key={row.unit} className="text-2xl font-bold tracking-tight text-primary tabular-nums">
                {formatQuantity(row.total, row.unit)}
              </p>
            ))}
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">{t("production.board.stock.empty")}</p>
        )}
      </div>
    );
  };

  return shell(
    <div className="flex items-start gap-2">
      {side("line", t("production.board.stock.line"), true)}
      <div className="relative mt-16 h-10 min-w-[64px] flex-[0.5]" aria-hidden="true">
        <div className="absolute inset-x-1 top-[18px] h-1.5 rounded-full bg-border" />
        <PalletIcon className="board-carry top-1 h-7 w-7 text-[#E6A52E]" />
      </div>
      {side("final", t("production.board.stock.final"), false)}
    </div>,
  );
}
