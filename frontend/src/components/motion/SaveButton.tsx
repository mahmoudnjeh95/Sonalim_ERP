import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Check, Loader2 } from "lucide-react";
import { Button, type ButtonProps } from "../ui/button";
import { cn } from "../../lib/utils";

const SAVED_FLASH_MS = 1400;

/** True for `SAVED_FLASH_MS` after each transition from pending to settled-success. */
export function useSavedFlash(pending: boolean, success: boolean) {
  const [justSaved, setJustSaved] = useState(false);
  const wasPending = useRef(pending);

  useEffect(() => {
    if (wasPending.current && !pending && success) {
      setJustSaved(true);
      const timer = setTimeout(() => setJustSaved(false), SAVED_FLASH_MS);
      wasPending.current = pending;
      return () => clearTimeout(timer);
    }
    wasPending.current = pending;
  }, [pending, success]);

  return justSaved;
}

interface SaveButtonProps extends Omit<ButtonProps, "children"> {
  pending: boolean;
  justSaved?: boolean;
  children: React.ReactNode;
  savedLabel: React.ReactNode;
}

/** Save/submit button that shows a spinner while pending and a brief check on success. */
export function SaveButton({ pending, justSaved = false, children, savedLabel, className, disabled, ...props }: SaveButtonProps) {
  return (
    <Button className={cn("relative overflow-hidden", className)} disabled={disabled || pending || justSaved} {...props}>
      <AnimatePresence mode="wait" initial={false}>
        {justSaved ? (
          <motion.span
            key="saved"
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.15 }}
            className="inline-flex items-center gap-1.5"
          >
            <Check className="h-4 w-4" />
            {savedLabel}
          </motion.span>
        ) : (
          <motion.span
            key="idle"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.15 }}
            className="inline-flex items-center gap-1.5"
          >
            {pending && <Loader2 className="h-4 w-4 animate-spin" />}
            {children}
          </motion.span>
        )}
      </AnimatePresence>
    </Button>
  );
}
