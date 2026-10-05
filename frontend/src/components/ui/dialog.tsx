import * as React from "react";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import { cn } from "../../lib/utils";

export const Dialog = DialogPrimitive.Root;
export const DialogTrigger = DialogPrimitive.Trigger;

/**
 * Moves a caller's plain width cap (`max-w-2xl`, `w-[48rem]`, …) to its `sm:`
 * variant, so it applies to the desktop dialog but not to the phone sheet.
 *
 * 58 call sites set a width this way. They are unprefixed utilities, so without
 * this tailwind-merge would drop the sheet's own `max-w-none` and leave a
 * narrow, centred box on a phone. Rewriting here keeps every one of those call
 * sites unchanged and their desktop width exactly as it was.
 */
export function widthCapsToDesktop(className: string | undefined): string | undefined {
  if (!className) return className;
  return className
    .split(/\s+/)
    .map((token) => (/^(max-w-|w-)(?!full$|auto$)/.test(token) ? `sm:${token}` : token))
    .join(" ");
}

export function DialogContent({
  className,
  children,
  ...props
}: React.ComponentPropsWithoutRef<typeof DialogPrimitive.Content>) {
  const desktopWidthClassName = widthCapsToDesktop(className);
  return (
    <DialogPrimitive.Portal>
      <DialogPrimitive.Overlay
        className={cn(
          "fixed inset-0 z-50 bg-foreground/25 backdrop-blur-sm",
          "data-[state=open]:animate-in data-[state=open]:fade-in-0",
          "data-[state=closed]:animate-out data-[state=closed]:fade-out-0",
        )}
      />
      <DialogPrimitive.Content
        className={cn(
          "fixed z-50 flex w-full flex-col border border-border bg-background shadow-raised",
          // Phone: a bottom sheet pinned to the bottom edge, full width, with the
          // rounding only on top. Callers override the desktop width with
          // `max-w-*` (58 of them do); those are unprefixed utilities, so the
          // sheet's width has to be unprefixed too or tailwind-merge would let a
          // caller's `max-w-2xl` win and leave a narrow box on a phone. Hence
          // `max-w-none` here and every desktop value behind `sm:`.
          "inset-x-0 bottom-0 max-w-none rounded-t-xl p-5 pb-[max(1.25rem,env(safe-area-inset-bottom))]",
          // Desktop (>=640px): the centred box exactly as before.
          "sm:inset-x-auto sm:bottom-auto sm:left-1/2 sm:top-1/2 sm:max-w-md sm:-translate-x-1/2 sm:-translate-y-1/2 sm:rounded-xl sm:p-6 sm:pb-6",
          // Never taller than the screen. Without this a long form runs
          // off both ends of the viewport and takes its own title and
          // submit button with it.
          "max-h-[85dvh] overflow-y-auto overscroll-contain sm:max-h-[calc(100dvh-3rem)]",
          "data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:slide-in-from-bottom-4",
          "data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=closed]:slide-out-to-bottom-4",
          "sm:data-[state=open]:zoom-in-95 sm:data-[state=open]:slide-in-from-top-2 sm:data-[state=open]:slide-in-from-bottom-0",
          "sm:data-[state=closed]:zoom-out-95 sm:data-[state=closed]:slide-out-to-bottom-0",
          "duration-200",
          desktopWidthClassName,
        )}
        {...props}
      >
        {children}
        <DialogPrimitive.Close
          className="absolute right-4 top-4 rounded-md p-1 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          aria-label="Close"
        >
          ×
        </DialogPrimitive.Close>
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  );
}

export function DialogHeader({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("mb-4 space-y-1", className)} {...props} />;
}

export function DialogTitle({
  className,
  ...props
}: React.ComponentPropsWithoutRef<typeof DialogPrimitive.Title>) {
  return <DialogPrimitive.Title className={cn("text-base font-semibold", className)} {...props} />;
}

export function DialogDescription({
  className,
  ...props
}: React.ComponentPropsWithoutRef<typeof DialogPrimitive.Description>) {
  return <DialogPrimitive.Description className={cn("text-sm text-muted-foreground", className)} {...props} />;
}
