import type { ReactNode } from "react";
import { useEffect, useRef, useState } from "react";
import { useLocation } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import { useIsFetching } from "@tanstack/react-query";
import { Menu } from "lucide-react";
import { Sidebar } from "./Sidebar";
import { AppLoader } from "../components/patterns/AppLoader";
import { useI18n } from "../lib/i18n";
import { useIsMobile } from "../lib/useIsMobile";
import { NotificationBell } from "../features/notifications/NotificationBell";
import logoTile64 from "../assets/icons/brand/logo-3d-64.png";
import logoTile96 from "../assets/icons/brand/logo-3d-96.png";

// The loader never flashes for less than this, and the page needs this long to
// mount its queries after the outgoing route finishes its exit animation.
const ROUTE_LOADER_MIN_MS = 500;
// A request that hangs must not leave the page blurred behind the loader for good.
const ROUTE_LOADER_MAX_MS = 15_000;

export function AppLayout({ children }: { children: ReactNode }) {
  const location = useLocation();
  const { t } = useI18n();
  const previousPathRef = useRef(location.pathname);
  const mainRef = useRef<HTMLElement>(null);
  const [showRouteLoader, setShowRouteLoader] = useState(false);
  const [minTimeElapsed, setMinTimeElapsed] = useState(true);
  const isMobile = useIsMobile();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const menuButtonRef = useRef<HTMLButtonElement>(null);
  // Reads with no data yet: a page opened for the first time. A background
  // refetch of cached data is not a reason to cover a page that is already usable.
  const firstReadsInFlight = useIsFetching({ predicate: (query) => query.state.status === "pending" });

  useEffect(() => {
    const previousPath = previousPathRef.current;
    const currentPath = location.pathname;
    const previousTopLevel = previousPath.split("/")[1] ?? "";
    const currentTopLevel = currentPath.split("/")[1] ?? "";
    const shouldShowLoader = previousTopLevel !== currentTopLevel || previousPath === "/" || currentPath === "/";

    if (!shouldShowLoader) {
      previousPathRef.current = currentPath;
      return;
    }

    setShowRouteLoader(true);
    setMinTimeElapsed(false);

    const minTimer = window.setTimeout(() => setMinTimeElapsed(true), ROUTE_LOADER_MIN_MS);
    const maxTimer = window.setTimeout(() => setShowRouteLoader(false), ROUTE_LOADER_MAX_MS);

    previousPathRef.current = currentPath;

    return () => {
      window.clearTimeout(minTimer);
      window.clearTimeout(maxTimer);
    };
  }, [location.pathname]);

  // The loader follows the page's own loading, not a clock: it goes once the
  // minimum time has passed and nothing is still waiting on its first answer.
  useEffect(() => {
    if (showRouteLoader && minTimeElapsed && firstReadsInFlight === 0) setShowRouteLoader(false);
  }, [showRouteLoader, minTimeElapsed, firstReadsInFlight]);

  // Widening the window past the breakpoint must not leave a stale drawer open
  // over the desktop layout.
  useEffect(() => {
    if (!isMobile) setDrawerOpen(false);
  }, [isMobile]);

  // Escape closes the drawer, and focus goes back to the control that opened it.
  useEffect(() => {
    if (!drawerOpen) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setDrawerOpen(false);
        menuButtonRef.current?.focus();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [drawerOpen]);

  return (
    <div className="relative flex h-screen overflow-hidden">
      {isMobile ? (
        <AnimatePresence>
          {drawerOpen && (
            <>
              <motion.div
                key="scrim"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.15 }}
                onClick={() => setDrawerOpen(false)}
                className="fixed inset-0 z-40 bg-foreground/25 backdrop-blur-sm"
              />
              <motion.div
                key="drawer"
                initial={{ x: "-100%" }}
                animate={{ x: 0 }}
                exit={{ x: "-100%" }}
                transition={{ type: "tween", duration: 0.2, ease: "easeOut" }}
                className="fixed inset-y-0 left-0 z-50 w-[min(19rem,85vw)] shadow-raised"
                role="dialog"
                aria-modal="true"
                aria-label={t("nav.menu")}
              >
                <Sidebar isMobile onNavigate={() => setDrawerOpen(false)} />
              </motion.div>
            </>
          )}
        </AnimatePresence>
      ) : (
        <Sidebar />
      )}
      <main ref={mainRef} className="relative flex-1 overflow-y-auto overflow-x-hidden px-4 py-4 md:px-8 md:py-8">
        {isMobile && (
          <div className="sticky top-0 z-30 -mx-4 -mt-4 mb-4 flex items-center gap-3 border-b border-border bg-background/95 px-4 py-3 backdrop-blur-sm">
            <button
              ref={menuButtonRef}
              onClick={() => setDrawerOpen(true)}
              aria-label={t("nav.menu")}
              aria-expanded={drawerOpen}
              className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            >
              <Menu className="h-5 w-5" />
            </button>
            <img
              src={logoTile64}
              srcSet={`${logoTile64} 2x, ${logoTile96} 3x`}
              alt=""
              width={32}
              height={32}
              className="h-8 w-8 shrink-0 rounded-lg shadow-glow"
            />
            <p className="truncate text-sm font-semibold">Sonalim ERP</p>
            <div className="ml-auto">
              <NotificationBell />
            </div>
          </div>
        )}

        {showRouteLoader && (
          <div className="absolute inset-0 z-20 flex items-center justify-center bg-background/60 backdrop-blur-[2px]">
            <AppLoader label={t("app.loading")} className="py-8" />
          </div>
        )}

        <AnimatePresence mode="wait" onExitComplete={() => mainRef.current?.scrollTo({ top: 0 })}>
          <motion.div
            key={location.pathname}
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -6 }}
            transition={{ duration: 0.18 }}
            className="mx-auto max-w-6xl"
          >
            {children}
          </motion.div>
        </AnimatePresence>
      </main>
    </div>
  );
}
