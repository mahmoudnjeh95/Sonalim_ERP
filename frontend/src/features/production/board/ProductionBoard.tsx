import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { motion, useReducedMotion } from "framer-motion";
import { CalendarDays, ChevronLeft, ChevronRight, Maximize2, Minimize2, Printer, RotateCw } from "lucide-react";
import { Link } from "react-router-dom";
import { useAuth } from "../../../lib/auth";
import { useI18n } from "../../../lib/i18n";
import { cn } from "../../../lib/utils";
import { getBoardDay, getBoardLines, getBoardLive, getBoardTrend } from "./api";
import { addDays, clockTime, formatDay, isoDay } from "./boardFormat";
import { BlockError } from "./BoardStates";
import { GlanceBand } from "./GlanceBand";
import { LinesBoard } from "./LinesBoard";
import { QualityBlock } from "./QualityBlock";
import { RankingCards } from "./RankingCards";
import { StockToday } from "./StockToday";
import { TrendCard } from "./TrendCard";
import { AppLoader } from "../../../components/patterns/AppLoader";
import { Skeleton } from "../../../components/ui/skeleton";

/**
 * The production board a manager opens in the morning: what happened
 * yesterday, what stands on the lines right now, and what waits to be
 * released. Each block fails on its own, so one broken read never blanks the
 * page. Supports instant date picking, 1-click presets, auto/manual refresh,
 * full-screen kiosk display for the factory floor, and daily report printing.
 */
