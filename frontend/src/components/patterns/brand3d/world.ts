/**
 * The pasta world: one scene for the welcome intro and the login page (spec
 * 2026-10-02 §1–3), loaded as its own chunk through import("./world").
 * BrandStage calls frame() with the time; nothing here keeps its own clock.
 */
import { DirectionalLight, Fog, HemisphereLight, PerspectiveCamera, Scene, Vector3 } from "three";
import { LOGO_SLOT_DEPTH, placeInSlot, type Rect } from "./framing";
import { BRAND, createStage, ENV_INTENSITY, untoneColor } from "./kit";
import { createLogo } from "./logo";
import { lerp } from "./math";
import { grainSeeds, piecePose, pieceSeeds, type Pose } from "./motion";
import { createPasta, type Pasta } from "./pasta";
import { TIERS } from "./quality";
import { createSemolina, type Semolina } from "./semolina";
import { cameraPose, cameraPosition, FOV, introState, logoState, withPointer } from "./timeline";

export interface FrameInput {
  /** Stage time in seconds; orbits and drift run on it (the caller slows it to a stop when idle). */
  time: number;
  /** The intro clock while the intro plays, null after it. */
  intro: number | null;
  /** Seconds since the logo appeared in its slot without the intro; Infinity once the intro handed it over. */
  logoBuild: number;
  /** The login's logo slot in CSS px; null keeps the logo centred. */
  slot: Rect | null;
  /** Eased pointer, -1..1 per axis (0 on touch). */
  pointer: { x: number; y: number };
}

export interface WorldOptions {
  tier: "high" | "low";
  transparent?: boolean;
  /** Include the 3D logo (the poster bake leaves it out: the login slots show it). */
  logo?: boolean;
  preserve?: boolean;
}

export interface World {
  frame(input: FrameInput): void;
  setTier(tier: "high" | "low"): void;
  resize(width: number, height: number, pixelRatio: number): void;
  dispose(): void;
}

const SEED = 20261002;

interface Layers {
  count: number;
  pasta: Pasta;
  semolina: Semolina;
}

export function createWorld(canvas: HTMLCanvasElement, { tier, transparent = false, logo: withLogo = true, preserve = false }: WorldOptions): World {
  const stage = createStage(canvas, { transparent, bloom: TIERS[tier].bloom, preserve });
  const scene = new Scene();
  const navy = untoneColor(BRAND.navyDeep); // lands on #071F43 after tone mapping: the canvas edge is the CSS navy
  if (!transparent) scene.background = navy;
  // The fog band follows the camera distance (frame()), so a far portrait camera does not turn the pasta brown.
  const fog = new Fog(navy, 6, 26);
  scene.fog = fog;
  scene.environment = stage.environment;
  scene.environmentIntensity = ENV_INTENSITY;
  scene.add(new HemisphereLight(0xffffff, BRAND.navyDeep, 0.45));
  const key = new DirectionalLight(0xffffff, 1.8);
  key.position.set(-4, 8, 6);
  scene.add(key);

  const camera = new PerspectiveCamera(FOV, 1, 0.05, 200);
  const pieces = pieceSeeds(TIERS.high.pieces, SEED);
  const grains = grainSeeds(TIERS.high.grains, SEED + 1);
  const poses: Pose[] = pieces.map(() => ({ position: [0, 0, 0], rotation: [0, 0, 0], scale: 0 }));

  const build = (next: "high" | "low"): Layers => {
    const settings = TIERS[next];
    const layers = {
      count: settings.pieces,
      pasta: createPasta(pieces.slice(0, settings.pieces)),
      semolina: createSemolina(grains.slice(0, settings.grains)),
    };
    scene.add(...layers.pasta.meshes, ...layers.semolina.points);
    stage.setBloom(settings.bloom);
    return layers;
  };
  const clear = (old: Layers) => {
    scene.remove(...old.pasta.meshes, ...old.semolina.points);
    old.pasta.dispose();
    old.semolina.dispose();
  };
  let layers = build(tier);

  const logo = withLogo ? createLogo() : null;
  if (logo) scene.add(logo.group);

  let width = 1;
  let height = 1;
  const slotPoint = new Vector3();

  return {
    frame({ time, intro, logoBuild, slot, pointer }) {
      const state = intro === null ? null : introState(intro);
      const pose = withPointer(cameraPose(intro, time, width / height), pointer);
      camera.position.set(...cameraPosition(pose));
      camera.lookAt(pose.target[0], pose.target[1], pose.target[2]);
      camera.updateMatrixWorld();
      // Depth fades in only behind the framed target: nothing in front of it is fogged.
      fog.near = pose.radius - 1;
      fog.far = pose.radius + 20;

      for (let i = 0; i < layers.count; i++) poses[i] = piecePose(pieces[i], time, state);
      layers.pasta.update(poses);
      layers.semolina.update(time, intro !== null && state ? { t: intro, state } : null, poses, layers.count);

      if (logo) {
        logo.set(logoState(intro, logoBuild));
        // Centred during the intro; glued to its login slot after the handoff (the slot is read every frame).
        let size = 1;
        slotPoint.set(0, 0, 0);
        if (slot) {
          const placed = placeInSlot(slot, width, height, FOV, LOGO_SLOT_DEPTH);
          const u = state ? state.handoff : 1;
          const target = camera.localToWorld(new Vector3(placed.x, placed.y, placed.z));
          slotPoint.set(lerp(0, target.x, u), lerp(0, target.y, u), lerp(0, target.z, u));
          size = lerp(1, placed.size / 2, u); // the mark spans 2 world units at scale 1
        }
        logo.group.position.copy(slotPoint);
        logo.group.scale.setScalar(size);
        logo.group.rotation.set(-0.12 + 0.05 * Math.sin(time * 0.37), 0.22 * Math.sin(time * 0.5), 0);
      }
      stage.render(scene, camera);
    },
    setTier(next) {
      clear(layers);
      layers = build(next);
    },
    resize(w, h, pixelRatio) {
      width = w;
      height = h;
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      stage.setSize(w, h, pixelRatio);
    },
    dispose() {
      clear(layers);
      logo?.dispose();
      stage.dispose();
    },
  };
}
