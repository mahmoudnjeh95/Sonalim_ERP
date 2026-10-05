/**
 * The one live 3D canvas behind the welcome intro and the login page (spec
 * 2026-10-02 §3–5). Mounted once in App. It renders only while the intro plays
 * or the login page is mounted, shows a baked poster when there is no live 3D,
 * steps its quality down on slow machines and comes to rest when nobody moves.
 */
import { useEffect, useRef, useState } from "react";
import posterLandscape from "../../../assets/animations/sonalim-stage-landscape.webp";
import posterPortrait from "../../../assets/animations/sonalim-stage-portrait.webp";
import { brandFlags } from "./devFlags";
import type { Rect } from "./framing";
import { nextTier, pixelRatio, SAMPLE_FRAMES, type Tier } from "./quality";
import { stageStore, stageWanted, useStage } from "./stageStore";
import type { World } from "./world";

const IDLE_STOP_MS = 60_000;
const FADE_MS = 600;
const NAVY_GLOW = "radial-gradient(40vmin 40vmin at 50% 50%, rgba(245,169,0,0.16), transparent 70%), #071F43";

function liveSupported(): boolean {
  if (brandFlags.fallback) return false;
  if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return false;
  try {
    const gl = document.createElement("canvas").getContext("webgl2");
    gl?.getExtension("WEBGL_lose_context")?.loseContext();
    return gl !== null;
  } catch {
    return false;
  }
}

/** The login's first visible logo slot, in CSS px (a slot hidden at this width measures 0 and is skipped). */
function slotRect(): Rect | null {
  for (const el of stageStore.get().loginSlots ?? []) {
    const r = el.getBoundingClientRect();
    if (r.width > 0 && r.height > 0) return { left: r.left, top: r.top, width: r.width, height: r.height };
  }
  return null;
}

/** Dev only: lets scripts/brand-stills.mjs report which tier ran. */
function markTier(tier: Tier | "fallback") {
  if (import.meta.env.DEV) document.documentElement.dataset.brandTier = tier;
}

