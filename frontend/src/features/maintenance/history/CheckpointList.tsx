import { useState } from "react";
import { Badge } from "../../../components/ui/badge";
import { Button } from "../../../components/ui/button";
import { useI18n } from "../../../lib/i18n";
import { useIsMobile } from "../../../lib/useIsMobile";
import { cn } from "../../../lib/utils";
import { formatDay, formatMeasure } from "../jobs/jobFormat";
import { OUTCOME_LABEL_KEY } from "../labels";
import type { CheckpointSummary } from "./api";
import { fill, sparklinePoints } from "./historyFormat";

function Sparkline({ values }: { values: number[] }) {
  const points = sparklinePoints(values, 58, 20);
  const last = points[points.length - 1];
  return (
    <svg viewBox="0 0 58 20" className="h-5 w-14 shrink-0" aria-hidden>
      <polyline
        points={points.map((p) => `${p.x},${p.y}`).join(" ")}
        fill="none"
        className="stroke-primary"
        strokeWidth="1.6"
        strokeLinejoin="round"
      />
      <circle cx={last.x} cy={last.y} r="2.6" className="fill-accent" />
    </svg>
  );
}

/** The machine's checkpoints in map order; each opens its history. On a phone the list sits behind a toggle. */
export function CheckpointList({ points, onOpen }: { points: CheckpointSummary[]; onOpen: (checkpointId: string) => void }) {
  const { t } = useI18n();
  const isMobile = useIsMobile();
  const [open, setOpen] = useState(false);
  const shown = !isMobile || open;
  return (
    <div>
      <div className="flex items-baseline justify-between px-4 pb-2 pt-3">
        <h2 className="text-sm font-semibold">{t("maintenance.history.points.title")}</h2>
        <span className="text-xs text-muted-foreground">{fill(t("maintenance.history.points.count"), { n: points.length })}</span>
      </div>
      {isMobile && (
        <div className="px-4 pb-3">
          <Button variant="outline" size="sm" className="w-full" aria-expanded={open} onClick={() => setOpen((value) => !value)}>
            {open ? t("maintenance.history.points.hide") : fill(t("maintenance.history.points.show"), { n: points.length })}
          </Button>
        </div>
      )}
      {shown &&
        (points.length === 0 ? (
          <p className="px-4 pb-4 text-sm text-muted-foreground">{t("maintenance.history.points.none")}</p>
        ) : (
          <ul className="divide-y divide-border border-t border-border">
            {points.map((point, index) => (
              <li key={point.checkpoint_id}>
                <button
                  type="button"
                  onClick={() => onOpen(point.checkpoint_id)}
                  className="flex w-full items-center gap-3 px-4 py-2.5 text-left transition-colors hover:bg-muted/40"
                >
                  <span
                    className={cn(
                      "grid h-6 w-6 shrink-0 place-items-center rounded-full text-[11px] font-bold",
                      point.checks_count === 0
                        ? "bg-muted text-muted-foreground"
                        : point.last_outcome === "issue"
                          ? "bg-destructive text-destructive-foreground"
                          : "bg-primary text-primary-foreground",
                    )}
                  >
                    {index + 1}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-medium">
                      {point.label}
                      {point.archived && <span className="ml-1 text-xs text-muted-foreground">({t("maintenance.history.points.archived")})</span>}
                    </span>
                    <span className="block truncate text-xs text-muted-foreground">
                      {point.last_checked_at && point.last_outcome
                        ? `${formatDay(point.last_checked_at)} · ${t(OUTCOME_LABEL_KEY[point.last_outcome])}`
                        : t("maintenance.history.points.never")}
                    </span>
                  </span>
                  {point.recent_measures.length >= 2 && <Sparkline values={point.recent_measures.map((m) => m.value)} />}
                  {point.last_measured_value !== null && (
                    <span className="shrink-0 whitespace-nowrap text-right text-xs tabular-nums text-muted-foreground">
                      {formatMeasure(point.last_measured_value, point.measure_unit)}
                    </span>
                  )}
                  {point.issues_count > 0 && (
                    <Badge variant="destructive">{fill(t("maintenance.history.points.issues"), { n: point.issues_count })}</Badge>
                  )}
                </button>
              </li>
            ))}
          </ul>
        ))}
    </div>
  );
}
