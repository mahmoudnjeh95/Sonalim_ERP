import { useEffect, useState } from "react";

/**
 * The one place the mobile/desktop divide is defined.
 *
 * Below this the app lays out for a phone (drawer nav, card lists, bottom
 * sheets); at this width and above it is the desktop app, unchanged. It matches
 * Tailwind's `md`, so a component can use `md:` utilities and this hook together
 * without the two drifting apart.
 *
 * Tablets sit on the desktop side deliberately: the table primitive's
 * `fitToWidth` still produces a usable grid at that width.
 */
export const MOBILE_MAX_WIDTH = 767;
export const MOBILE_MEDIA_QUERY = `(max-width: ${MOBILE_MAX_WIDTH}px)`;

export function useIsMobile(): boolean {
  const [isMobile, setIsMobile] = useState(() => matches());

  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return;
    const query = window.matchMedia(MOBILE_MEDIA_QUERY);
    const onChange = (event: MediaQueryListEvent) => setIsMobile(event.matches);
    // Re-read on mount: the width may have changed between the initial state
    // and this effect (a rotation, or a resize during hydration).
    setIsMobile(query.matches);
    query.addEventListener("change", onChange);
    return () => query.removeEventListener("change", onChange);
  }, []);

  return isMobile;
}

function matches(): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return false;
  return window.matchMedia(MOBILE_MEDIA_QUERY).matches;
}
