import { useEffect, useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { useAuth } from "../../lib/auth";
import { useI18n } from "../../lib/i18n";
import splashArt from "../../assets/animations/sonalim-erp-splash.webp";
import { BrandLoader } from "./BrandLoader";

interface AppSplashProps {
  onFinished?: () => void;
}

/** A signed-out visitor is heading to the login: give them the brand intro. */
const INTRO_MS = 2300;
/** A refresh mid-work only needs a beat, long enough not to flash. */
const REFRESH_MIN_MS = 900;
const FONT_WAIT_CAP_MS = 1500;

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
            <Intro />
          )}
          <div className="sr-only">{t("app.startingUp")}</div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

/** The artwork is 1586 x 992; it carries the logo, wordmark, tagline and its own loading bar. */
const ART_RATIO = 1586 / 992;

function Intro() {
  return (
    <div className="relative h-full w-full overflow-hidden bg-[linear-gradient(135deg,#021938,#0b2c59)]">
      {/* Landscape: cover the viewport. Portrait: fit the width and letterbox on the matching navy. */}
      <div
        className="absolute left-1/2 top-1/2 h-[max(100vh,62.55vw)] w-[max(100vw,159.9vh)] -translate-x-1/2 -translate-y-1/2 portrait:h-auto portrait:w-screen"
        style={{ aspectRatio: `${ART_RATIO}` }}
      >
        <motion.img
          src={splashArt}
          alt=""
          draggable={false}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.8, ease: "easeOut" }}
          className="block h-full w-full object-cover portrait:[mask-image:linear-gradient(to_bottom,transparent,black_10%,black_90%,transparent)]"
        />
      </div>
    </div>
  );
}
