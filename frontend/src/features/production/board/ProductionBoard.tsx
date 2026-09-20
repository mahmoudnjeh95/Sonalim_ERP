import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { Link } from "react-router-dom";
import { useAuth } from "../../../lib/auth";
import { useI18n } from "../../../lib/i18n";
import { cn } from "../../../lib/utils";
import { Skeleton } from "../../../components/ui/skeleton";
import { getBoardDay, getBoardLines, getBoardTrend } from "./api";
import { addDays, clockTime, formatDay, isoDay } from "./boardFormat";
import { BlockError } from "./BoardStates";
import { GlanceBand } from "./GlanceBand";
import { LinesBoard } from "./LinesBoard";
import { QualityBlock } from "./QualityBlock";
import { RankingCards } from "./RankingCards";
import { StockToday } from "./StockToday";
import { TrendCard } from "./TrendCard";

/**
 * The production board a manager opens in the morning: what happened
 * yesterday, what stands on the lines right now, and what waits to be
 * released. Each block loads and fails on its own, so one slow or broken read
 * never blanks the page.
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

  // Same parameters as the chart's "week" tab, so the two share one cached read.
  const weekParams = { date_from: addDays(date, -6), date_to: date, granularity: "day" as const };
  const week = useQuery({ queryKey: ["production", "board", "trend", weekParams], queryFn: () => getBoardTrend(token, weekParams) });

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

      {day.isError ? <BlockError onRetry={() => void day.refetch()} /> : <GlanceBand day={day.data} isLoading={day.isLoading} trend={week.data?.current.points} />}

      <section>
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="text-base font-semibold text-primary">{t("production.board.lines.title")}</h2>
          <p className="text-xs text-muted-foreground">{t("production.board.lines.subtitle")}</p>
        </div>
        {lines.isError ? (
          <BlockError onRetry={() => void lines.refetch()} />
        ) : lines.isLoading || !lines.data ? (
          <div className="mt-6 space-y-3">
            <Skeleton className="h-52 w-full" />
            <Skeleton className="h-52 w-full" />
          </div>
        ) : (
          <LinesBoard board={lines.data} day={day.data} dayIsLoading={day.isLoading} />
        )}
      </section>

      <StockToday />

      <TrendCard date={date} />

      {day.data ? <RankingCards day={day.data} lines={lines.data?.lines} /> : null}

      <section className="space-y-2">
        <h2 className="text-base font-semibold text-primary">{t("production.board.quality.title")}</h2>
        <QualityBlock date={date} />
      </section>
    </div>
  );
}
