import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { BellRing, X } from "lucide-react";
import { useAuth } from "../../lib/auth";
import { useI18n } from "../../lib/i18n";
import { listAlerts } from "./instrumentsApi";
import { listNotifications, markNotificationRead } from "./paymentOrdersApi";

/**
 * There is no notification channel in the platform, so what needs attention is pulled: the layout asks
 * once when it mounts (and again every few minutes) and shows a dismissible strip when a cheque or
 * draft has reached its alert window, or when a colleague sent a payment order. Users without
 * treasury.view never call the endpoints.
 */
export function TreasuryAlertBanner() {
  const { session, hasPermission } = useAuth();
  const { t, language } = useI18n();
  const queryClient = useQueryClient();
  const [dismissed, setDismissed] = useState(false);
  const allowed = !!session && hasPermission("treasury.view");

  const { data: alerts = [] } = useQuery({
    queryKey: ["treasury", "alerts"],
    queryFn: () => listAlerts(session!.token),
    enabled: allowed,
    refetchInterval: 5 * 60 * 1000,
    retry: false,
  });
  const { data: notifications = [] } = useQuery({
    queryKey: ["treasury", "notifications"],
    queryFn: () => listNotifications(session!.token),
    enabled: allowed,
    refetchInterval: 5 * 60 * 1000,
    retry: false,
  });
  const readMutation = useMutation({
    mutationFn: (id: string) => markNotificationRead(session!.token, id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["treasury", "notifications"] }),
  });

  if (!allowed || (alerts.length === 0 && notifications.length === 0)) return null;
  const received = alerts.filter((a) => a.direction === "in").length;
  const issued = alerts.length - received;

  return (
    <div className="mx-auto mb-4 max-w-6xl space-y-2">
      {notifications.map((notice) => (
        <div key={notice.id} className="flex items-center gap-3 rounded-md border border-primary/40 bg-primary/10 px-4 py-2 text-sm">
          <BellRing className="h-4 w-4 shrink-0" />
          <p className="flex-1">{language === "fr" ? notice.message_fr : notice.message_en}</p>
          <Link to="/treasury" className="font-medium underline">
            {t("treasury.alerts.view")}
          </Link>
          <button type="button" aria-label={t("treasury.alerts.dismiss")} onClick={() => readMutation.mutate(notice.id)}>
            <X className="h-4 w-4" />
          </button>
        </div>
      ))}
      {!dismissed && alerts.length > 0 && (
        <div className="flex items-center gap-3 rounded-md border border-warning/40 bg-warning/10 px-4 py-2 text-sm">
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
      )}
    </div>
  );
}
