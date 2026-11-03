import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { BellRing, X } from "lucide-react";
import { useAuth } from "../../lib/auth";
import { useI18n } from "../../lib/i18n";
import { listAlerts } from "./instrumentsApi";

/**
 * There is no notification channel in the platform, so due-date alerts are pulled: the layout asks
 * once when it mounts (and again every few minutes) and shows a dismissible strip when a cheque or
 * draft has reached its alert window. Users without treasury.view never call the endpoint.
 */
export function TreasuryAlertBanner() {
  const { session, hasPermission } = useAuth();
  const { t } = useI18n();
  const [dismissed, setDismissed] = useState(false);
  const allowed = !!session && hasPermission("treasury.view");

  const { data: alerts = [] } = useQuery({
    queryKey: ["treasury", "alerts"],
    queryFn: () => listAlerts(session!.token),
    enabled: allowed,
    refetchInterval: 5 * 60 * 1000,
    retry: false,
  });

  if (!allowed || dismissed || alerts.length === 0) return null;
  const received = alerts.filter((a) => a.direction === "in").length;
  const issued = alerts.length - received;

  return (
    <div className="mx-auto mb-4 flex max-w-6xl items-center gap-3 rounded-md border border-warning/40 bg-warning/10 px-4 py-2 text-sm">
      <BellRing className="h-4 w-4 shrink-0" />
      <p className="flex-1">
        {t("treasury.alerts.summary")} {received > 0 && `${received} ${t("treasury.instruments.received").toLowerCase()}`}
        {received > 0 && issued > 0 && " · "}
        {issued > 0 && `${issued} ${t("treasury.instruments.issued").toLowerCase()}`}
      </p>
      <Link to="/treasury" className="font-medium underline">
        {t("treasury.alerts.view")}
      </Link>
      <button type="button" aria-label={t("treasury.alerts.dismiss")} onClick={() => setDismissed(true)}>
        <X className="h-4 w-4" />
      </button>
    </div>
  );
}
