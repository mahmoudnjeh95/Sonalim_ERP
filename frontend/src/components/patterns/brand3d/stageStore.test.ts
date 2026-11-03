import { describe, expect, it } from "vitest";
import { createStageStore, loginRevealed, stageWanted, type StageState } from "./stageStore";
import { INTRO } from "./timeline";

function withClock() {
  let ms = 0;
  const store = createStageStore(() => ms);
  return {
    store,
    at: (value: number) => {
      ms = value;
    },
  };
}

describe("intro clock", () => {
  it("reads 0 until the intro starts", () => {
    const { store, at } = withClock();
    at(5000);
    expect(store.introTime()).toBe(0);
    expect(store.get().introStarted).toBe(false);
  });

  it("counts seconds from the start", () => {
    const { store, at } = withClock();
    at(1000);
    store.startIntro();
    at(2500);
    expect(store.introTime()).toBeCloseTo(1.5, 9);
    expect(store.get().introStarted).toBe(true);
  });

  it("starts only once", () => {
    const { store, at } = withClock();
    at(1000);
    store.startIntro();
    at(2000);
    store.startIntro();
    at(3000);
    expect(store.introTime()).toBeCloseTo(2, 9);
  });

  it("fast-forwards to the handoff after a skip, then runs on", () => {
    const { store, at } = withClock();
    at(1000);
    store.startIntro();
    at(2500);
    store.skipIntro();
    at(2800);
    expect(store.introTime()).toBeCloseTo(INTRO.handoff, 9);
    at(2900);
    expect(store.introTime()).toBeCloseTo(3.7, 9);
  });

  it("still skips when pressed before the 3D has started the clock", () => {
    const { store, at } = withClock();
    at(1000);
    store.skipIntro();
    expect(store.get().introStarted).toBe(true);
    at(1300);
    expect(store.introTime()).toBeCloseTo(INTRO.handoff, 9);
  });

  it("ignores a second skip", () => {
    const { store, at } = withClock();
    at(1000);
    store.startIntro();
    at(2000);
    store.skipIntro();
    at(2100);
    store.skipIntro();
    at(2300);
    expect(store.introTime()).toBeCloseTo(INTRO.handoff, 9);
  });

  it("pins the clock for dev stills", () => {
    const { store, at } = withClock();
    store.freezeIntro(2.9);
    at(9000);
    store.startIntro();
    store.skipIntro();
    at(20000);
    expect(store.introTime()).toBe(2.9);
  });
});

describe("store", () => {
  it("notifies subscribers and merges patches", () => {
    const { store } = withClock();
    let calls = 0;
    const off = store.subscribe(() => calls++);
    store.set({ ready: true });
    expect(calls).toBe(1);
    expect(store.get()).toMatchObject({ ready: true, fallback: false, introPhase: "none" });
    off();
    store.set({ ready: false });
    expect(calls).toBe(1);
  });
});

describe("stageWanted / loginRevealed", () => {
  const base: StageState = { introPhase: "none", introStarted: false, loginSlots: null, ready: false, fallback: false };

  it("wants the stage during the intro and on the login page only", () => {
    expect(stageWanted(base)).toBe(false);
    expect(stageWanted({ ...base, introPhase: "playing" })).toBe(true);
    expect(stageWanted({ ...base, introPhase: "handoff" })).toBe(true);
    expect(stageWanted({ ...base, introPhase: "done" })).toBe(false);
    expect(stageWanted({ ...base, introPhase: "done", loginSlots: [] })).toBe(true);
  });

  it("never holds the login form back for the 3D", () => {
    expect(loginRevealed({ ...base, introPhase: "none", ready: false })).toBe(true);
    expect(loginRevealed({ ...base, introPhase: "handoff", ready: false })).toBe(true);
    expect(loginRevealed({ ...base, introPhase: "done", fallback: true })).toBe(true);
    expect(loginRevealed({ ...base, introPhase: "playing", ready: true })).toBe(false);
  });
});
