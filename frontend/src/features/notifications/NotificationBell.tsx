import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell } from "lucide-react";
import { useAuth } from "../../lib/auth";
import { useI18n, currentLocale } from "../../lib/i18n";
import { cn } from "../../lib/utils";
import { Popover, PopoverContent, PopoverTrigger } from "../../components/ui/popover";
import {
  getUnreadNotificationCount,
  listNotifications,
  markAllNotificationsRead,
  markNotificationRead,
  type AppNotification,
} from "./api";

const UNREAD_COUNT_QUERY_KEY = ["notifications", "unread-count"] as const;
const LIST_QUERY_KEY = ["notifications", "list"] as const;
// The bell polls rather than relying on a live channel; the sweep worker and
// the app itself both publish notifications, so 60 s is the agreed-on bound
// on how stale the badge is allowed to be (brief Global Constraints).
const POLL_INTERVAL_MS = 60_000;

const RELATIVE_UNITS: Array<[Intl.RelativeTimeFormatUnit, number]> = [
  ["year", 60 * 60 * 24 * 365],
  ["month", 60 * 60 * 24 * 30],
  ["week", 60 * 60 * 24 * 7],
  ["day", 60 * 60 * 24],
  ["hour", 60 * 60],
  ["minute", 60],
];

// `currentLocale()` already follows the app's language toggle (see lib/i18n),
// not the browser's OS locale, so the relative phrasing always matches the
// title/body language shown next to it.
function formatRelativeTime(iso: string): string {
  const deltaSeconds = (new Date(iso).getTime() - Date.now()) / 1000;
  const formatter = new Intl.RelativeTimeFormat(currentLocale(), { numeric: "auto" });
  for (const [unit, secondsInUnit] of RELATIVE_UNITS) {
    if (Math.abs(deltaSeconds) >= secondsInUnit) {
      return formatter.format(Math.round(deltaSeconds / secondsInUnit), unit);
    }
  }
  return formatter.format(Math.round(deltaSeconds), "second");
}

function NotificationRow({ notification, onOpen }: { notification: AppNotification; onOpen: (notification: AppNotification) => void }) {
  const { language } = useI18n();
  const title = language === "fr" ? notification.title_fr : notification.title;
  const body = language === "fr" ? notification.body_fr : notification.body;
  const unread = !notification.read_at;

  return (
    <button
      type="button"
      onClick={() => onOpen(notification)}
      className={cn(
        "flex w-full items-start gap-2 rounded-md px-2 py-2 text-left text-sm transition-colors hover:bg-muted",
        unread && "bg-primary/5",
      )}
    >
      <span className={cn("mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full", unread ? "bg-primary" : "bg-transparent")} aria-hidden />
      <span className="min-w-0 flex-1">
        <span className={cn("line-clamp-2 break-words", unread ? "font-medium text-foreground" : "text-muted-foreground")}>{title}</span>
        {body && <span className="line-clamp-2 break-words text-xs text-muted-foreground">{body}</span>}
        <span className="block text-[11px] text-muted-foreground/70">{formatRelativeTime(notification.created_at)}</span>
      </span>
    </button>
  );
}

/**
 * Bell with an unread-count badge and a popover listing the latest
 * notifications. Lives in the sidebar footer (desktop/collapsed) and the
 * mobile top bar — see `routes/Sidebar.tsx` and `routes/AppLayout.tsx`.
 */
export function NotificationBell({ collapsed = false }: { collapsed?: boolean }) {
  const { session } = useAuth();
  const { t } = useI18n();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const token = session?.token ?? null;
  const [open, setOpen] = useState(false);

  const countQuery = useQuery({
    queryKey: UNREAD_COUNT_QUERY_KEY,
    queryFn: () => getUnreadNotificationCount(token!),
    enabled: !!token,
    refetchInterval: POLL_INTERVAL_MS,
  });

  const listQuery = useQuery({
    queryKey: LIST_QUERY_KEY,
    queryFn: () => listNotifications(token!),
    enabled: !!token && open,
  });

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: UNREAD_COUNT_QUERY_KEY });
    queryClient.invalidateQueries({ queryKey: LIST_QUERY_KEY });
  };

  const handleOpenNotification = async (notification: AppNotification) => {
    if (!token) return;
    setOpen(false);
    if (!notification.read_at) {
      try {
        await markNotificationRead(token, notification.id);
      } finally {
        invalidate();
      }
    }
    if (notification.link) navigate(notification.link);
  };

  const handleMarkAllRead = async () => {
    if (!token) return;
    try {
      await markAllNotificationsRead(token);
    } finally {
      invalidate();
    }
  };

  const count = countQuery.data?.count ?? 0;
  const notifications = listQuery.data ?? [];

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-label={t("notifications.title")}
          title={collapsed ? t("notifications.title") : undefined}
          className={cn(
            "relative flex items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground",
            collapsed ? "h-8 w-8" : "h-8 w-8",
          )}
        >
          <Bell className="h-4 w-4" />
          {count > 0 && (
            <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-destructive px-1 text-[10px] font-semibold leading-none text-destructive-foreground">
              {count > 9 ? "9+" : count}
            </span>
          )}
        </button>
      </PopoverTrigger>

      <PopoverContent align="end" side={collapsed ? "right" : "top"} className="w-80 p-2">
        <div className="flex items-center justify-between border-b border-border px-1 pb-2">
          <p className="text-sm font-semibold">{t("notifications.title")}</p>
          <button
            type="button"
            onClick={handleMarkAllRead}
            disabled={count === 0}
            className="text-xs font-medium text-primary transition-opacity hover:underline disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:no-underline"
          >
            {t("notifications.markAllRead")}
          </button>
        </div>

        <div className="mt-1 max-h-96 space-y-0.5 overflow-y-auto">
          {listQuery.isLoading && <p className="px-2 py-4 text-center text-xs text-muted-foreground">{t("notifications.loading")}</p>}
          {!listQuery.isLoading && notifications.length === 0 && (
            <p className="px-2 py-6 text-center text-sm text-muted-foreground">{t("notifications.empty")}</p>
          )}
          {notifications.map((notification) => (
            <NotificationRow key={notification.id} notification={notification} onOpen={handleOpenNotification} />
          ))}
        </div>
      </PopoverContent>
    </Popover>
  );
}
