/**
 * The three.js stage for the brand scene: a TypeScript port of the parts of
 * the brand-motion-design skill's kit/three.js used here, with its measured
 * traps built in: bloom threshold 1.0 (lower turns the scene to milk),
 * environment ~0.55 and exposure 0.95 (brighter turns every colour pastel),
 * and the background un-toned so the canvas edge is exactly the CSS navy.
 */
import {
  ACESFilmicToneMapping,
  CanvasTexture,
  Color,
  LinearSRGBColorSpace,
  MeshPhysicalMaterial,
  PerspectiveCamera,
  PMREMGenerator,
  Scene,
  SRGBColorSpace,
  Vector2,
  WebGLRenderer,
  type Camera,
  type MeshPhysicalMaterialParameters,
  type Texture,
} from "three";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";
import { EffectComposer } from "three/addons/postprocessing/EffectComposer.js";
import { OutputPass } from "three/addons/postprocessing/OutputPass.js";
import { RenderPass } from "three/addons/postprocessing/RenderPass.js";
import { UnrealBloomPass } from "three/addons/postprocessing/UnrealBloomPass.js";
import { untone } from "./color";

export const EXPOSURE = 0.95;
export const ENV_INTENSITY = 0.55;

/** The palette (skill BRAND.md, tailwind.config.ts). Nothing outside it. */
export const BRAND = {
  navyDeep: "#071F43",
  gold: "#F5A900",
  goldPellet: "#F5B51B",
  goldLight: "#FFD45A",
} as const;

export interface Stage {
  renderer: WebGLRenderer;
  environment: Texture;
  render(scene: Scene, camera: Camera): void;
  setSize(width: number, height: number, pixelRatio: number): void;
  setBloom(on: boolean): void;
  dispose(): void;
}

export interface StageOptions {
  /** Transparent background (the logo bake). Bloom stays off: its pass writes alpha 1. */
  transparent?: boolean;
  bloom?: boolean;
  /** Keep the drawing buffer so the bake can read pixels back. */
  preserve?: boolean;
}

export function createStage(canvas: HTMLCanvasElement, { transparent = false, bloom = true, preserve = false }: StageOptions = {}): Stage {
  const renderer = new WebGLRenderer({ canvas, antialias: true, alpha: transparent, preserveDrawingBuffer: preserve, powerPreference: "high-performance" });
  renderer.outputColorSpace = SRGBColorSpace;
  renderer.toneMapping = ACESFilmicToneMapping;
  renderer.toneMappingExposure = EXPOSURE;
  if (transparent) renderer.setClearColor(0x000000, 0);

  const pmrem = new PMREMGenerator(renderer);
  const room = new RoomEnvironment();
  const environment = pmrem.fromScene(room, 0.04).texture;
  room.dispose();
  pmrem.dispose();

  const composer = new EffectComposer(renderer);
  const renderPass = new RenderPass(new Scene(), new PerspectiveCamera());
  const bloomPass = new UnrealBloomPass(new Vector2(1, 1), 0.7, 0.55, 1.0);
  composer.addPass(renderPass);
  composer.addPass(bloomPass);
  composer.addPass(new OutputPass());
  let useBloom = bloom && !transparent;

  return {
    renderer,
    environment,
    render(scene, camera) {
      if (!useBloom) {
        renderer.render(scene, camera);
        return;
      }
      renderPass.scene = scene;
      renderPass.camera = camera;
      composer.render();
    },
    setSize(width, height, pixelRatio) {
      renderer.setPixelRatio(pixelRatio);
      renderer.setSize(width, height, false);
      composer.setPixelRatio(pixelRatio);
      composer.setSize(width, height);
    },
    setBloom(on) {
      useBloom = on && !transparent;
    },
    dispose() {
      bloomPass.dispose();
      composer.dispose();
      environment.dispose();
      renderer.dispose();
      // Release the GPU context now: logout/login cycles must not pile contexts up.
      renderer.forceContextLoss();
    },
  };
}

/** Polished gold for the logo: the kit's "metal", softened so the environment reads as gold, not chrome. */
export function goldMetal(extra: MeshPhysicalMaterialParameters = {}): MeshPhysicalMaterial {
  return new MeshPhysicalMaterial({ color: BRAND.gold, metalness: 1, roughness: 0.28, clearcoat: 0.6, clearcoatRoughness: 0.2, ...extra });
}

/** Dry pasta: the kit's "satin" (soft sheen, no gloss). Colour comes per instance from the gold ramp. */
export function pastaSatin(extra: MeshPhysicalMaterialParameters = {}): MeshPhysicalMaterial {
  return new MeshPhysicalMaterial({
    color: 0xffffff,
    roughness: 0.62,
    metalness: 0,
    sheen: 0.4,
    sheenRoughness: 0.6,
    sheenColor: new Color(BRAND.goldLight),
    ...extra,
  });
}

/** The linear colour that renders as exactly `hex` through this stage's tone mapping. */
export function untoneColor(hex: string): Color {
  const [r, g, b] = untone(hex, EXPOSURE);
  return new Color().setRGB(r, g, b, LinearSRGBColorSpace);
}

/** A soft round sprite (white centre fading out) for grains and the logo's halo. */
export function softDisc(size = 64): CanvasTexture {
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = size;
  const ctx = canvas.getContext("2d")!;
  const half = size / 2;
  const gradient = ctx.createRadialGradient(half, half, 0, half, half, half);
  gradient.addColorStop(0, "rgba(255,255,255,1)");
  gradient.addColorStop(0.45, "rgba(255,255,255,0.9)");
  gradient.addColorStop(1, "rgba(255,255,255,0)");
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, size, size);
  const texture = new CanvasTexture(canvas);
  texture.colorSpace = SRGBColorSpace;
  return texture;
}
