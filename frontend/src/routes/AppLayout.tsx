import type { ReactNode } from "react";
import { useEffect, useRef, useState } from "react";
import { useLocation } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import { useIsFetching } from "@tanstack/react-query";
import { Sidebar } from "./Sidebar";
import { AppLoader } from "../components/patterns/AppLoader";
import { useI18n } from "../lib/i18n";
import { TreasuryAlertBanner } from "../features/treasury/TreasuryAlertBanner";

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

  return (
    <div className="relative flex h-screen overflow-hidden">
      <Sidebar />
      <main ref={mainRef} className="relative flex-1 overflow-y-auto overflow-x-hidden px-8 py-8">
        {showRouteLoader && (
          <div className="absolute inset-0 z-20 flex items-center justify-center bg-background/60 backdrop-blur-[2px]">
            <AppLoader label={t("app.loading")} className="py-8" />
          </div>
        )}

        <TreasuryAlertBanner />

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
