// Review stills of the brand 3D (spec §8) from a private headless Chrome.
// Needs the dev server (and, for the app-shell shots, the backend on :8000).
// Usage: node scripts/brand-stills.mjs [--out <dir>] [--only <name prefix>] [--no-webgl]
import { mkdirSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { launchChrome, sleep } from "./lib/cdp.mjs";

const args = process.argv.slice(2);
const option = (name) => (args.includes(name) ? args[args.indexOf(name) + 1] : null);
const out = option("--out") ?? join(tmpdir(), "sonalim-brand-stills");
const only = option("--only");
const noWebgl = args.includes("--no-webgl");
const base = process.env.BRAND_URL ?? "http://localhost:5173";
const api = process.env.BRAND_API ?? "http://localhost:8000";

const DESKTOP = { width: 1440, height: 900, mobile: false };
const PHONE = { width: 390, height: 844, mobile: true };
const ALL = noWebgl
  ? [{ name: "login-no-webgl", path: "/login", ...DESKTOP, wait: 7000 }]
  : [
      { name: "intro-0.6", path: "/login?brand-t=0.6&brand-tier=high", ...DESKTOP, wait: 9000 },
      { name: "intro-1.8", path: "/login?brand-t=1.8&brand-tier=high", ...DESKTOP, wait: 9000 },
      { name: "intro-2.9", path: "/login?brand-t=2.9&brand-tier=high", ...DESKTOP, wait: 9000 },
      { name: "intro-3.8", path: "/login?brand-t=3.8&brand-tier=high", ...DESKTOP, wait: 9000 },
      { name: "intro-phone-2.9", path: "/login?brand-t=2.9&brand-tier=high", ...PHONE, wait: 9000 },
      { name: "login-desktop", path: "/login", ...DESKTOP, wait: 9000, cycles: 3 },
      { name: "login-tablet", path: "/login", width: 820, height: 1180, mobile: false, wait: 9000 },
      { name: "login-phone", path: "/login", ...PHONE, wait: 9000 },
      { name: "login-reduced-motion", path: "/login", ...DESKTOP, wait: 7000, reducedMotion: true },
      { name: "login-forced-fallback", path: "/login?brand-fallback=1", ...DESKTOP, wait: 7000 },
      { name: "app-shell-desktop", path: "/production", ...DESKTOP, wait: 10000, session: true },
      { name: "app-shell-phone", path: "/production", ...PHONE, wait: 10000, session: true },
    ];
const SHOTS = only ? ALL.filter((s) => s.name.startsWith(only)) : ALL;

/** Logs the demo user in over the API and returns the sessionStorage value the app expects (lib/auth.tsx). */
async function demoSession() {
  const response = await fetch(`${api}/core/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email: "demo@sonalim-erp.local", password: "demo1234" }),
  });
  if (!response.ok) throw new Error(`demo login failed: HTTP ${response.status} (is the backend up on ${api}?)`);
  const r = await response.json();
  return JSON.stringify({
    token: r.token,
    tenantId: r.tenant_id,
    userId: r.user_id,
    email: r.email,
    expiresAt: r.expires_at,
    refreshToken: r.refresh_token,
    refreshExpiresAt: r.refresh_expires_at,
    permissions: r.permissions,
  });
}

/** Vite restarts when `tsc -b --force` rewrites vite.config.js: wait until it answers again. */
async function devServerReady() {
  for (let i = 0; i < 60; i++) {
    try {
      if ((await fetch(`${base}/login`)).ok) return;
    } catch {
      // Not listening yet.
    }
    await sleep(500);
  }
  throw new Error(`the dev server at ${base} did not answer`);
}

mkdirSync(out, { recursive: true });
await devServerReady();
const chrome = await launchChrome({ port: 9345, flags: noWebgl ? ["--disable-3d-apis"] : [] });
try {
  // Needed for addScriptToEvaluateOnNewDocument to reach new documents (the app-shell session).
  await chrome.send("Page.enable");
  for (const shot of SHOTS) {
    if (shot.session) {
      const value = await demoSession();
      await chrome.send("Page.addScriptToEvaluateOnNewDocument", {
        source: `sessionStorage.setItem("sonalim-erp.session", ${JSON.stringify(value)});`,
      });
    }
    await chrome.send("Emulation.setDeviceMetricsOverride", {
      width: shot.width,
      height: shot.height,
      deviceScaleFactor: shot.mobile ? 2 : 1,
      mobile: shot.mobile,
    });
    await chrome.send("Emulation.setEmulatedMedia", {
      features: [{ name: "prefers-reduced-motion", value: shot.reducedMotion ? "reduce" : "no-preference" }],
    });
    await chrome.send("Page.navigate", { url: base + shot.path });
    await sleep(shot.wait);
    for (let i = 0; i < (shot.cycles ?? 0); i++) {
      // Leave the login for a public 404 and come back: each visit builds and disposes a renderer.
      await chrome.evaluate(`history.pushState({}, "", "/brand-cycle-${i}"); dispatchEvent(new PopStateEvent("popstate")); true`);
      await sleep(800);
      await chrome.evaluate(`history.pushState({}, "", "/login"); dispatchEvent(new PopStateEvent("popstate")); true`);
      await sleep(3000);
    }
    const { data } = await chrome.send("Page.captureScreenshot", { format: "png" });
    const file = join(out, `${shot.name}.png`);
    writeFileSync(file, Buffer.from(data, "base64"));
    const tier = await chrome.evaluate("document.documentElement.dataset.brandTier ?? 'none'");
    console.log(`${file}  tier=${tier}`);
  }
} finally {
  chrome.close();
}
