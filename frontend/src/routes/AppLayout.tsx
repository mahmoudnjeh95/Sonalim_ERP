import type { ReactNode } from "react";
import { useLocation } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import { Sidebar } from "./Sidebar";

export function AppLayout({ children }: { children: ReactNode }) {
  const location = useLocation();

  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar />
      <main className="flex-1 overflow-y-auto overflow-x-hidden px-8 py-8">
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
