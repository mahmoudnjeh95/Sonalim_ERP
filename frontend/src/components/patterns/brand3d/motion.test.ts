import { describe, expect, it } from "vitest";
import { LOGO_SLOT_DEPTH } from "./framing";
import type { Vec3 } from "./math";
import { DUST, grainPosition, grainSeeds, PIECE_EXTENT, piecePose, pieceSeeds, SHAPES, type Pose } from "./motion";
import { cameraPose, cameraPosition, INTRO, introState, withPointer } from "./timeline";

const SEEDS = pieceSeeds(60, 20261002);
const TIMES = Array.from({ length: 81 }, (_, i) => i * 0.5); // 0..40 s

describe("pieceSeeds", () => {
  it("repeats the same layout for the same seed", () => {
    expect(pieceSeeds(60, 20261002)).toEqual(SEEDS);
  });

  it("mixes the plant's four shapes, mostly short pasta", () => {
    const count = (shape: string) => SEEDS.filter((s) => s.shape === shape).length;
    expect(SHAPES.map(count)).toEqual([12, 21, 18, 9]);
  });

  it("keeps the low tier a prefix of the high tier", () => {
    expect(pieceSeeds(30, 20261002)).toEqual(SEEDS.slice(0, 30));
  });
});

describe("piecePose", () => {
  it("settles exactly onto its login track at the end of the intro", () => {
    for (const p of SEEDS) expect(piecePose(p, 7, introState(4.2))).toEqual(piecePose(p, 7, null));
  });

  it("is not there before the grains have condensed", () => {
    for (const p of SEEDS) expect(piecePose(p, 1, introState(1)).scale).toBe(0);
  });
});

describe("pasta never covers the logo", () => {
  // From the ring's first stroke to the end of the intro, then the login.
  const introStates = [...Array.from({ length: 17 }, (_, i) => introState(INTRO.ringStart + i * 0.1)), null];

  it("stays behind the logo's plane or clear of it once the logo appears", () => {
    for (const p of SEEDS) {
      for (const time of TIMES) {
        for (const state of introStates) {
          const [x, y, z] = piecePose(p, time, state).position;
          const behind = z + PIECE_EXTENT <= -0.1;
          const clear = Math.hypot(x, y) - PIECE_EXTENT >= 0.95;
          expect(behind || clear, `${p.track} piece ${p.index} at t=${time}`).toBe(true);
        }
      }
    }
  });

  it("stays deeper than the logo in its login slot, whatever the screen and pointer", () => {
    for (const aspect of [16 / 9, 4 / 3, 9 / 16]) {
      for (const time of TIMES) {
        for (const extreme of [-1, 1]) {
          const eye = cameraPosition(withPointer(cameraPose(null, time, aspect), { x: extreme, y: extreme }));
          for (const p of SEEDS) {
            const [x, y, z] = piecePose(p, time, null).position;
            expect(Math.hypot(x - eye[0], y - eye[1], z - eye[2]) - PIECE_EXTENT).toBeGreaterThan(LOGO_SLOT_DEPTH + 0.5);
          }
        }
      }
    }
  });
});

describe("grains", () => {
  const GRAINS = grainSeeds(1200, 20261003);
  const at = 2.39;
  const poses: Pose[] = SEEDS.map((p) => piecePose(p, at, introState(at)));
  const out: Vec3 = [0, 0, 0];

  it("are invisible before the stream reaches them", () => {
    for (const g of GRAINS) expect(grainPosition(g, 0, { t: 0, state: introState(0) }, poses, 60, out)).toBe(0);
  });

  it("have all landed on their piece and faded by the end of condensing", () => {
    for (const g of GRAINS) {
      const alpha = grainPosition(g, at, { t: at, state: introState(at) }, poses, 60, out);
      const [tx, ty, tz] = poses[g.piece % 60].position;
      expect(alpha).toBe(0);
      expect(Math.hypot(out[0] - tx, out[1] - ty, out[2] - tz)).toBeLessThan(0.4);
    }
  });

  it("land on the pieces a smaller tier keeps", () => {
    const g = GRAINS[45];
    grainPosition(g, at, { t: at, state: introState(at) }, poses, 30, out);
    const [tx, ty, tz] = poses[45 % 30].position;
    expect(Math.hypot(out[0] - tx, out[1] - ty, out[2] - tz)).toBeLessThan(0.4);
  });

  it("float as dust inside the volume on the login page", () => {
    for (const g of GRAINS) {
      expect(grainPosition(g, 30, null, poses, 60, out)).toBeGreaterThan(0);
      expect(Math.abs(out[1])).toBeLessThanOrEqual(DUST.y);
    }
  });
});
