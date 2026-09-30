import { useEffect, useRef, useState } from "react";
import { Camera, X } from "lucide-react";
import { Button } from "../../components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "../../components/ui/dialog";
import { useLabel } from "../production/shift/shiftText";
import { S } from "./scanText";

/** A live camera view: take the fiches one after the other, then send them together. */
export function CameraDialog({
  open, onOpenChange, onShots, onFallback,
}: { open: boolean; onOpenChange: (open: boolean) => void; onShots: (files: File[]) => void; onFallback: () => void }) {
  const label = useLabel();
  const videoRef = useRef<HTMLVideoElement>(null);
  const [ready, setReady] = useState(false);
  const [failed, setFailed] = useState(false);
  const [shots, setShots] = useState<{ file: File; url: string }[]>([]);

  useEffect(() => {
    if (!open) return;
    let stream: MediaStream | null = null;
    let cancelled = false;
    if (!navigator.mediaDevices?.getUserMedia) {
      setFailed(true);
      return;
    }
    navigator.mediaDevices
      .getUserMedia({ video: { facingMode: { ideal: "environment" }, width: { ideal: 2400 } }, audio: false })
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
    return () => {
      cancelled = true;
      stream?.getTracks().forEach((track) => track.stop());
      setReady(false);
      setFailed(false);
      setShots((current) => {
        current.forEach((shot) => URL.revokeObjectURL(shot.url));
        return [];
      });
    };
  }, [open]);

  const snap = () => {
    const video = videoRef.current;
    if (!video || !video.videoWidth) return;
    const canvas = document.createElement("canvas");
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    canvas.getContext("2d")!.drawImage(video, 0, 0);
    canvas.toBlob((blob) => {
      if (!blob) return;
      setShots((current) => [
        ...current,
        { file: new File([blob], `camera-${current.length + 1}.jpg`, { type: "image/jpeg" }), url: URL.createObjectURL(blob) },
      ]);
    }, "image/jpeg", 0.9);
  };
  const drop = (index: number) =>
    setShots((current) => {
      URL.revokeObjectURL(current[index].url);
      return current.filter((_, i) => i !== index);
    });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle>{label(S.camera)}</DialogTitle>
        </DialogHeader>
        {failed ? (
          <div className="space-y-3">
            <p className="text-sm text-warning">{label(S.cameraUnavailable)}</p>
            <Button variant="outline" onClick={() => { onOpenChange(false); onFallback(); }}>
              <Camera className="h-4 w-4" />
              {label(S.phoneCamera)}
            </Button>
          </div>
        ) : (
          <div className="space-y-3">
            <video ref={videoRef} playsInline muted className="max-h-[60vh] w-full rounded-md bg-black object-contain" />
            <div className="flex flex-wrap items-center gap-2">
              <Button onClick={snap} disabled={!ready}>
                <Camera className="h-4 w-4" />
                {label(S.snap)}
              </Button>
              <span className="text-sm text-muted-foreground">{`${shots.length} ${label(S.shotsTaken)}`}</span>
              <Button className="ml-auto" variant="outline" disabled={shots.length === 0} onClick={() => { onShots(shots.map((s) => s.file)); onOpenChange(false); }}>
                {label(S.useShots)}
              </Button>
            </div>
            {shots.length > 0 && (
              <div className="flex gap-2 overflow-x-auto">
                {shots.map((shot, index) => (
                  <div key={shot.url} className="relative shrink-0">
                    <img src={shot.url} alt={label(S.photo)} className="h-20 rounded border border-border" />
                    <button
                      type="button"
                      onClick={() => drop(index)}
                      aria-label={label(S.remove)}
                      className="absolute right-0.5 top-0.5 rounded bg-background/80 p-0.5"
                    >
                      <X className="h-3 w-3" />
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
