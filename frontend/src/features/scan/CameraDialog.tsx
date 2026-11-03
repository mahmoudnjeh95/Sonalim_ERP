import { useEffect, useRef, useState } from "react";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import { AnimatePresence, motion } from "framer-motion";
import { Camera, Check, X } from "lucide-react";
import { Button } from "../../components/ui/button";
import { useLabel } from "../production/shift/shiftText";
import { S } from "./scanText";

// A short burst of fading noise: the "click" a camera makes, so a shot is never silent.
function playShutter(context: AudioContext) {
  const length = Math.round(context.sampleRate * 0.08);
  const buffer = context.createBuffer(1, length, context.sampleRate);
  const data = buffer.getChannelData(0);
  for (let i = 0; i < length; i++) data[i] = (Math.random() * 2 - 1) * (1 - i / length) ** 3;
  const source = context.createBufferSource();
  const gain = context.createGain();
  gain.gain.value = 0.5;
  source.buffer = buffer;
  source.connect(gain).connect(context.destination);
  source.start();
}

/** A full-screen live camera: take the fiches one after the other, then send them together. */
export function CameraDialog({
  open, onOpenChange, onShots, onFallback,
}: { open: boolean; onOpenChange: (open: boolean) => void; onShots: (files: File[]) => void; onFallback: () => void }) {
  const label = useLabel();
  const rootRef = useRef<HTMLDivElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const audioRef = useRef<AudioContext | null>(null);
  const [ready, setReady] = useState(false);
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [flash, setFlash] = useState(0);
  const [shots, setShots] = useState<{ file: File; url: string }[]>([]);

  useEffect(() => {
    if (!open) return;
    let stream: MediaStream | null = null;
    let cancelled = false;
    if (!navigator.mediaDevices?.getUserMedia) {
      setFailed(true);
    } else {
      navigator.mediaDevices
        .getUserMedia({ video: { facingMode: { ideal: "environment" }, width: { ideal: 4096 } }, audio: false })
        .then((media) => {
          if (cancelled) {
            media.getTracks().forEach((track) => track.stop());
            return;
          }
          stream = media;
          if (videoRef.current) {
            videoRef.current.srcObject = media;
            void videoRef.current.play();
          }
          setReady(true);
        })
        .catch(() => setFailed(true));
    }
    return () => {
      cancelled = true;
      stream?.getTracks().forEach((track) => track.stop());
      if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
      void audioRef.current?.close();
      audioRef.current = null;
      setReady(false);
      setFailed(false);
      setBusy(false);
      setShots((current) => {
        current.forEach((shot) => URL.revokeObjectURL(shot.url));
        return [];
      });
    };
  }, [open]);

  const snap = () => {
    const video = videoRef.current;
    if (!video || !video.videoWidth || busy) return;
    // Every shot says so three ways: a white flash, a shutter click and (on phones) a short buzz.
    setFlash((n) => n + 1);
    navigator.vibrate?.(40);
    try {
      audioRef.current ??= new AudioContext();
      playShutter(audioRef.current);
    } catch {
      // No audio on this device: the flash and the new thumbnail still show the shot.
    }
    setBusy(true);
    const canvas = document.createElement("canvas");
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    canvas.getContext("2d")!.drawImage(video, 0, 0);
    canvas.toBlob((blob) => {
      setBusy(false);
      if (!blob) return;
      setShots((current) => [
        ...current,
        { file: new File([blob], `camera-${current.length + 1}.jpg`, { type: "image/jpeg" }), url: URL.createObjectURL(blob) },
      ]);
    }, "image/jpeg", 0.95);
  };
  const drop = (index: number) =>
    setShots((current) => {
      URL.revokeObjectURL(current[index].url);
      return current.filter((_, i) => i !== index);
    });
  const finish = () => {
    onShots(shots.map((s) => s.file));
    onOpenChange(false);
  };

  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Content
          ref={rootRef}
          aria-describedby={undefined}
          // Hides the browser's bars where the platform allows it (Android); the view fills the screen regardless.
          onOpenAutoFocus={() => {
            if (!document.fullscreenElement) rootRef.current?.requestFullscreen?.().catch(() => {});
          }}
          className="fixed inset-0 z-50 flex h-[100dvh] w-screen flex-col bg-black text-white"
        >
          <div className="flex items-center gap-3 px-4 pb-3 pt-[max(0.75rem,env(safe-area-inset-top))]">
            <DialogPrimitive.Title className="min-w-0 flex-1 truncate text-base font-semibold">{label(S.camera)}</DialogPrimitive.Title>
            <DialogPrimitive.Close
              aria-label={label(S.closeCamera)}
              className="rounded-full bg-white/15 p-2 transition-colors hover:bg-white/25 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white"
            >
              <X className="h-5 w-5" />
            </DialogPrimitive.Close>
          </div>

          {failed ? (
            <div className="flex flex-1 flex-col items-center justify-center gap-4 px-6 text-center">
              <p className="max-w-sm text-sm text-white/80">{label(S.cameraUnavailable)}</p>
              <Button variant="outline" onClick={() => { onOpenChange(false); onFallback(); }}>
                <Camera className="h-4 w-4" />
                {label(S.phoneCamera)}
              </Button>
            </div>
          ) : (
            <>
              <div className="relative min-h-0 flex-1 overflow-hidden">
                <video ref={videoRef} playsInline muted className="absolute inset-0 h-full w-full object-contain" />
                <AnimatePresence>
                  {flash > 0 && (
                    <motion.div
                      key={flash}
                      className="pointer-events-none absolute inset-0 bg-white"
                      initial={{ opacity: 0.9 }}
                      animate={{ opacity: 0 }}
                      transition={{ duration: 0.45, ease: "easeOut" }}
                    />
                  )}
                </AnimatePresence>
                <div role="status" className="pointer-events-none absolute inset-0 grid place-items-center">
                  <AnimatePresence>
                    {flash > 0 && (
                      <motion.div
                        key={flash}
                        className="flex items-center gap-2 rounded-full bg-black/70 px-4 py-2 text-sm font-medium"
                        initial={{ opacity: 0, scale: 0.8 }}
                        animate={{ opacity: [0, 1, 1, 0], scale: [0.8, 1, 1, 1] }}
                        transition={{ duration: 1.2, times: [0, 0.15, 0.75, 1] }}
                      >
                        <Check className="h-4 w-4 text-success" />
                        {`${label(S.photoTaken)} · ${shots.length + (busy ? 1 : 0)}`}
                      </motion.div>
                    )}
                  </AnimatePresence>
                </div>
              </div>

              <div className="space-y-3 px-4 pb-[max(1rem,env(safe-area-inset-bottom))] pt-3">
                {shots.length > 0 && (
                  <div className="flex gap-2 overflow-x-auto">
                    <AnimatePresence initial={false}>
                      {shots.map((shot, index) => (
                        <motion.div
                          key={shot.url}
                          className="relative shrink-0"
                          initial={{ opacity: 0, scale: 0.6 }}
                          animate={{ opacity: 1, scale: 1 }}
                          exit={{ opacity: 0, scale: 0.6 }}
                        >
                          <img src={shot.url} alt={label(S.photo)} className="h-16 rounded border border-white/40" />
                          <button
                            type="button"
                            onClick={() => drop(index)}
                            aria-label={label(S.remove)}
                            className="absolute right-0.5 top-0.5 rounded-full bg-black/70 p-1"
                          >
                            <X className="h-3 w-3" />
                          </button>
                        </motion.div>
                      ))}
                    </AnimatePresence>
                  </div>
                )}
                <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-3">
                  <span />
                  <button
                    type="button"
                    onClick={snap}
                    disabled={!ready || busy}
                    aria-label={label(S.snap)}
                    className="grid h-[4.5rem] w-[4.5rem] place-items-center rounded-full border-4 border-white transition-opacity disabled:opacity-40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white focus-visible:ring-offset-2 focus-visible:ring-offset-black"
                  >
                    <span className="h-14 w-14 rounded-full bg-white transition-transform active:scale-90" />
                  </button>
                  <div className="flex justify-end">
                    <Button disabled={shots.length === 0} onClick={finish}>
                      <Check className="h-4 w-4" />
                      {`${label(S.done)}${shots.length ? ` (${shots.length})` : ""}`}
                    </Button>
                  </div>
                </div>
              </div>
            </>
          )}
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}
