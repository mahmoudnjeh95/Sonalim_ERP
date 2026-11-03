import { useQuery } from "@tanstack/react-query";
import { Lock } from "lucide-react";
import { useAuth } from "../../lib/auth";
import { useI18n } from "../../lib/i18n";
import { listLocations } from "./api";
import { listCycleCounts } from "./cycleCounts/api";

/** While a cycle count is in progress the bins in its scope refuse every stock movement, including
 * production postings; this tells the people who would otherwise hit that refusal why. */
export function FrozenLocationsNotice() {
  const { session, hasPermission } = useAuth();
  const { t } = useI18n();
  const allowed = hasPermission("warehouse.view_cycle_counts");
  const { data: counts = [] } = useQuery({
    queryKey: ["warehouse", "cycleCounts", "in_progress"],
    queryFn: () => listCycleCounts(session!.token, { status: "in_progress" }),
    enabled: allowed,
  });
  const { data: locations = [] } = useQuery({
    queryKey: ["warehouse", "locations"],
    queryFn: () => listLocations(session!.token),
    enabled: allowed,
  });

  if (!allowed || counts.length === 0) return null;
  const names = counts
    .map((c) => (c.scope_location_id ? (locations.find((l) => l.id === c.scope_location_id)?.name ?? c.scope_location_id) : t("inventory.wholeSite")))
    .join(", ");

  return (
    <div className="flex items-center gap-3 rounded-md border border-warning/40 bg-warning/10 px-4 py-2 text-sm">
      <Lock className="h-4 w-4 shrink-0" />
      <p>
        {t("inventory.frozenNotice")} <span className="font-medium">{names}</span>
      </p>
    </div>
  );
}
