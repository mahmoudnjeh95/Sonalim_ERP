import { ImageOff } from "lucide-react";
import { Skeleton } from "../../../components/ui/skeleton";
import { useAuth } from "../../../lib/auth";
import { useI18n, type TranslationKey } from "../../../lib/i18n";
import { cn } from "../../../lib/utils";
import { fetchViewImageBlob, useEquipmentViews, type JobCheck, type JobDetail } from "../api";
import { PinnedPhoto, type Pin, type PinTone } from "../map/PinnedPhoto";
import { useAuthedImage } from "../useAuthedImage";
import { checkPinTone } from "./jobFormat";

interface NumberedCheck {
  check: JobCheck;
  /** The point's number on the job (its row in the checks table), not its number on the machine's map. */
  n: number;
}

const LEGEND: { tone: PinTone; labelKey: TranslationKey; className: string }[] = [
  { tone: "dim", labelKey: "maintenance.jobs.views.legend.pending", className: "border-border bg-muted" },
  { tone: "default", labelKey: "maintenance.jobs.views.legend.done", className: "border-primary bg-primary" },
  { tone: "done", labelKey: "maintenance.jobs.views.legend.accepted", className: "border-success bg-success" },
  { tone: "issue", labelKey: "maintenance.jobs.views.legend.redo", className: "border-destructive bg-destructive" },
];

function ViewPhoto({
  viewId,
  version,
  ready,
  pins,
  onPinClick,
}: {
  viewId: string;
  version: string | null;
  /** False while the machine's views are still loading: the photo waits so it is fetched once, with its version. */
  ready: boolean;
  pins: Pin[];
  onPinClick: (checkId: string) => void;
}) {
  const { t } = useI18n();
  const { url, isError } = useAuthedImage(fetchViewImageBlob, ready ? viewId : null, version);
  if (isError) {
    return (
      <div className="flex aspect-[4/3] w-full flex-col items-center justify-center gap-2 rounded-lg bg-muted text-sm text-muted-foreground">
        <ImageOff className="h-5 w-5" />
        {t("maintenance.jobs.views.photoError")}
      </div>
    );
  }
  if (!url) return <Skeleton className="aspect-[4/3] w-full rounded-lg" />;
  return <PinnedPhoto src={url} pins={pins} onPinClick={onPinClick} />;
}

/**
 * The machine photos the job's points were pinned on, each with its points
 * numbered as in the checks table and coloured by state. Positions and view
 * ids come from the job's own snapshot (`JobCheck.view_id/x_pct/y_pct`), so a
 * later edit of the machine's map never moves them; only the view's label is
 * read from the live map. Ad-hoc tasks have no photo and are not shown here.
 */
export function JobViewsStrip({
  job,
  highlightedCheckId,
  onPinClick,
}: {
  job: JobDetail;
  highlightedCheckId: string | null;
  onPinClick: (checkId: string) => void;
}) {
  const { session } = useAuth();
  const { t } = useI18n();
  const { data: views = [], isLoading: viewsLoading } = useEquipmentViews(session!.token, job.equipment_id);

  const byView = new Map<string, NumberedCheck[]>();
  job.checks.forEach((check, index) => {
    if (!check.view_id || check.x_pct === null || check.y_pct === null) return;
    const group = byView.get(check.view_id) ?? [];
    group.push({ check, n: index + 1 });
    byView.set(check.view_id, group);
  });
  if (byView.size === 0) return null;

  const knownViews = new Map(views.map((view) => [view.id, view]));
  // The machine's own view order where known; a view no longer on the map keeps its place at the end.
  const viewIds = [...byView.keys()].sort((a, b) => {
    const orderA = knownViews.get(a)?.sort_order ?? Number.MAX_SAFE_INTEGER;
    const orderB = knownViews.get(b)?.sort_order ?? Number.MAX_SAFE_INTEGER;
    return orderA - orderB;
  });

  return (
    <div className="space-y-3">
      <div className={cn("grid grid-cols-1 gap-4", viewIds.length > 1 && "lg:grid-cols-2")}>
        {viewIds.map((viewId, index) => {
          const view = knownViews.get(viewId);
          const pins: Pin[] = (byView.get(viewId) ?? []).map(({ check, n }) => ({
            id: check.id,
            x: check.x_pct ?? 0,
            y: check.y_pct ?? 0,
            n,
            tone: check.id === highlightedCheckId ? "active" : checkPinTone(check),
          }));
          return (
            <figure key={viewId} className="space-y-2">
              <figcaption className="flex items-baseline justify-between gap-2 text-sm">
                <span className="min-w-0 truncate font-medium">
                  {view?.label ?? t("maintenance.jobs.views.fallbackLabel").replace("{n}", String(index + 1))}
                </span>
                <span className="shrink-0 text-xs text-muted-foreground">
                  {t("maintenance.jobs.views.points").replace("{count}", String(pins.length))}
                </span>
              </figcaption>
              <ViewPhoto viewId={viewId} version={view?.updated_at ?? null} ready={!viewsLoading} pins={pins} onPinClick={onPinClick} />
            </figure>
          );
        })}
      </div>
      <ul className="flex flex-wrap gap-x-4 gap-y-1.5 text-xs text-muted-foreground">
        {LEGEND.map((item) => (
          <li key={item.tone} className="flex items-center gap-1.5">
            <span className={cn("h-3 w-3 rounded-full border-2", item.className)} aria-hidden />
            {t(item.labelKey)}
          </li>
        ))}
      </ul>
    </div>
  );
}
