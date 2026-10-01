import { useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { motion } from "framer-motion";
import { cn } from "../../../lib/utils";

export type PinTone = "default" | "active" | "done" | "issue" | "dim";

export interface Pin {
  id: string;
  /** Percent of the image box, 0-100. */
  x: number;
  /** Percent of the image box, 0-100. */
  y: number;
  n: number;
  tone: PinTone;
}

export interface PinnedPhotoProps {
  src: string;
  pins: Pin[];
  /** Click/tap on the photo itself, at the % position within the image box — used by the editor's "add point" mode. */
  onPick?: (x: number, y: number) => void;
  onPinClick?: (id: string) => void;
  /** Dragging a pin to a new % position — the editor PATCHes x_pct/y_pct on drop. */
  onPinMove?: (id: string, x: number, y: number) => void;
  className?: string;
}

const TONE_CLASS: Record<PinTone, string> = {
  default: "border-primary bg-primary text-primary-foreground",
  active: "border-accent bg-accent text-accent-foreground",
  done: "border-success bg-success text-success-foreground",
  issue: "border-destructive bg-destructive text-destructive-foreground",
  dim: "border-border bg-muted text-muted-foreground opacity-60",
};

/**
 * A photo (machine view, job photo, wizard checkpoint photo…) with numbered
 * pins placed at percentage coordinates of the image's own box, so pins stay
 * aligned regardless of the box's rendered size. Reused by the checkpoint-map
 * editor (F3), the job page (F4) and the check wizard (F5):
 * - F3 passes `onPick` (tap-to-place a new point) and `onPinMove` (drag to
 *   reposition an existing one) — editing mode.
 * - F4/F5 render read-only pins (no `onPick`/`onPinMove`) and use
 *   `onPinClick` to open a point's detail/entry form.
 *
 * The image is `object-contain` inside a relative box matched to the image's
 * own aspect ratio (via a loaded-size measurement), so percent coordinates
 * always land on the photo itself, never in the surrounding letterboxing.
 */
export function PinnedPhoto({ src, pins, onPick, onPinClick, onPinMove, className }: PinnedPhotoProps) {
  const boxRef = useRef<HTMLDivElement>(null);
  const [aspectRatio, setAspectRatio] = useState<number | null>(null);
  const [draggingId, setDraggingId] = useState<string | null>(null);
  const dragMoved = useRef(false);

  function percentFromEvent(clientX: number, clientY: number): { x: number; y: number } | null {
    const box = boxRef.current;
    if (!box) return null;
    const rect = box.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) return null;
    const x = Math.min(100, Math.max(0, ((clientX - rect.left) / rect.width) * 100));
    const y = Math.min(100, Math.max(0, ((clientY - rect.top) / rect.height) * 100));
    return { x, y };
  }

  function handlePhotoClick(event: ReactPointerEvent<HTMLDivElement>) {
    if (!onPick || draggingId) return;
    const point = percentFromEvent(event.clientX, event.clientY);
    if (point) onPick(point.x, point.y);
  }

  function handlePinPointerDown(pinId: string, event: ReactPointerEvent<HTMLButtonElement>) {
    if (!onPinMove) return;
    event.stopPropagation();
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    dragMoved.current = false;
    setDraggingId(pinId);
  }

  function handlePinPointerMove(pinId: string, event: ReactPointerEvent<HTMLButtonElement>) {
    if (draggingId !== pinId || !onPinMove) return;
    const point = percentFromEvent(event.clientX, event.clientY);
    if (!point) return;
    dragMoved.current = true;
    onPinMove(pinId, point.x, point.y);
  }

  function handlePinPointerUp(pinId: string, event: ReactPointerEvent<HTMLButtonElement>) {
    if (draggingId === pinId) {
      event.currentTarget.releasePointerCapture(event.pointerId);
      setDraggingId(null);
      // A tap that never moved is a click, not a drag-drop.
      if (!dragMoved.current) onPinClick?.(pinId);
    }
  }

  return (
    <div
      ref={boxRef}
      onClick={handlePhotoClick}
      className={cn(
        "relative w-full select-none overflow-hidden rounded-lg bg-muted",
        onPick && "cursor-crosshair",
        className,
      )}
      style={aspectRatio ? { aspectRatio: String(aspectRatio) } : undefined}
    >
      <img
        src={src}
        alt=""
        draggable={false}
        onLoad={(event) => {
          const image = event.currentTarget;
          if (image.naturalWidth && image.naturalHeight) {
            setAspectRatio(image.naturalWidth / image.naturalHeight);
          }
        }}
        className="h-full w-full object-contain"
      />
      {pins.map((pin) => (
        <motion.button
          key={pin.id}
          type="button"
          onPointerDown={(event) => handlePinPointerDown(pin.id, event)}
          onPointerMove={(event) => handlePinPointerMove(pin.id, event)}
          onPointerUp={(event) => handlePinPointerUp(pin.id, event)}
          onClick={(event) => {
            event.stopPropagation();
            if (!onPinMove) onPinClick?.(pin.id);
          }}
          className={cn(
            "absolute flex h-9 w-9 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full border-2 text-sm font-semibold shadow-soft",
            onPinMove ? "cursor-grab touch-none active:cursor-grabbing" : onPinClick ? "cursor-pointer" : "cursor-default",
            TONE_CLASS[pin.tone],
          )}
          style={{ left: `${pin.x}%`, top: `${pin.y}%` }}
          animate={
            pin.tone === "active"
              ? { scale: [1, 1.18, 1] }
              : { scale: 1 }
          }
          transition={pin.tone === "active" ? { duration: 1.4, repeat: Infinity, ease: "easeInOut" } : { duration: 0.15 }}
        >
          {pin.n}
        </motion.button>
      ))}
    </div>
  );
}
