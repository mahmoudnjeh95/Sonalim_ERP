/**
 * Semolina: fine gold grains, plus a few sparks drawn brighter than white so
 * they alone cross the bloom threshold. Positions come from motion.ts each frame.
 */
import { BufferAttribute, BufferGeometry, Color, Points, PointsMaterial } from "three";
import { mixHex } from "./color";
import { BRAND, softDisc } from "./kit";
import type { Vec3 } from "./math";
import { grainPosition, type GrainSeed, type Pose } from "./motion";
import type { IntroState } from "./timeline";

export interface Semolina {
  points: Points[];
  update(time: number, intro: { t: number; state: IntroState } | null, poses: readonly Pose[], pieceCount: number): void;
  dispose(): void;
}

export function createSemolina(seeds: readonly GrainSeed[]): Semolina {
  const sprite = softDisc(64);
  const colour = new Color();
  const layer = (members: readonly GrainSeed[], size: number, brightness: number) => {
    const positions = new Float32Array(members.length * 3);
    const colours = new Float32Array(members.length * 4); // rgba: alpha per grain
    members.forEach((g, i) => {
      colour.set(mixHex(BRAND.goldPellet, BRAND.goldLight, g.tone)).multiplyScalar(brightness);
      colours.set([colour.r, colour.g, colour.b, 0], i * 4);
    });
    const geometry = new BufferGeometry();
    geometry.setAttribute("position", new BufferAttribute(positions, 3));
    geometry.setAttribute("color", new BufferAttribute(colours, 4));
    const material = new PointsMaterial({ size, map: sprite, vertexColors: true, transparent: true, depthWrite: false, sizeAttenuation: true });
    const points = new Points(geometry, material);
    points.frustumCulled = false;
    return { members, positions, colours, geometry, material, points };
  };
  const layers = [layer(seeds.filter((g) => !g.glow), 0.045, 1), layer(seeds.filter((g) => g.glow), 0.09, 4)];
  const out: Vec3 = [0, 0, 0];

  return {
    points: layers.map((l) => l.points),
    update(time, intro, poses, pieceCount) {
      for (const l of layers) {
        l.members.forEach((g, i) => {
          const alpha = grainPosition(g, time, intro, poses, pieceCount, out);
          l.positions[i * 3] = out[0];
          l.positions[i * 3 + 1] = out[1];
          l.positions[i * 3 + 2] = out[2];
          l.colours[i * 4 + 3] = alpha;
        });
        l.geometry.attributes.position.needsUpdate = true;
        l.geometry.attributes.color.needsUpdate = true;
      }
    },
    dispose() {
      for (const l of layers) {
        l.geometry.dispose();
        l.material.dispose();
      }
      sprite.dispose();
    },
  };
}
