import { useEffect, useRef, useState } from "react";
import { Camera, ImagePlus, Loader2, RotateCcw, Trash2 } from "lucide-react";
import { useI18n } from "../../../lib/i18n";
import { cn } from "../../../lib/utils";
import { shrinkImageToFile } from "../map/shrinkImageFile";

// The API takes JPEG, PNG or WebP up to 10 MB (spec: image limit 10 MB).
const ACCEPTED_TYPES = ["image/jpeg", "image/png", "image/webp"];
const MAX_BYTES = 10 * 1024 * 1024;

/**
 * The point's photo proof: "Prendre une photo" opens the phone's rear camera straight away
 * (`capture="environment"`), the gallery stays one tap away. The picture is made upright and
 * shrunk to the upload budget (same steps as the scan's `imagePrep`) before it is kept.
 */
export function PhotoProofInput({
  file,
  onChange,
  required,
  error,
  disabled,
}: {
  file: File | null;
  onChange: (file: File | null) => void;
  required: boolean;
  error?: string;
  disabled?: boolean;
}) {
  const { t } = useI18n();
  const cameraRef = useRef<HTMLInputElement>(null);
  const galleryRef = useRef<HTMLInputElement>(null);
  const [preparing, setPreparing] = useState(false);
  const [unreadable, setUnreadable] = useState(false);
  const [preview, setPreview] = useState<string | null>(null);

  useEffect(() => {
    if (!file) {
      setPreview(null);
      return;
    }
    const url = URL.createObjectURL(file);
    setPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  async function pick(files: FileList | null) {
    const picked = files?.[0];
    if (!picked) return;
    setUnreadable(false);
    setPreparing(true);
    try {
      onChange(await shrinkImageToFile(picked));
    } catch {
      // A format the browser cannot draw (e.g. HEIC on some phones): send it as it is when the API accepts it.
      if (ACCEPTED_TYPES.includes(picked.type) && picked.size <= MAX_BYTES) onChange(picked);
      else setUnreadable(true);
    } finally {
      setPreparing(false);
    }
  }

  const inputs = (
    <>
      <input
        ref={cameraRef}
        type="file"
        accept="image/*"
        capture="environment"
        hidden
        onChange={(event) => {
          void pick(event.target.files);
          event.target.value = "";
        }}
      />
      <input
        ref={galleryRef}
        type="file"
        accept="image/*"
        hidden
        onChange={(event) => {
          void pick(event.target.files);
          event.target.value = "";
        }}
      />
    </>
  );

  const shownError = unreadable ? t("maintenance.wizard.photo.unreadable") : error;

  return (
    <div className="space-y-2">
      <p className="flex items-baseline gap-2 text-sm font-medium">
        {t("maintenance.wizard.photo")}
        <span className={cn("text-xs font-normal", required ? "text-destructive" : "text-muted-foreground")}>
          {required ? t("maintenance.wizard.required") : t("maintenance.wizard.optional")}
        </span>
      </p>
      {inputs}

      {preparing ? (
        <div className="flex h-28 items-center justify-center gap-2 rounded-xl border-2 border-dashed border-border bg-muted/50 text-sm text-muted-foreground">
          <Loader2 className="h-5 w-5 animate-spin" />
          {t("maintenance.wizard.photo.preparing")}
        </div>
      ) : preview ? (
        <div className="flex items-stretch gap-3">
          <img src={preview} alt="" className="h-28 w-28 shrink-0 rounded-xl border border-border object-cover" />
          <div className="flex min-w-0 flex-1 flex-col justify-center gap-2">
            <button
              type="button"
              onClick={() => cameraRef.current?.click()}
              disabled={disabled}
              className="flex min-h-11 items-center gap-2 rounded-lg border border-border bg-background px-3 text-sm font-medium transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50"
            >
              <RotateCcw className="h-4 w-4" />
              {t("maintenance.wizard.photo.retake")}
            </button>
            <button
              type="button"
              onClick={() => onChange(null)}
              disabled={disabled}
              className="flex min-h-11 items-center gap-2 rounded-lg px-3 text-sm font-medium text-destructive transition-colors hover:bg-destructive-soft focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50"
            >
              <Trash2 className="h-4 w-4" />
              {t("maintenance.wizard.photo.remove")}
            </button>
          </div>
        </div>
      ) : (
        <div className="space-y-1">
          <button
            type="button"
            onClick={() => cameraRef.current?.click()}
            disabled={disabled}
            className={cn(
              "flex h-16 w-full items-center justify-center gap-3 rounded-xl border-2 border-dashed text-base font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50",
              shownError ? "border-destructive bg-destructive-soft text-destructive" : "border-primary/40 bg-primary/5 text-primary hover:bg-primary/10",
            )}
          >
            <Camera className="h-6 w-6" />
            {t("maintenance.wizard.photo.take")}
          </button>
          <div className="flex justify-center">
            <button
              type="button"
              onClick={() => galleryRef.current?.click()}
              disabled={disabled}
              className="inline-flex min-h-11 items-center gap-1.5 rounded-md px-2 text-sm font-medium text-muted-foreground underline-offset-4 hover:text-foreground hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50"
            >
              <ImagePlus className="h-4 w-4" />
              {t("maintenance.wizard.photo.gallery")}
            </button>
          </div>
        </div>
      )}
      {shownError && (
        <p className="text-sm font-medium text-destructive" role="alert">
          {shownError}
        </p>
      )}
    </div>
  );
}
