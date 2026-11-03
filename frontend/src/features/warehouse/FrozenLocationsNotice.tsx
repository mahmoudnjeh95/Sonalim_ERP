import { useQuery } from "@tanstack/react-query";
import { Lock } from "lucide-react";
import { useAuth } from "../../lib/auth";
import { useI18n } from "../../lib/i18n";
import { listLocations } from "./api";
import { listInventories } from "./stockDocumentsApi";

/** While a full inventory is open its location refuses every stock movement, including production
 * postings; this tells the people who would otherwise hit that refusal why. */
export function FrozenLocationsNotice() {
  const { session, hasPermission } = useAuth();
  const { t } = useI18n();
  const allowed = hasPermission("warehouse.view_moves");
  const { data: inventories = [] } = useQuery({
    queryKey: ["warehouse", "inventories"],
    queryFn: () => listInventories(session!.token),
    enabled: allowed,
  });
  const { data: locations = [] } = useQuery({
    queryKey: ["warehouse", "locations"],
    queryFn: () => listLocations(session!.token),
    enabled: allowed,
  });

  const frozen = inventories.filter((i) => i.status === "open" && i.type === "full");
  if (!allowed || frozen.length === 0) return null;
  const names = frozen.map((i) => locations.find((l) => l.id === i.location_id)?.name ?? i.number).join(", ");

  return (
    <div className="flex items-center gap-3 rounded-md border border-warning/40 bg-warning/10 px-4 py-2 text-sm">
      <Lock className="h-4 w-4 shrink-0" />
      <p>
        {t("inventory.frozenNotice")} <span className="font-medium">{names}</span>
      </p>
    </div>
  );
}
