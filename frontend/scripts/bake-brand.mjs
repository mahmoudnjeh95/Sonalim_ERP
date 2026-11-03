// Bakes the 3D logo images and the fallback posters from the live 3D code
// (spec docs/superpowers/specs/2026-10-02-brand-3d-design.md §6) and saves them
// in place. Needs the dev server: `npm run dev`, then `node scripts/bake-brand.mjs`.
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { launchChrome } from "./lib/cdp.mjs";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const base = process.env.BRAND_URL ?? "http://localhost:5173";
const ICONS = "src/assets/icons/brand";
const DEST = {
  "logo-3d-mark-512.png": ICONS,
  "logo-3d-64.png": ICONS,
  "logo-3d-96.png": ICONS,
  "logo-3d-88.png": ICONS,
  "logo-3d-132.png": ICONS,
  "favicon-16.png": "public",
  "favicon-32.png": "public",
  "apple-touch-icon.png": "public",
  "sonalim-stage-landscape.webp": "src/assets/animations",
  "sonalim-stage-portrait.webp": "src/assets/animations",
};

const chrome = await launchChrome({ port: 9344 });
try {
  await chrome.send("Page.navigate", { url: `${base}/bake-brand.html` });
  await chrome.waitFor("location.pathname === '/bake-brand.html' && !!window.__brandBake");
  const outputs = JSON.parse(await chrome.evaluate("window.__brandBake.then((o) => JSON.stringify(o))"));
  const missing = Object.keys(DEST).filter((name) => !outputs.some((o) => o.name === name));
  if (missing.length) throw new Error(`the bake page did not produce: ${missing.join(", ")}`);
  for (const { name, dataUrl } of outputs) {
    const dir = DEST[name];
    if (!dir) throw new Error(`unexpected bake output ${name}`);
    mkdirSync(join(root, dir), { recursive: true });
    const bytes = Buffer.from(dataUrl.slice(dataUrl.indexOf(",") + 1), "base64");
    writeFileSync(join(root, dir, name), bytes);
    console.log(`${dir}/${name}  ${(bytes.length / 1024).toFixed(1)} KB`);
  }
} finally {
  chrome.close();
}
