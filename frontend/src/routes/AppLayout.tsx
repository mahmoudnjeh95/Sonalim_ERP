import type { ReactNode } from "react";
import { useEffect, useRef, useState } from "react";
import { useLocation } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import { Sidebar } from "./Sidebar";
import { AppLoader } from "../components/patterns/AppLoader";

export function AppLayout({ children }: { children: ReactNode }) {
  const location = useLocation();
  const previousPathRef = useRef(location.pathname);
  const [showRouteLoader, setShowRouteLoader] = useState(false);

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

    const timer = window.setTimeout(() => {
      setShowRouteLoader(false);
    }, 1000);

    previousPathRef.current = currentPath;

    return () => window.clearTimeout(timer);
  }, [location.pathname]);

  return (
    <div className="relative flex h-screen overflow-hidden">
      <Sidebar />
      <main className="relative flex-1 overflow-y-auto overflow-x-hidden px-8 py-8">
        {showRouteLoader && (
          <div className="absolute inset-0 z-20 flex items-center justify-center bg-background/60 backdrop-blur-[2px]">
            <AppLoader label="Loading…" className="py-8" />
          </div>
        )}

        <AnimatePresence mode="wait">
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
