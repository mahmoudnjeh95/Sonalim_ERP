import { ImageOff } from "lucide-react";
import { Checkbox } from "../../../components/ui/checkbox";
import { Skeleton } from "../../../components/ui/skeleton";
import { useI18n } from "../../../lib/i18n";
import { fetchViewImageBlob, type Checkpoint, type EquipmentView } from "../api";
import { CHECK_ACTION_ICON, CHECK_ACTION_LABEL_KEY } from "../labels";
import { useAuthedImage } from "../useAuthedImage";

function ViewThumbnail({ view }: { view: EquipmentView }) {
  const { url, isLoading, isError } = useAuthedImage(fetchViewImageBlob, view.id, view.updated_at);
  if (isError) {
    return (
      <span className="flex h-12 w-16 shrink-0 items-center justify-center rounded-md bg-muted text-muted-foreground">
        <ImageOff className="h-4 w-4" />
      </span>
    );
  }
  if (isLoading || !url) return <Skeleton className="h-12 w-16 shrink-0" />;
  return <img src={url} alt="" className="h-12 w-16 shrink-0 rounded-md border border-border object-cover" />;
}

function activeCheckpoints(view: EquipmentView): Checkpoint[] {
  return view.checkpoints.filter((checkpoint) => !checkpoint.archived_at).sort((a, b) => a.sort_order - b.sort_order);
}

/**
 * Multi-select of a machine's checkpoints, grouped by view (photo thumbnail +
 * view label, with a tick per view to take or drop all of its points).
 * Controlled: `value` is the list of selected checkpoint ids.
 *
 * Used by the new-job dialog; the program dialog needs the same control, so it
 * lives next to the map it reads from. Archived checkpoints are never offered.
 */
export function CheckpointPicker({
  views,
  value,
  onChange,
  isLoading = false,
}: {
  views: EquipmentView[];
  value: string[];
  onChange: (checkpointIds: string[]) => void;
  /** The views are still being fetched: skeleton rows instead of the empty message. */
  isLoading?: boolean;
}) {
  const { t } = useI18n();
  const selected = new Set(value);
  const groups = views
    .slice()
    .sort((a, b) => a.sort_order - b.sort_order)
    .map((view) => ({ view, checkpoints: activeCheckpoints(view) }))
    .filter((group) => group.checkpoints.length > 0);

  if (isLoading) {
    return (
      <div className="space-y-2 rounded-md border border-border p-3">
        <Skeleton className="h-12 w-full" />
        <Skeleton className="h-5 w-2/3" />
        <Skeleton className="h-5 w-1/2" />
      </div>
    );
  }

  if (groups.length === 0) {
    return (
      <p className="rounded-md border border-dashed border-border px-3 py-4 text-sm text-muted-foreground">
        {t("maintenance.checkpointPicker.empty")}
      </p>
    );
  }

  function toggle(checkpointId: string) {
    onChange(selected.has(checkpointId) ? value.filter((id) => id !== checkpointId) : [...value, checkpointId]);
  }

  function toggleView(checkpoints: Checkpoint[], allSelected: boolean) {
    const ids = checkpoints.map((checkpoint) => checkpoint.id);
    if (allSelected) {
      onChange(value.filter((id) => !ids.includes(id)));
    } else {
      onChange([...value, ...ids.filter((id) => !selected.has(id))]);
    }
  }

  return (
    <div className="max-h-80 space-y-3 overflow-y-auto rounded-md border border-border p-3 scrollbar-thin">
      {groups.map(({ view, checkpoints }) => {
        const selectedCount = checkpoints.filter((checkpoint) => selected.has(checkpoint.id)).length;
        const allSelected = selectedCount === checkpoints.length;
        return (
          <div key={view.id} className="space-y-1">
            <label className="flex min-h-11 cursor-pointer items-center gap-3 rounded-md px-1 py-1 hover:bg-muted">
              <Checkbox checked={allSelected} onCheckedChange={() => toggleView(checkpoints, allSelected)} />
              <ViewThumbnail view={view} />
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm font-medium">{view.label}</span>
                <span className="block text-xs text-muted-foreground">
                  {t("maintenance.checkpointPicker.selectedOf")
                    .replace("{selected}", String(selectedCount))
                    .replace("{total}", String(checkpoints.length))}
                </span>
              </span>
            </label>
            <ul className="space-y-0.5 pl-7">
              {checkpoints.map((checkpoint) => {
                const Icon = CHECK_ACTION_ICON[checkpoint.action];
                return (
                  <li key={checkpoint.id}>
                    <label className="flex min-h-10 cursor-pointer items-center gap-2 rounded-md px-2 py-1 text-sm hover:bg-muted">
                      <Checkbox checked={selected.has(checkpoint.id)} onCheckedChange={() => toggle(checkpoint.id)} />
                      <Icon className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
                      <span className="min-w-0 flex-1 truncate">{checkpoint.label}</span>
                      <span className="shrink-0 text-xs text-muted-foreground">{t(CHECK_ACTION_LABEL_KEY[checkpoint.action])}</span>
                    </label>
                  </li>
                );
              })}
            </ul>
          </div>
        );
      })}
    </div>
  );
}
