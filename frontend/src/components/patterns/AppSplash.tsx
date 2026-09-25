import { useEffect, useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { useAuth } from "../../lib/auth";
import { useI18n } from "../../lib/i18n";
import LogoMark from "../../assets/animations/logo-mark.svg?react";
import { BrandLoader, BrandWordmark } from "./BrandLoader";

interface AppSplashProps {
  onFinished?: () => void;
}

/** A signed-out visitor is heading to the login: give them the brand intro. */
const INTRO_MS = 2300;
/** A refresh mid-work only needs a beat, long enough not to flash. */
const REFRESH_MIN_MS = 900;
const FONT_WAIT_CAP_MS = 1500;

const EASE = [0.22, 1, 0.36, 1] as const;

/** Wait for the web font so the wordmark doesn't swap mid-animation, but never let a slow font host hold the splash. */
function fontsReady(): Promise<unknown> {
  const fonts =
    typeof document !== "undefined" && "fonts" in document
      ? document.fonts.ready
      : Promise.resolve();
  const cap = new Promise<void>((resolve) =>
    window.setTimeout(resolve, FONT_WAIT_CAP_MS),
  );
  return Promise.race([fonts, cap]);
}

/**
 * Full-screen cover shown while the app boots. Two moods, picked from whether
 * a session was restored: no session = the cinematic intro on the way to the
 * login page; session = the lightweight wordmark loader, dismissed as soon as
 * the fonts are in and a minimum beat has passed rather than on a long timer.
 */
export function AppSplash({ onFinished }: AppSplashProps) {
  const { t } = useI18n();
  const { session } = useAuth();
  const reduceMotion = useReducedMotion();
  // Decided once, at mount: the splash should not flip mood when the user logs in under it.
  const [mode] = useState<"intro" | "refresh">(() =>
    session ? "refresh" : "intro",
  );
  const [visible, setVisible] = useState(true);

  useEffect(() => {
    let cancelled = false;
    const wait = new Promise<void>((resolve) =>
      window.setTimeout(resolve, mode === "intro" ? INTRO_MS : REFRESH_MIN_MS),
    );
    Promise.all([wait, fontsReady()]).then(() => {
      if (!cancelled) setVisible(false);
    });
    return () => {
      cancelled = true;
    };
  }, [mode]);

  return (
    <AnimatePresence onExitComplete={onFinished}>
      {visible && (
        <motion.div
          key="splash"
          initial={{ opacity: 1 }}
          exit={{ opacity: 0, scale: reduceMotion ? 1 : 1.02 }}
          transition={{ duration: 0.4, ease: "easeOut" }}
          className="fixed inset-0 z-[9999]"
        >
          {mode === "refresh" ? (
            <BrandLoader fullScreen size={44} />
          ) : (
            <Intro reduceMotion={!!reduceMotion} />
          )}
          <div className="sr-only">{t("app.startingUp")}</div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

function Intro({ reduceMotion }: { reduceMotion: boolean }) {
  return (
    <div className="relative flex h-full w-full flex-col items-center justify-center overflow-hidden bg-[#071F43] text-white">
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_50%_40%,rgba(245,169,0,0.16),transparent_42%),radial-gradient(circle_at_85%_90%,rgba(255,255,255,0.08),transparent_35%),linear-gradient(135deg,#071F43,#123B6D)]"
      />
      {/* Slow gold sweep across the whole screen, once. */}
      {!reduceMotion && (
        <motion.div
          aria-hidden="true"
          className="pointer-events-none absolute inset-y-0 w-1/3 bg-gradient-to-r from-transparent via-[#F5A900]/10 to-transparent"
          initial={{ x: "-120%" }}
          animate={{ x: "420%" }}
          transition={{ duration: 1.8, delay: 0.4, ease: "easeInOut" }}
        />
      )}

      {/* Own layer: the absolute background above would otherwise paint over in-flow content. */}
      <div className="relative z-10 flex flex-col items-center">
        <motion.div
          initial={{ opacity: 0, scale: 0.7, y: 12 }}
          animate={{ opacity: 1, scale: 1, y: 0 }}
          transition={{ duration: 0.7, ease: EASE }}
          className="relative mb-7 flex h-28 w-28 items-center justify-center rounded-[28px] border border-white/15 bg-white/[0.06] shadow-[0_30px_80px_rgba(0,0,0,0.35)] backdrop-blur-sm"
        >
          <motion.div
            aria-hidden="true"
            className="absolute inset-[-14px] rounded-full bg-[#F5A900]/20 blur-2xl"
            animate={
              reduceMotion
                ? undefined
                : { opacity: [0.4, 0.9, 0.4], scale: [0.95, 1.05, 0.95] }
            }
            transition={{ duration: 2.2, repeat: Infinity, ease: "easeInOut" }}
          />
          <LogoMark className="relative h-20 w-20 text-[#F5A900]" />
        </motion.div>

        <motion.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, delay: 0.35, ease: EASE }}
        >
          <BrandWordmark tone="dark" size={56} />
        </motion.div>

        <motion.p
          initial={{ opacity: 0, letterSpacing: "0.2em" }}
          animate={{ opacity: 1, letterSpacing: "0.38em" }}
          transition={{ duration: 0.8, delay: 0.85, ease: "easeOut" }}
          className="mt-5 text-[11px] font-medium uppercase text-[#D9E6F5]/80 sm:text-xs"
        >
          Production • Qualité • Performance
        </motion.p>

        <div className="mt-10 h-[3px] w-56 overflow-hidden rounded-full bg-white/10">
          <motion.div
            className="h-full rounded-full bg-gradient-to-r from-[#F5A900] to-[#FFD45A]"
            initial={{ width: reduceMotion ? "100%" : "0%" }}
            animate={{ width: "100%" }}
            transition={{
              duration: (INTRO_MS - 500) / 1000,
              delay: 0.5,
              ease: [0.2, 0.8, 0.2, 1],
            }}
          />
        </div>
      </div>
    </div>
  );
}
