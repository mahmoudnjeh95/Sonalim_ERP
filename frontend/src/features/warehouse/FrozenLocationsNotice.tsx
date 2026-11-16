import { useQuery } from "@tanstack/react-query";
import { Lock } from "lucide-react";
import { useAuth } from "../../lib/auth";
import { useI18n } from "../../lib/i18n";
import { CYCLE_COUNTS_QUERY_KEY, listFrozenLocations } from "./cycleCounts/api";

/** While a cycle count is in progress the locations in its scope refuse every stock movement, including
 * production postings; this tells the people who would otherwise hit that refusal why. */
export function FrozenLocationsNotice() {
  const { session, hasPermission } = useAuth();
  const { t } = useI18n();
  const allowed = hasPermission("warehouse.view_moves");
  const { data: frozen = [] } = useQuery({
    queryKey: [...CYCLE_COUNTS_QUERY_KEY, "frozen"],
    queryFn: () => listFrozenLocations(session!.token),
    enabled: allowed,
  });

  if (!allowed || frozen.length === 0) return null;

  return (
    <div className="flex items-center gap-3 rounded-md border border-warning/40 bg-warning/10 px-4 py-2 text-sm">
      <Lock className="h-4 w-4 shrink-0" />
      <p>
        {t("inventory.frozenNotice")} <span className="font-medium">{frozen.map((f) => `${f.name} (${f.number})`).join(", ")}</span>
      </p>
    </div>
  );
}