export function BrandStage() {
  const wanted = useStage(stageWanted);
  const fallback = useStage((s) => s.fallback);
  const ready = useStage((s) => s.ready);
  const phase = useStage((s) => s.introPhase);
  const introStarted = useStage((s) => s.introStarted);
  const containerRef = useRef<HTMLDivElement>(null);
  // Keep the layer one fade longer than `wanted`, so leaving the login fades the navy out.
  const [shown, setShown] = useState(wanted);
  // The poster stays under a fading-in canvas until the fade is over.
  const [settled, setSettled] = useState(false);

  useEffect(() => {
    if (wanted) {
      setShown(true);
      return;
    }
    const id = window.setTimeout(() => setShown(false), 300);
    return () => window.clearTimeout(id);
  }, [wanted]);

  useEffect(() => {
    if (!ready) {
      setSettled(false);
      return;
    }
    const id = window.setTimeout(() => setSettled(true), FADE_MS);
    return () => window.clearTimeout(id);
  }, [ready]);

  useEffect(() => {
    if (!wanted || fallback) return;
    if (!liveSupported()) {
      markTier("fallback");
      stageStore.set({ fallback: true });
      return;
    }
    const container = containerRef.current;
    if (!container) return;
    // A fresh canvas per run: a disposed renderer loses its context, and a lost canvas cannot be reused.
    const canvas = document.createElement("canvas");
    canvas.className = "absolute inset-0 h-full w-full";
    canvas.style.zIndex = "1";
    canvas.style.opacity = "0";
    canvas.style.transition = `opacity ${FADE_MS}ms ease-out`;
    container.appendChild(canvas);

    let world: World | null = null;
    let disposed = false;
    let raf = 0;
    let tier: Tier = brandFlags.tier ?? "high";
    let samples: number[] = [];
    let warmup = 5;
    let last = 0;
    let time = 0;
    let motion = 1;
    let lastInput = performance.now();
    const pointer = { x: 0, y: 0 };
    const target = { x: 0, y: 0 };
    let handedOff = false;
    let buildStart: number | null = null;

    const goFallback = () => {
      markTier("fallback");
      stageStore.set({ fallback: true });
    };

    const frame = (now: number) => {
      if (!world) return;
      const dt = last ? Math.min(0.1, (now - last) / 1000) : 0; // a stall never jumps the orbits
      last = now;
      const s = stageStore.get();
      const introRunning = s.introPhase === "playing" || s.introPhase === "handoff";
      if (s.introPhase === "handoff") handedOff = true;
      if (introRunning) stageStore.startIntro(); // the intro's clock starts on its first live frame
      const idle = !introRunning && now - lastInput > IDLE_STOP_MS;
      motion += ((idle ? 0 : 1) - motion) * Math.min(1, dt * 2);
      time += dt * motion;
      const ease = Math.min(1, dt * 3);
      pointer.x += (target.x - pointer.x) * ease;
      pointer.y += (target.y - pointer.y) * ease;
      if (!introRunning && !handedOff && buildStart === null) buildStart = now;
      world.frame({
        time,
        intro: introRunning ? stageStore.introTime() : null,
        logoBuild: handedOff ? Infinity : buildStart === null ? 0 : (now - buildStart) / 1000,
        slot: slotRect(),
        pointer,
      });
      if (!s.ready) {
        canvas.style.opacity = "1";
        stageStore.set({ ready: true });
      }
      if (brandFlags.tier || tier === "still") return;
      if (warmup > 0) {
        warmup--;
        return;
      }
      if (dt > 0) samples.push(dt * 1000);
      if (samples.length < SAMPLE_FRAMES) return;
      const next = nextTier(tier, samples, !introRunning);
      samples = [];
      if (next === tier) return;
      tier = next;
      markTier(tier);
      if (tier !== "still") {
        world.setTier(tier);
        resize();
      }
    };

    const loop = () => {
      raf = requestAnimationFrame((now) => {
        raf = 0;
        frame(now);
        // Stop when frozen, hidden, or at rest after the idle ease (input restarts it).
        if (!disposed && tier !== "still" && !document.hidden && motion > 0.001) loop();
      });
    };

    function resize() {
      if (!world) return;
      world.resize(window.innerWidth, window.innerHeight, pixelRatio(window.devicePixelRatio || 1, tier));
      if (!raf) frame(performance.now()); // a resting or frozen scene still follows the window
    }

    const wake = () => {
      lastInput = performance.now();
      if (!raf && world && !disposed && tier !== "still" && !document.hidden) loop();
    };
    const onPointerMove = (event: PointerEvent) => {
      wake();
      if (event.pointerType !== "mouse") return;
      target.x = (event.clientX / window.innerWidth) * 2 - 1;
      target.y = (event.clientY / window.innerHeight) * 2 - 1;
    };
    const onVisibility = () => {
      if (document.hidden) {
        cancelAnimationFrame(raf);
        raf = 0;
      } else {
        last = 0;
        wake();
      }
    };
    const onLost = (event: Event) => {
      event.preventDefault();
      goFallback();
    };

    window.addEventListener("resize", resize);
    window.addEventListener("pointermove", onPointerMove);
    window.addEventListener("pointerdown", wake);
    window.addEventListener("keydown", wake);
    document.addEventListener("visibilitychange", onVisibility);
    canvas.addEventListener("webglcontextlost", onLost);
    markTier(tier);

    import("./world").then(
      ({ createWorld }) => {
        if (disposed) return;
        try {
          world = createWorld(canvas, { tier: tier === "still" ? "low" : tier });
        } catch {
          goFallback();
          return;
        }
        resize();
        loop();
      },
      () => {
        if (!disposed) goFallback();
      },
    );

    return () => {
      disposed = true;
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", resize);
      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("pointerdown", wake);
      window.removeEventListener("keydown", wake);
      document.removeEventListener("visibilitychange", onVisibility);
      // Before dispose: forcing the context loss on purpose is not a failure.
      canvas.removeEventListener("webglcontextlost", onLost);
      world?.dispose();
      canvas.remove();
      stageStore.set({ ready: false });
    };
  }, [wanted, fallback]);

  if (!wanted && !shown) return null;

  const introRunning = phase === "playing" || phase === "handoff";
  // During the intro: plain navy until the clock runs, then the poster only if the live 3D is not there yet.
  const showPoster = fallback || (introRunning ? introStarted && !ready : !settled);

  return (
    <div
      ref={containerRef}
      aria-hidden="true"
      className="pointer-events-none fixed inset-0 z-0 transition-opacity duration-300"
      style={{ opacity: wanted ? 1 : 0, background: NAVY_GLOW }}
    >
      {showPoster && (
        <picture>
          <source media="(orientation: portrait)" srcSet={posterPortrait} />
          <img src={posterLandscape} alt="" className="absolute inset-0 h-full w-full object-cover" />
        </picture>
      )}
    </div>
  );
}
