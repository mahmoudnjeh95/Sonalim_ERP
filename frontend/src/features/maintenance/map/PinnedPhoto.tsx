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
  /** Fired on every pointer-move tick while a pin is being dragged — live visual feedback only, not a save point. */
  onPinMove?: (id: string, x: number, y: number) => void;
  /** Fired once, on pointerup/pointercancel, with the final dropped position — this is what the editor should PATCH. */
  onPinMoveEnd?: (id: string, x: number, y: number) => void;
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
 * - F3 passes `onPick` (tap-to-place a new point) and `onPinMoveEnd` (drag to
 *   reposition an existing one, saved once on drop) — editing mode. `onPinMove`
 *   is optional live feedback only: this component already tracks the dragged
 *   pin's own position internally and renders it smoothly without the caller
 *   re-rendering `pins` on every tick, so most callers need only
 *   `onPinMoveEnd`. Neither callback should be read as "save this now" except
 *   `onPinMoveEnd`, which fires exactly once per drag (pointerup/pointercancel).
 * - F4/F5 render read-only pins (no `onPick`/`onPinMove`/`onPinMoveEnd`) and
 *   use `onPinClick` to open a point's detail/entry form.
 *
 * The image is `object-contain` inside a relative box matched to the image's
 * own aspect ratio (via a loaded-size measurement), so percent coordinates
 * always land on the photo itself, never in the surrounding letterboxing.
 */
/**
 * How far (in screen pixels) a pressed pin must travel before it is a drag: a
 * finger always jitters a little on a tap, and that tap must open the point,
 * not move it. The usual touch slop.
 */
const DRAG_SLOP_PX = 6;

export function isDrag(start: { x: number; y: number }, current: { x: number; y: number }): boolean {
  return Math.hypot(current.x - start.x, current.y - start.y) > DRAG_SLOP_PX;
}

export function PinnedPhoto({ src, pins, onPick, onPinClick, onPinMove, onPinMoveEnd, className }: PinnedPhotoProps) {
  const boxRef = useRef<HTMLDivElement>(null);
  const [aspectRatio, setAspectRatio] = useState<number | null>(null);
  const [draggingId, setDraggingId] = useState<string | null>(null);
  // The dragged pin's own live position while the drag is in progress, so it
  // tracks the pointer smoothly even if the caller doesn't re-render `pins`
  // on every `onPinMove` tick (it isn't meant to — that callback is for live
  // feedback only; the caller PATCHes once, from `onPinMoveEnd`).
  const [livePosition, setLivePosition] = useState<{ x: number; y: number } | null>(null);
  const dragMoved = useRef(false);
  const dragStart = useRef<{ x: number; y: number } | null>(null);

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

  const canDrag = !!onPinMove || !!onPinMoveEnd;

  function handlePinPointerDown(pinId: string, event: ReactPointerEvent<HTMLButtonElement>) {
    if (!canDrag) return;
    event.stopPropagation();
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    dragMoved.current = false;
    dragStart.current = { x: event.clientX, y: event.clientY };
    setLivePosition(null);
    setDraggingId(pinId);
  }

  function handlePinPointerMove(pinId: string, event: ReactPointerEvent<HTMLButtonElement>) {
    if (draggingId !== pinId || !canDrag) return;
    if (!dragMoved.current && dragStart.current && !isDrag(dragStart.current, { x: event.clientX, y: event.clientY })) return;
    const point = percentFromEvent(event.clientX, event.clientY);
    if (!point) return;
    dragMoved.current = true;
    setLivePosition(point);
    onPinMove?.(pinId, point.x, point.y);
  }

  function endDrag(pinId: string, event: ReactPointerEvent<HTMLButtonElement>) {
    if (draggingId !== pinId) return;
    event.currentTarget.releasePointerCapture(event.pointerId);
    setDraggingId(null);
    if (dragMoved.current) {
      // The final dropped position — this is the single save point. Recompute
      // from the event rather than trusting state timing, same clamp as every
      // other position read.
      const point = percentFromEvent(event.clientX, event.clientY) ?? livePosition;
      if (point) onPinMoveEnd?.(pinId, point.x, point.y);
    } else {
      // A tap that never moved is a click, not a drag-drop.
      onPinClick?.(pinId);
    }
    setLivePosition(null);
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
      {pins.map((pin) => {
        const isDragging = draggingId === pin.id;
        const position = isDragging && livePosition ? livePosition : { x: pin.x, y: pin.y };
        return (
          <motion.button
            key={pin.id}
            type="button"
            onPointerDown={(event) => handlePinPointerDown(pin.id, event)}
            onPointerMove={(event) => handlePinPointerMove(pin.id, event)}
            onPointerUp={(event) => endDrag(pin.id, event)}
            onPointerCancel={(event) => endDrag(pin.id, event)}
            onClick={(event) => {
              event.stopPropagation();
              if (!canDrag) onPinClick?.(pin.id);
            }}
            className={cn(
              // `before:` widens the tap area to 44 px around the 36 px disc.
              "absolute flex h-9 w-9 items-center justify-center rounded-full border-2 text-sm font-semibold shadow-soft before:absolute before:-inset-1 before:rounded-full before:content-['']",
              canDrag ? "cursor-grab touch-none active:cursor-grabbing" : onPinClick ? "cursor-pointer" : "cursor-default",
              TONE_CLASS[pin.tone],
            )}
            // Centred on its point through Framer's own x/y: a Tailwind `-translate-*` class is
            // overwritten by the inline transform Framer writes for the `scale` animation.
            style={{ left: `${position.x}%`, top: `${position.y}%`, x: "-50%", y: "-50%" }}
            animate={
              pin.tone === "active"
                ? { scale: [1, 1.18, 1] }
                : { scale: 1 }
            }
            transition={pin.tone === "active" ? { duration: 1.4, repeat: Infinity, ease: "easeInOut" } : { duration: 0.15 }}
          >
            {pin.n}
          </motion.button>
        );
      })}
    </div>
  );
}
