import { useState } from "react";
import { Check, ZoomIn } from "lucide-react";
import { cn } from "../../lib/utils";
import { Button } from "../../components/ui/button";
import { Card, CardContent } from "../../components/ui/card";
import { Skeleton } from "../../components/ui/skeleton";
import { useLabel } from "../production/shift/shiftText";
import { usePageImage, useUpright } from "./PageImage";
import type { ScanPage, SourceEntry } from "./scanApi";
import { S } from "./scanText";

export function PhotoViewer({
  page, source, flagged, onConfirm,
}: { page: ScanPage | undefined; source: SourceEntry | undefined; flagged: boolean; onConfirm: () => void }) {
  const label = useLabel();
  if (!page) {
    return (
      <Card>
        <CardContent className="py-10 text-center text-sm text-muted-foreground">{label(S.noSource)}</CardContent>
      </Card>
    );
  }
  return <Viewer page={page} source={source} flagged={flagged} onConfirm={onConfirm} />;
}

function Viewer({ page, source, flagged, onConfirm }: { page: ScanPage; source: SourceEntry | undefined; flagged: boolean; onConfirm: () => void }) {
  const label = useLabel();
  const image = usePageImage(page.id);
  const src = useUpright(image.data, page.rotation);
  const [zoomed, setZoomed] = useState(true);
  const box = source?.box;
  const origin = box ? `${((box[0] + box[2]) / 2) * 100}% ${((box[1] + box[3]) / 2) * 100}%` : "50% 50%";
  return (
    <Card>
      <CardContent className="space-y-2 py-3">
        <div className="relative overflow-hidden rounded-md border border-border bg-muted">
          {src ? (
            <div className="relative transition-transform duration-300" style={{ transform: zoomed && box ? "scale(2.5)" : "none", transformOrigin: origin }}>
              <img src={src} alt={label(S.photo)} className="block w-full" />
              {box && (
                <div
                  className="absolute rounded-sm border-2 border-warning bg-warning/20"
                  style={{ left: `${box[0] * 100}%`, top: `${box[1] * 100}%`, width: `${(box[2] - box[0]) * 100}%`, height: `${(box[3] - box[1]) * 100}%` }}
                />
              )}
            </div>
          ) : (
            <Skeleton className="h-72 w-full" />
          )}
        </div>
        {source && (
          <p className="text-sm">
            <span className="text-muted-foreground">{label(S.readAs)} </span>
            <span className="font-medium">{source.text}</span>
          </p>
        )}
        <div className="flex gap-2">
          <Button size="sm" variant="outline" onClick={() => setZoomed((z) => !z)} disabled={!box}>
            <ZoomIn className="h-3.5 w-3.5" />
            {label(S.zoom)}
          </Button>
          {flagged && (
            <Button size="sm" className={cn("ml-auto")} onClick={onConfirm}>
              <Check className="h-3.5 w-3.5" />
              {label(S.valueIsRight)}
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
