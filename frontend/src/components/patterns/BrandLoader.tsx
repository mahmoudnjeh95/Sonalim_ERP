import { motion, useReducedMotion } from "framer-motion";
import { useI18n } from "../../lib/i18n";
import { cn } from "../../lib/utils";

type Tone = "dark" | "light";

interface BrandWordmarkProps {
  /** "dark" sits on the navy brand background; "light" on the app's white pages. */
  tone?: Tone;
  /** Font size of the wordmark in px. The ERP slide distance scales with it. */
  size?: number;
  /** Loop the loading motion (SONALIM pulse + ERP slide). Off = static wordmark with an entrance only. */
  animate?: boolean;
  className?: string;
}

const EASE = [0.22, 1, 0.36, 1] as const;

/**
 * The "SONALIM ERP" wordmark. While `animate` is on, SONALIM breathes
 * (a soft opacity pulse — the "blink") and ERP slides right and back as the
 * loading motion, so the brand itself is the progress indicator.
 */
export function BrandWordmark({ tone = "dark", size = 40, animate = false, className }: BrandWordmarkProps) {
  const reduceMotion = useReducedMotion();
  const loop = animate && !reduceMotion;
  const slide = Math.round(size * 0.35);

  return (
    <div
      aria-hidden="true"
      className={cn("flex select-none items-baseline font-bold tracking-[0.08em]", className)}
      style={{ fontSize: size, lineHeight: 1 }}
    >
      <motion.span
        initial={{ opacity: 0, y: size * 0.25 }}
        animate={loop ? { opacity: [1, 0.45, 1], y: 0 } : { opacity: 1, y: 0 }}
        transition={
          loop
            ? { opacity: { duration: 1.6, repeat: Infinity, ease: "easeInOut" }, y: { duration: 0.5, ease: EASE } }
            : { duration: 0.5, ease: EASE }
        }
        className={tone === "dark" ? "text-white" : "text-[#123B6D]"}
      >
        SONALIM
      </motion.span>
      <motion.span
        initial={{ opacity: 0, x: -slide }}
        animate={loop ? { opacity: 1, x: [0, slide, 0] } : { opacity: 1, x: 0 }}
        transition={
          loop
            ? { x: { duration: 1.6, repeat: Infinity, ease: "easeInOut" }, opacity: { duration: 0.4, delay: 0.15 } }
            : { duration: 0.5, delay: 0.15, ease: EASE }
        }
        className="ml-[0.3em] text-[#F5A900]"
        style={{ textShadow: tone === "dark" ? "0 0 24px rgba(245,169,0,0.45)" : undefined }}
      >
        ERP
      </motion.span>
    </div>
  );
}

interface BrandLoaderProps {
  tone?: Tone;
  size?: number;
  label?: string;
  /** Fill the viewport (used as the refresh splash). Otherwise fills its container. */
  fullScreen?: boolean;
  className?: string;
}

/**
 * Wordmark + a thin sweeping gold line + a caption. This is what the user
 * sees on a refresh while signed in, and while a lazy route chunk loads.
 */
export function BrandLoader({ tone = "dark", size = 40, label, fullScreen = false, className }: BrandLoaderProps) {
  const { t } = useI18n();
  const reduceMotion = useReducedMotion();
  const dark = tone === "dark";
  const trackWidth = Math.round(size * 5.2);

  return (
    <div
      role="status"
      aria-live="polite"
      className={cn(
        "flex flex-col items-center justify-center gap-5",
        fullScreen ? "fixed inset-0 z-[9999] bg-[#071F43]" : "min-h-[60vh]",
        className,
      )}
    >
      {dark && fullScreen && (
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_50%_45%,rgba(245,169,0,0.14),transparent_45%),linear-gradient(135deg,#071F43,#123B6D)]"
        />
      )}
      <div className="relative flex flex-col items-center gap-5">
        <BrandWordmark tone={tone} size={size} animate />
        <div
          className={cn("relative h-[3px] overflow-hidden rounded-full", dark ? "bg-white/10" : "bg-[#123B6D]/10")}
          style={{ width: trackWidth }}
        >
          <motion.div
            className="absolute inset-y-0 w-2/5 rounded-full bg-gradient-to-r from-[#F5A900] to-[#FFD45A]"
            initial={{ x: "-100%" }}
            animate={reduceMotion ? { x: "75%" } : { x: ["-100%", "250%"] }}
            transition={reduceMotion ? { duration: 0 } : { duration: 1.6, repeat: Infinity, ease: "easeInOut" }}
          />
        </div>
        <motion.span
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.4, delay: 0.2 }}
          className={cn(
            "text-xs font-medium uppercase tracking-[0.28em]",
            dark ? "text-slate-300/80" : "text-[#123B6D]/70",
          )}
        >
          {label ?? t("app.loading")}
        </motion.span>
      </div>
    </div>
  );
}
