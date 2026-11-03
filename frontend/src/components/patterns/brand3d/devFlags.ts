/**
 * Dev-only URL flags for review stills (scripts/brand-stills.mjs):
 *   ?brand-t=2.9        pin the intro clock at 2.9 s (the intro then never ends)
 *   ?brand-tier=low     force a quality tier (no measuring)
 *   ?brand-fallback=1   force the baked-poster fallback
 * Production builds ignore the URL.
 */

export interface BrandDevFlags {
  introAt: number | null;
  tier: "high" | "low" | "still" | null;
  fallback: boolean;
}

const NONE: BrandDevFlags = { introAt: null, tier: null, fallback: false };

export function parseBrandFlags(search: string): BrandDevFlags {
  const q = new URLSearchParams(search);
  const t = q.get("brand-t");
  const tier = q.get("brand-tier");
  return {
    introAt: t !== null && t !== "" && Number.isFinite(Number(t)) ? Number(t) : null,
    tier: tier === "high" || tier === "low" || tier === "still" ? tier : null,
    fallback: q.get("brand-fallback") === "1",
  };
}

export const brandFlags: BrandDevFlags =
  import.meta.env.DEV && typeof window !== "undefined" ? parseBrandFlags(window.location.search) : NONE;
