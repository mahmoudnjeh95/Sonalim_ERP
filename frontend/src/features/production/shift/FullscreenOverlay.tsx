import type { ReactNode } from "react";
import { Minimize2 } from "lucide-react";
import { Button } from "../../../components/ui/button";
import { DialogContent, DialogTitle, Dialog as DialogRoot } from "../../../components/ui/dialog";
import { T, useLabel } from "./shiftText";

/**
 * A section, or the whole fiche, taking the entire browser tab: the paper fiche is a big
 * sheet and the plant's screens are narrow, so filling it a few centimetres tall at a time
 * is the actual complaint. Same exit gesture (button, Esc, the dialog's own close) everywhere
 * it's used.
 */
export function FullscreenOverlay({
  open,
  onOpenChange,
  title,
  icon,
  children,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  icon?: ReactNode;
  children: ReactNode;
}) {
  const label = useLabel();
  return (
    <DialogRoot open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="left-0 top-0 h-[100dvh] w-screen max-w-none translate-x-0 translate-y-0 rounded-none border-0 p-0 max-h-[100dvh]"
        onOpenAutoFocus={(e) => e.preventDefault()}
      >
        <DialogTitle className="sr-only">{title}</DialogTitle>
        <div className="flex items-center gap-3 border-b border-border bg-muted/50 px-4 py-3">
          {icon && (
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
              {icon}
            </span>
          )}
          <span className="min-w-0 flex-1 truncate text-sm font-semibold tracking-tight">{title}</span>
          <Button size="sm" variant="outline" onClick={() => onOpenChange(false)} className="h-7 gap-1.5 px-2.5 text-xs">
            <Minimize2 className="h-3.5 w-3.5" />
            {label(T.exitKiosk)}
          </Button>
        </div>
        <div className="h-[calc(100dvh-3.25rem)] overflow-y-auto overscroll-contain">{children}</div>
      </DialogContent>
    </DialogRoot>
  );
}
