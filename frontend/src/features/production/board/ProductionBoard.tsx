import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { motion, useReducedMotion } from "framer-motion";
import { ChevronLeft, ChevronRight } from "lucide-react";
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
 * page. The first load shows the branded loader once for the whole board (the
 * blocks stay mounted behind it so all their reads run in parallel); after that
 * a block that is still waiting, or a day change, only shows a quiet skeleton.
 */
export function ProductionBoard() {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;

  const today = isoDay(new Date());
  const yesterday = addDays(today, -1);
  const [date, setDate] = useState(yesterday);

  // The clock in the header is the plant's own: it is what the current shift is judged against.
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 30_000);
    return () => window.clearInterval(timer);
  }, []);

  const lines = useQuery({
    queryKey: ["production", "board", "lines"],
    queryFn: () => getBoardLines(token, clockTime(new Date())),
    refetchInterval: 60_000,
  });
  const day = useQuery({ queryKey: ["production", "board", "day", date], queryFn: () => getBoardDay(token, date) });
  // The shift running now, from what its team has entered so far. Shown apart from the validated
  // figures; if it cannot be read the board simply has no live strip.
  const live = useQuery({
    queryKey: ["production", "board", "live"],
    queryFn: () => getBoardLive(token, isoDay(new Date()), clockTime(new Date())),
    refetchInterval: 60_000,
    retry: false,
  });

  // Same parameters as the chart's "week" tab, so the two share one cached read.
  const weekParams = { date_from: addDays(date, -6), date_to: date, granularity: "day" as const };
  const week = useQuery({ queryKey: ["production", "board", "trend", weekParams], queryFn: () => getBoardTrend(token, weekParams) });

  // The board only counts as "booting" until its two primary reads have answered once. Later
  // refetches and day changes never bring the loader back.
  const primaryLoading = lines.isLoading || day.isLoading;
  const [booted, setBooted] = useState(false);
  useEffect(() => {
    if (!primaryLoading) setBooted(true);
  }, [primaryLoading]);
  const booting = !booted && primaryLoading;
  const reduceMotion = useReducedMotion();

  const dateLabel = formatDay(date, { weekday: "long", day: "numeric", month: "long" });

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <button type="button" aria-label={t("production.board.prevDay")} onClick={() => setDate(addDays(date, -1))} className="rounded-lg border border-border bg-white p-1.5 text-primary hover:bg-muted">
            <ChevronLeft className="h-4 w-4" />
          </button>
          <span className="min-w-[14rem] rounded-lg bg-primary px-3 py-1.5 text-center text-sm font-medium capitalize text-primary-foreground">{dateLabel}</span>
          <button type="button" aria-label={t("production.board.nextDay")} disabled={date >= today} onClick={() => setDate(addDays(date, 1))} className={cn("rounded-lg border border-border bg-white p-1.5 text-primary hover:bg-muted", date >= today && "pointer-events-none opacity-40")}>
            <ChevronRight className="h-4 w-4" />
          </button>
        </div>
        <div className="flex flex-wrap items-center gap-3 text-sm">
          {day.data && day.data.awaiting_validation > 0 ? (
            <Link to="/production?tab=validation" className="rounded-lg border border-[#f1d9a0] bg-warning-soft px-3 py-1.5 text-warning hover:underline">
              {day.data.awaiting_validation} {t("production.board.awaiting")}
            </Link>
          ) : null}
          <span className="flex items-center gap-2 text-muted-foreground">
            <i className="h-2 w-2 rounded-full bg-success board-team-now" aria-hidden="true" />
            {t("production.board.live")} · {clockTime(now)}
            {lines.data?.current_shift ? ` · ${lines.data.current_shift.shift}` : ""}
          </span>
        </div>
      </div>

      {booting && <AppLoader fullScreen label={t("production.board.loading")} />}

      <motion.div
        initial={false}
        animate={{ opacity: booting ? 0 : 1, y: booting ? 8 : 0 }}
        transition={{ duration: reduceMotion ? 0 : 0.35, ease: "easeOut" }}
        className={cn("space-y-4", booting && "hidden")}
      >
        {day.isError ? <BlockError onRetry={() => void day.refetch()} /> : <GlanceBand day={day.data} isLoading={day.isLoading} trend={week.data?.current.points} />}

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
            <LinesBoard board={lines.data} day={day.data} dayIsLoading={day.isLoading} live={live.data} />
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
