/**
 * The brand stage's shared state: which screen wants the 3D, the intro's phase
 * and its clock. One small external store, because the splash (outside the
 * router) and the login page (inside it) drive one canvas together.
 */
import { useSyncExternalStore } from "react";
import { skipTime } from "./timeline";

export type IntroPhase = "none" | "playing" | "handoff" | "done";

export interface StageState {
  introPhase: IntroPhase;
  /** The intro clock runs: from the first live frame, or from the poster timeout. */
  introStarted: boolean;
  /** The login page's logo slots while it is mounted, null otherwise. */
  loginSlots: readonly HTMLElement[] | null;
  /** The live scene has drawn its first frame. */
  ready: boolean;
  /** No live 3D here: reduced motion, no WebGL 2, a lost context or a failed chunk. */
  fallback: boolean;
}

const INITIAL: StageState = { introPhase: "none", introStarted: false, loginSlots: null, ready: false, fallback: false };

export function createStageStore(now: () => number = () => performance.now()) {
  let state = INITIAL;
  const listeners = new Set<() => void>();
  let startMs: number | null = null;
  let skipMs: number | null = null;
  let skippedAt = 0;
  let frozen: number | null = null;

  const set = (patch: Partial<StageState>) => {
    state = { ...state, ...patch };
    listeners.forEach((listener) => listener());
  };

  /** Intro time in seconds: 0 until started; after a skip, the fast-forward (timeline.skipTime). */
  const introTime = (): number => {
    if (frozen !== null) return frozen;
    if (startMs === null) return 0;
    const at = now();
    return skipMs === null ? (at - startMs) / 1000 : skipTime(skippedAt, (at - skipMs) / 1000);
  };

  const startIntro = () => {
    if (startMs !== null) return;
    startMs = now();
    set({ introStarted: true });
  };

  /** A skip before the 3D has started the clock starts it, so the intro still ends at once. */
  const skipIntro = () => {
    if (frozen !== null || skipMs !== null) return;
    startIntro();
    skippedAt = introTime();
    skipMs = now();
  };

  return {
    get: () => state,
    subscribe: (listener: () => void) => {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    set,
    introTime,
    startIntro,
    skipIntro,
    /** Dev stills (`?brand-t=`): pin the intro clock at `t` seconds. */
    freezeIntro: (t: number) => {
      frozen = t;
    },
  };
}

export type StageStore = ReturnType<typeof createStageStore>;

export const stageStore = createStageStore();

/** Subscribe a component to one slice of the stage. `select` must return a primitive or a stored reference. */
export function useStage<T>(select: (state: StageState) => T): T {
  return useSyncExternalStore(stageStore.subscribe, () => select(stageStore.get()));
}

/** The canvas is wanted while the intro plays and while the login page is mounted. */
export const stageWanted = (s: StageState): boolean =>
  s.introPhase === "playing" || s.introPhase === "handoff" || s.loginSlots !== null;

/** The login card shows unless the intro is still playing: it never waits for the 3D. */
export const loginRevealed = (s: StageState): boolean => s.introPhase !== "playing";
