import { useState } from "react";
import { ImageOff } from "lucide-react";
import { Dialog, DialogContent, DialogTitle } from "../../../components/ui/dialog";
import { Skeleton } from "../../../components/ui/skeleton";
import { useI18n } from "../../../lib/i18n";
import { cn } from "../../../lib/utils";
import { fetchCheckEntryPhotoBlob } from "../api";
import { useAuthedImage } from "../useAuthedImage";

/**
 * The proof photo of one check entry: a small thumbnail that opens the full
 * picture in a lightbox. The image is fetched with the bearer token
 * (`useAuthedImage`), so nothing is requested for an entry without a photo —
 * render this only when `entry.has_photo`.
 */
export function EntryPhoto({ entryId, className }: { entryId: string; className?: string }) {
  const { t } = useI18n();
  const { url, isLoading, isError } = useAuthedImage(fetchCheckEntryPhotoBlob, entryId);
  const [open, setOpen] = useState(false);

  if (isError) {
    return (
      <span
        className={cn("inline-flex h-11 w-11 items-center justify-center rounded-md bg-muted text-muted-foreground", className)}
        title={t("maintenance.jobs.photo.error")}
      >
        <ImageOff className="h-4 w-4" />
      </span>
    );
  }
  if (isLoading || !url) {
    return <Skeleton className={cn("h-11 w-11", className)} />;
  }

  return (
    <>
      <button
        type="button"
        onClick={(event) => {
          event.stopPropagation();
          setOpen(true);
        }}
        aria-label={t("maintenance.jobs.photo.open")}
        className={cn(
          "block h-11 w-11 shrink-0 overflow-hidden rounded-md border border-border transition-shadow hover:shadow-soft focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
          className,
        )}
      >
        <img src={url} alt="" className="h-full w-full object-cover" />
      </button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-3xl" aria-describedby={undefined}>
          <DialogTitle className="mb-3">{t("maintenance.jobs.photo.title")}</DialogTitle>
          <img src={url} alt="" className="max-h-[70dvh] w-full rounded-md object-contain" />
        </DialogContent>
      </Dialog>
    </>
  );
}