export function ProductionBoard() {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const containerRef = useRef<HTMLDivElement>(null);
  const dateInputRef = useRef<HTMLInputElement>(null);

  const today = isoDay(new Date());
  const yesterday = addDays(today, -1);
  const [date, setDate] = useState(yesterday);
  const [isKiosk, setIsKiosk] = useState(false);
  const [lastUpdated, setLastUpdated] = useState(() => new Date());

  // Listen to fullscreen changes (e.g. Esc key pressed)
  useEffect(() => {
    const handleFullscreenChange = () => {
      setIsKiosk(Boolean(document.fullscreenElement));
    };
    document.addEventListener("fullscreenchange", handleFullscreenChange);
    return () => document.removeEventListener("fullscreenchange", handleFullscreenChange);
  }, []);

  const toggleKiosk = () => {
    if (!document.fullscreenElement) {
      containerRef.current?.requestFullscreen?.().catch(() => {});
      setIsKiosk(true);
    } else {
      document.exitFullscreen?.().catch(() => {});
      setIsKiosk(false);
    }
  };

  // The clock in the header is the plant's own: it is what the current shift is judged against.
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 30_000);
    return () => window.clearInterval(timer);
  }, []);

  const lines = useQuery({
    queryKey: ["production", "board", "lines", date],
    queryFn: () => getBoardLines(token, clockTime(new Date()), date),
    refetchInterval: 60_000,
  });

  // Automatically refresh today's data every 60s as shifts submit reports
  const day = useQuery({
    queryKey: ["production", "board", "day", date],
    queryFn: () => getBoardDay(token, date),
    refetchInterval: date === today ? 60_000 : false,
  });

  const live = useQuery({
    queryKey: ["production", "board", "live"],
    queryFn: () => getBoardLive(token, isoDay(new Date()), clockTime(new Date())),
    refetchInterval: 60_000,
    retry: false,
  });

  const weekParams = { date_from: addDays(date, -6), date_to: date, granularity: "day" as const };
  const week = useQuery({ queryKey: ["production", "board", "trend", weekParams], queryFn: () => getBoardTrend(token, weekParams) });

  const isRefreshing = lines.isFetching || day.isFetching || live.isFetching || week.isFetching;

  const handleManualRefresh = async () => {
    setLastUpdated(new Date());
    await Promise.all([
      lines.refetch(),
      day.refetch(),
      live.refetch(),
      week.refetch(),
      queryClient.invalidateQueries({ queryKey: ["qc"] }),
      queryClient.invalidateQueries({ queryKey: ["warehouse", "stock"] }),
    ]);
  };

  const primaryLoading = lines.isLoading || day.isLoading;
  const [booted, setBooted] = useState(false);
  useEffect(() => {
    if (!primaryLoading) setBooted(true);
  }, [primaryLoading]);
  const booting = !booted && primaryLoading;
  const reduceMotion = useReducedMotion();

  const isViewingToday = date === today;
  const isViewingYesterday = date === yesterday;
  const dateLabel = formatDay(date, { weekday: "long", day: "numeric", month: "long" });

  return (
    <div ref={containerRef} className={cn("space-y-4", isKiosk && "h-screen overflow-y-auto bg-slate-50 p-6")}>
      {/* Top Toolbar / Navigation Strip */}
      <div className="flex flex-wrap items-center justify-between gap-3 print:hidden">
        {/* Date Selector & Quick Toggles */}
        <div className="flex flex-wrap items-center gap-2">
          {/* Quick Presets */}
          <div className="flex items-center rounded-lg border border-border bg-white p-0.5 shadow-xs">
            <button
              type="button"
              onClick={() => setDate(yesterday)}
              className={cn(
                "rounded-md px-2.5 py-1 text-xs font-medium transition-colors",
                isViewingYesterday ? "bg-primary text-primary-foreground shadow-xs" : "text-muted-foreground hover:text-foreground",
              )}
            >
              {t("production.board.yesterday")}
            </button>
            <button
              type="button"
              onClick={() => setDate(today)}
              className={cn(
                "rounded-md px-2.5 py-1 text-xs font-medium transition-colors",
                isViewingToday ? "bg-primary text-primary-foreground shadow-xs" : "text-muted-foreground hover:text-foreground",
              )}
            >
              {t("production.board.today")}
            </button>
          </div>

          {/* Stepper with integrated direct Date Picker */}
          <div className="flex items-center gap-1">
            <button
              type="button"
              aria-label={t("production.board.prevDay")}
              onClick={() => setDate(addDays(date, -1))}
              className="rounded-lg border border-border bg-white p-1.5 text-primary hover:bg-muted"
            >
              <ChevronLeft className="h-4 w-4" />
            </button>

            {/* Clickable Date Display with hidden native picker trigger */}
            <div className="relative">
              <button
                type="button"
                onClick={() => dateInputRef.current?.showPicker?.()}
                title={t("production.board.pickDate")}
                className="group flex min-w-[14.5rem] items-center justify-center gap-2 rounded-lg bg-primary px-3.5 py-1.5 text-center text-sm font-medium capitalize text-primary-foreground shadow-xs transition hover:bg-primary/90"
              >
                <span>{dateLabel}</span>
                <CalendarDays className="h-3.5 w-3.5 opacity-80 transition group-hover:scale-110" />
              </button>
              <input
                ref={dateInputRef}
                type="date"
                value={date}
                max={today}
                onChange={(e) => e.target.value && setDate(e.target.value)}
                className="pointer-events-none absolute inset-0 opacity-0"
                aria-hidden="true"
                tabIndex={-1}
              />
            </div>

            <button
              type="button"
              aria-label={t("production.board.nextDay")}
              disabled={date >= today}
              onClick={() => setDate(addDays(date, 1))}
              className={cn(
                "rounded-lg border border-border bg-white p-1.5 text-primary hover:bg-muted",
                date >= today && "pointer-events-none opacity-40",
              )}
            >
              <ChevronRight className="h-4 w-4" />
            </button>
          </div>

          {/* Today In-Progress Badge */}
          {isViewingToday ? (
            <span className="inline-flex items-center gap-1.5 rounded-full border border-primary/20 bg-primary/10 px-2.5 py-0.5 text-xs font-semibold text-primary">
              <span className="h-1.5 w-1.5 rounded-full bg-primary animate-pulse" />
              {t("production.board.todayInProgress")}
            </span>
          ) : null}
        </div>

        {/* Live Plant Telemetry, Awaiting Validation & Control Toolbar */}
        <div className="flex flex-wrap items-center gap-2 text-sm">
          {day.data && day.data.awaiting_validation > 0 ? (
            <Link
              to="/production?tab=validation"
              className="rounded-lg border border-[#f1d9a0] bg-warning-soft px-3 py-1.5 text-xs font-medium text-warning hover:underline"
            >
              {day.data.awaiting_validation} {t("production.board.awaiting")}
            </Link>
          ) : null}

          {/* Plant Live Clock */}
          <span className="flex items-center gap-2 rounded-lg border border-border bg-white px-2.5 py-1 text-xs text-muted-foreground">
            <i className="h-2 w-2 rounded-full bg-success board-team-now" aria-hidden="true" />
            <span className="font-semibold text-foreground">{t("production.board.live")}</span>
            <span>· {clockTime(now)}</span>
            {lines.data?.current_shift ? <span className="font-medium text-primary">· {lines.data.current_shift.shift}</span> : ""}
          </span>

          {/* Manual Refresh Button & Last Updated Timestamp */}
          <button
            type="button"
            onClick={() => void handleManualRefresh()}
            disabled={isRefreshing}
            title={`${t("production.board.refresh")} (${t("production.board.lastUpdated")} ${clockTime(lastUpdated)})`}
            className="flex items-center gap-1.5 rounded-lg border border-border bg-white px-2.5 py-1 text-xs font-medium text-primary hover:bg-muted disabled:opacity-60"
          >
            <RotateCw className={cn("h-3.5 w-3.5", isRefreshing && "animate-spin text-primary")} />
            <span className="hidden sm:inline">{clockTime(lastUpdated)}</span>
          </button>

          {/* Kiosk / TV Fullscreen Mode Toggle */}
          <button
            type="button"
            onClick={toggleKiosk}
            title={isKiosk ? t("production.board.exitKiosk") : t("production.board.kiosk")}
            className="rounded-lg border border-border bg-white p-1.5 text-primary hover:bg-muted"
          >
            {isKiosk ? <Minimize2 className="h-4 w-4" /> : <Maximize2 className="h-4 w-4" />}
          </button>

          {/* Print Daily Brief */}
          <button
            type="button"
            onClick={() => window.print()}
            title={t("production.board.print")}
            className="rounded-lg border border-border bg-white p-1.5 text-primary hover:bg-muted"
          >
            <Printer className="h-4 w-4" />
          </button>
        </div>
      </div>

      {booting && <AppLoader fullScreen label={t("production.board.loading")} />}

      <motion.div
        initial={false}
        animate={{ opacity: booting ? 0 : 1, y: booting ? 8 : 0 }}
        transition={{ duration: reduceMotion ? 0 : 0.35, ease: "easeOut" }}
        className={cn("space-y-4", booting && "hidden")}
      >
        {day.isError ? (
          <BlockError onRetry={() => void day.refetch()} />
        ) : (
          <GlanceBand day={day.data} isLoading={day.isLoading} trend={week.data?.current.points} isToday={isViewingToday} />
        )}

        <section>
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h2 className="text-base font-semibold text-primary">{t("production.board.lines.title")}</h2>
            <p className="text-xs text-muted-foreground">{t("production.board.lines.subtitle")}</p>
          </div>
          {lines.isError ? (
            <BlockError onRetry={() => void lines.refetch()} />
          ) : lines.isLoading || !lines.data ? (
            <Skeleton className="mt-3 h-52 w-full" />
          ) : (
            <LinesBoard board={lines.data} day={day.data} dayIsLoading={day.isLoading} live={live.data} today={today} />
          )}
        </section>

        <StockToday />

        <TrendCard date={date} />

        {day.data ? <RankingCards day={day.data} lines={lines.data?.lines} /> : null}

        <section className="space-y-2">
          <h2 className="text-base font-semibold text-primary">{t("production.board.quality.title")}</h2>
          <QualityBlock date={date} />
        </section>
      </motion.div>
    </div>
  );
}
