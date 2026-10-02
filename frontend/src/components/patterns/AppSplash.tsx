import { useCallback, useEffect, useRef, useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { useAuth } from "../../lib/auth";
import { useI18n } from "../../lib/i18n";
import logoMark from "../../assets/icons/brand/logo-3d-mark-512.png";
import { BrandLoader, BrandWordmark } from "./BrandLoader";
import { brandFlags } from "./brand3d/devFlags";
import { stageStore, useStage } from "./brand3d/stageStore";
import { INTRO, introState, logoState } from "./brand3d/timeline";

interface AppSplashProps {
  onFinished?: () => void;
}

/** A refresh mid-work only needs a beat, long enough not to flash. */
const REFRESH_MIN_MS = 900;
const FONT_WAIT_CAP_MS = 1500;
/** How long the intro waits for the live 3D before it plays on the baked poster instead. */
const POSTER_WAIT_MS = 1500;

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
 * a session was restored: no session = the 3D welcome intro (about 4 s,
 * skippable) on the way to the login page, drawn by BrandStage under this
 * transparent overlay; session = the lightweight wordmark loader, dismissed as
 * soon as the fonts are in and a minimum beat has passed.
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
  const handOff = useCallback(() => setVisible(false), []);

  useEffect(() => {
    if (mode !== "refresh") return;
    let cancelled = false;
    const wait = new Promise<void>((resolve) =>
      window.setTimeout(resolve, REFRESH_MIN_MS),
    );
    Promise.all([wait, fontsReady()]).then(() => {
      if (!cancelled) setVisible(false);
    });
    return () => {
      cancelled = true;
    };
  }, [mode]);

  return (
    <AnimatePresence
      onExitComplete={() => {
        if (mode === "intro") stageStore.set({ introPhase: "done" });
        onFinished?.();
      }}
    >
      {visible && (
        <motion.div
          key="splash"
          initial={{ opacity: 1 }}
          exit={{ opacity: 0, scale: mode === "refresh" && !reduceMotion ? 1.02 : 1 }}
          transition={{ duration: 0.4, ease: "easeOut" }}
          className="fixed inset-0 z-[9999]"
        >
          {mode === "refresh" ? (
            <BrandLoader fullScreen size={44} />
          ) : (
            <IntroOverlay onHandoff={handOff} />
          )}
          <div className="sr-only">{t("app.startingUp")}</div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

/**
 * What the intro adds over the 3D: the wordmark and tagline on their beat, a
 * skip control, and the baked mark when the live 3D is not there. Click, tap
 * or any key skips.
 */
function IntroOverlay({ onHandoff }: { onHandoff: () => void }) {
  const { t } = useI18n();
  const ready = useStage((s) => s.ready);
  const started = useStage((s) => s.introStarted);
  const fallback = useStage((s) => s.fallback);
  const lockupRef = useRef<HTMLDivElement>(null);
  const markRef = useRef<HTMLImageElement>(null);
  const [wordmarkSize] = useState(() =>
    Math.round(Math.min(44, Math.max(24, window.innerWidth * 0.07))),
  );

  // No live 3D on this device (reduced motion, no WebGL): play the poster intro at once rather than after the wait.
  useEffect(() => {
    if (fallback) stageStore.startIntro();
  }, [fallback]);

  useEffect(() => {
    stageStore.set({ introPhase: "playing" });
    if (brandFlags.introAt !== null) {
      stageStore.freezeIntro(brandFlags.introAt);
      stageStore.startIntro();
    }
    // The live 3D starts the clock on its first frame; past this wait the intro runs on the poster.
    const posterTimer = window.setTimeout(() => stageStore.startIntro(), POSTER_WAIT_MS);
    let raf = 0;
    const tick = () => {
      const time = stageStore.introTime();
      if (lockupRef.current) lockupRef.current.style.opacity = String(introState(time).wordmark);
      if (markRef.current) markRef.current.style.opacity = String(logoState(time, 0).ring);
      if (brandFlags.introAt === null && stageStore.get().introStarted && time >= INTRO.handoff) {
        stageStore.set({ introPhase: "handoff" });
        onHandoff();
        return;
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    const skip = () => stageStore.skipIntro();
    window.addEventListener("keydown", skip);
    return () => {
      window.clearTimeout(posterTimer);
      cancelAnimationFrame(raf);
      window.removeEventListener("keydown", skip);
    };
  }, [onHandoff]);

  return (
    <div
      className="relative h-full w-full cursor-pointer select-none"
      onPointerDown={() => stageStore.skipIntro()}
    >
      {started && !ready && (
        <img
          ref={markRef}
          src={logoMark}
          alt=""
          draggable={false}
          style={{ opacity: 0 }}
          className="absolute left-1/2 top-1/2 h-[48vmin] w-[48vmin] -translate-x-1/2 -translate-y-1/2"
        />
      )}
      <div
        ref={lockupRef}
        style={{ opacity: 0, top: "calc(50% + 20vmin + 28px)" }}
        className="absolute inset-x-0 flex flex-col items-center gap-3 px-4 text-center"
      >
        <BrandWordmark tone="dark" size={wordmarkSize} />
        <p className="text-xs uppercase tracking-[0.35em] text-[#F5A900]/90">{t("login.tagline")}</p>
      </div>
      <button
        type="button"
        onClick={() => stageStore.skipIntro()}
        className="absolute bottom-[calc(1.5rem+env(safe-area-inset-bottom,0px))] right-6 rounded-full px-3 py-1.5 text-xs font-medium uppercase tracking-[0.2em] text-white/60 transition-colors hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#F5A900]/60"
      >
        {t("app.skipIntro")}
      </button>
    </div>
  );
}
