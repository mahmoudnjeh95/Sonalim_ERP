/**
 * Dev-only bake page (frontend/bake-brand.html): renders the 3D logo images and
 * the fallback posters from the same code as the live scene, so they always
 * match it. `node scripts/bake-brand.mjs` (dev server up) saves them in place.
 * Never in the production build: Vite builds index.html only.
 */
import { DirectionalLight, HemisphereLight, PerspectiveCamera, Scene } from "three";
import { BRAND, createStage, ENV_INTENSITY } from "./kit";
import { createLogo, type LogoOptions } from "./logo";
import { createWorld } from "./world";

export interface BakeOutput {
  name: string;
  dataUrl: string;
}

// Ring and strokes thicken as the image shrinks, so the mark still reads at 16–32 px.
const THIN: LogoOptions = { ringTube: 0.035, strokeScale: 1 };
const MEDIUM: LogoOptions = { ringTube: 0.05, strokeScale: 1.2 };
const THICK: LogoOptions = { ringTube: 0.07, strokeScale: 1.5 };
const MARK_PX = 512;

function canvas2d(size: number) {
  const c = document.createElement("canvas");
  c.width = c.height = size;
  const ctx = c.getContext("2d")!;
  ctx.imageSmoothingQuality = "high";
  return { c, ctx };
}

/** The gold mark alone on a transparent 512 px square, lit like the live scene. */
function renderMark(options: LogoOptions): HTMLCanvasElement {
  const canvas = document.createElement("canvas");
  const stage = createStage(canvas, { transparent: true, bloom: false, preserve: true });
  stage.setSize(MARK_PX, MARK_PX, 1);
  const scene = new Scene();
  scene.environment = stage.environment;
  scene.environmentIntensity = ENV_INTENSITY;
  scene.add(new HemisphereLight(0xffffff, BRAND.navyDeep, 0.5));
  const key = new DirectionalLight(0xffffff, 2);
  key.position.set(-3, 5, 6);
  scene.add(key);
  const logo = createLogo({ ...options, halo: false });
  logo.set({ ring: 1, glyph: 1, flash: 0 });
  logo.group.rotation.set(-0.1, -0.28, 0);
  scene.add(logo.group);
  const camera = new PerspectiveCamera(15, 1, 0.1, 100);
  camera.position.set(0, 0, 1 / (0.92 * Math.tan((15 * Math.PI) / 360))); // the mark (radius ~1) fills 92 %
  camera.lookAt(0, 0, 0);
  stage.render(scene, camera);
  const { c, ctx } = canvas2d(MARK_PX);
  ctx.drawImage(canvas, 0, 0);
  logo.dispose();
  stage.dispose();
  return c;
}

/** Halve until near the target, then draw at size: smoother than one big jump. */
function downscale(src: HTMLCanvasElement, size: number): HTMLCanvasElement {
  let current = src;
  while (current.width / 2 >= size) {
    const { c, ctx } = canvas2d(current.width / 2);
    ctx.drawImage(current, 0, 0, c.width, c.height);
    current = c;
  }
  const { c, ctx } = canvas2d(size);
  ctx.drawImage(current, 0, 0, size, size);
  return c;
}

/** The mark on a navy rounded square with a soft gold glow (the login panel's look). `radius` and `padding` are shares of the side. */
function tile(mark: HTMLCanvasElement, size: number, radius: number, padding: number): HTMLCanvasElement {
  const { c, ctx } = canvas2d(size);
  ctx.beginPath();
  ctx.roundRect(0, 0, size, size, radius * size);
  ctx.fillStyle = BRAND.navyDeep;
  ctx.fill();
  const glow = ctx.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
  glow.addColorStop(0, "rgba(245,169,0,0.22)");
  glow.addColorStop(1, "rgba(245,169,0,0)");
  ctx.fillStyle = glow;
  ctx.fill();
  const inner = Math.round(size * (1 - 2 * padding));
  const offset = Math.round((size - inner) / 2);
  ctx.drawImage(downscale(mark, inner), offset, offset);
  return c;
}

/** The login scene without the logo (the slots show it), as the fallback poster. */
function poster(width: number, height: number): string {
  const canvas = document.createElement("canvas");
  const world = createWorld(canvas, { tier: "high", logo: false, preserve: true });
  world.resize(width, height, 1);
  world.frame({ time: 14, intro: null, logoBuild: Infinity, slot: null, pointer: { x: 0, y: 0 } });
  const url = canvas.toDataURL("image/webp", 0.82);
  world.dispose();
  return url;
}

function bake(): BakeOutput[] {
  const outputs: BakeOutput[] = [];
  const png = (name: string, c: HTMLCanvasElement) => outputs.push({ name, dataUrl: c.toDataURL("image/png") });
  png("logo-3d-mark-512.png", renderMark(THIN));
  const medium = renderMark(MEDIUM);
  for (const size of [64, 96, 88, 132]) png(`logo-3d-${size}.png`, tile(medium, size, 0.28, 0.14));
  const thick = renderMark(THICK);
  for (const size of [16, 32]) png(`favicon-${size}.png`, tile(thick, size, 0.22, 0.08));
  png("apple-touch-icon.png", tile(medium, 180, 0, 0.16)); // iOS rounds the corners itself
  outputs.push({ name: "sonalim-stage-landscape.webp", dataUrl: poster(1920, 1080) });
  outputs.push({ name: "sonalim-stage-portrait.webp", dataUrl: poster(1080, 1920) });
  return outputs;
}

declare global {
  interface Window {
    __brandBake?: Promise<BakeOutput[]>;
  }
}

window.__brandBake = Promise.resolve().then(() => {
  const outputs = bake();
  const list = document.getElementById("out")!;
  for (const { name, dataUrl } of outputs) {
    const figure = document.createElement("figure");
    const img = document.createElement("img");
    img.src = dataUrl;
    img.alt = name;
    const caption = document.createElement("figcaption");
    caption.textContent = name;
    figure.append(img, caption);
    list.appendChild(figure);
  }
  return outputs;
});
