import { PackagePlus, Wrench } from "lucide-react";
import { Button } from "../../../components/ui/button";
import { useI18n } from "../../../lib/i18n";
import { formatQuantity } from "../../../lib/units";
import type { CheckPart } from "../api";

/**
 * The spare parts a check's point needs: how many, and where they are in the
 * spare-parts location (shelf by shelf) or that there are none. `onRequest`
 * opens a parts request already filled in with these parts.
 */
export function CheckPartsList({ parts, onRequest }: { parts: CheckPart[]; onRequest?: () => void }) {
  const { t } = useI18n();
  if (parts.length === 0) return null;
  return (
    <div className="space-y-2 rounded-lg bg-background px-3 py-2 shadow-soft ring-1 ring-border">
      <p className="flex items-center gap-1.5 text-sm font-semibold">
        <Wrench className="h-4 w-4 text-muted-foreground" aria-hidden />
        {t("maintenance.map.point.parts")}
      </p>
      <ul className="space-y-2">
        {parts.map((part) => {
          const short = part.available < part.quantity;
          return (
            <li key={part.product_id} className="text-sm">
              <div className="flex flex-wrap items-baseline justify-between gap-x-3">
                <span className="min-w-0 break-words font-medium">{part.product_name}</span>
                <span className="shrink-0 tabular-nums">× {formatQuantity(part.quantity, part.uom_code)}</span>
              </div>
              {part.available <= 0 ? (
                <p className="text-xs font-medium text-destructive">{t("maintenance.parts.stock.out")}</p>
              ) : (
                <ul className="text-xs text-muted-foreground">
                  {part.locations.map((location) => (
                    <li key={location.location_id}>
                      {location.location_name} : {formatQuantity(location.available, part.uom_code)}
                    </li>
                  ))}
                  {short && <li className="font-medium text-destructive">{t("maintenance.parts.stock.short")}</li>}
                </ul>
              )}
            </li>
          );
        })}
      </ul>
      {onRequest && (
        <Button type="button" variant="outline" size="sm" className="min-h-10" onClick={onRequest}>
          <PackagePlus className="h-3.5 w-3.5" />
          {t("maintenance.parts.requestFromPoint")}
        </Button>
      )}
    </div>
  );
}
