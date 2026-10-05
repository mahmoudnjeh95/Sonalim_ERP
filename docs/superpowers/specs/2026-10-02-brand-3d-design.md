# Brand 3D: logo, welcome intro and login scene — design

Date: 2026-10-02
Status: draft, awaiting review

## Goal

Give Sonalim ERP a 3D brand presence, made with the look and rules of the
`brand-motion-design` skill (`C:\Users\mahmoudn\Downloads\brand-motion-design-skill-main`):

1. a **simple 3D logo** used inside the app,
2. a **smooth 3D welcome intro** (the splash a signed-out visitor sees on the way to login),
3. **3D motion on the login page**,

with **pasta and semolina** as the subject of the motion.

## Decisions (user, 2026-10-02)

| Question | Answer |
|---|---|
| Logo | A *simple* 3D logo. Read as: the current vector mark `logo-mark.svg` (ring + wheat glyph), not the raster "S" of the splash art. |
| Motion subject | Pasta and semolina. |
| Delivery | **Live 3D in the browser** (not pre-rendered video). |
| 3D logo spots | Sidebar + mobile header, login page, welcome splash, browser tab icon. |
| Intro length | About **4 s, skippable**. |
| Login 3D | **Whole page background**. |
| Login stage colour | **Navy, continuing the intro** (login becomes a dark page; the card stays white). |
| Approach | **A**: plain `three` + a TypeScript port of the skill's Three.js kit (not React Three Fiber). |

Assumed, not asked: the "welcome page" is `AppSplash`'s intro mode, not `website/index.html`
(a gitignored draft for another brand, "MSquare").

## Current state (read 2026-10-02)

- `AppSplash.tsx`: signed-out boot shows `sonalim-erp-splash.webp` (static raster, fade-in) for
  2.3 s; a restored session shows `BrandLoader` for ≥ 0.9 s. The splash is a fixed overlay
  above `RouterProvider`, so for a signed-out visitor the login page is already mounted under it.
- `LoginPage.tsx`: light page (`.theme-login`, `#EEF3F9` + soft radial glows, three blurred
  Framer Motion blobs), a glass card `bg-white/75 backdrop-blur-xl` split into a navy brand
  panel (`#071F43` + gradients + a light sweep, 2D `LogoMark` tile, `BrandWordmark`, tagline,
  title, three features; hidden below `md`) and a form side (gradient tile with a white
  `LogoMark`, wordmark, form).
- `Sidebar.tsx` and the mobile header in `AppLayout.tsx` show a 32 px gradient "SE" text badge.
- `frontend/index.html` has no favicon; there is no `frontend/public/`.
- The frontend has no 3D dependency. Vitest is set up (`npm test`).
- The plant's products (`backend/scripts/seed_client_product_list.py`): Spaghetti 1.2 (Pasta
  Douman / Prima), Coquillettes N°4/6/7, Torsadés, Vermicelles (also Escargots, Anneaux).

## 1. The look: "pasta world"

Brand rules come from the skill's saved profile `videos/BRAND.md` (palette, gold as the one
highlight, Inter, the logo build) and do not bend.

- **Stage.** Deep navy `#071F43`, fog into depth, a soft gold glow behind the logo (the splash
  art's mood), the kit's studio environment light. Background and fog are set to the inverse
  ACES value of `#071F43` (`untone`, a trap measured in `BRAND.md`) so the canvas edge is
  exactly the CSS navy around it and under the fallback poster.
- **Logo.** The current mark as polished gold "wire": ring → torus; each glyph stroke → a
  round-capped tube along its SVG path. Slight tilt, slow turn, no particles on it.
- **Semolina.** Fine gold grains (soft sprites). A few catch the light and glow: with the
  logo's highlight, the only things that cross the bloom threshold.
- **Pasta**, procedural:
  - spaghetti 1.2: long thin rods, some gently bowed;
  - coquillettes: short curved hollow tubes;
  - torsadés: twisted helix;
  - vermicelles: fine short strands.

  Satin material (dry-pasta sheen) in the brand's gold ramp `#F5A900` → `#FFD45A`. No new
  colours: pasta reads as pasta through shape and sheen.
- **Type** stays HTML: `BrandWordmark` and the tagline, never 3D text.
- Kit settings kept from the skill's traps: bloom threshold 1.0, environment intensity ≈ 0.55,
  exposure ≈ 0.95, only "glow" materials bloom.

## 2. Welcome intro (signed-out boot only)

The clock starts on the **first rendered frame**; until then the overlay is plain navy with the
CSS gold glow. Total ≈ 4.0 s.

| Time (s) | Beat | What happens |
|---|---|---|
| 0.0–1.2 | Semoule | A stream of gold semolina grains spirals in from the depth (the splash art's wave), camera close and drifting. |
| 1.2–2.4 | Pâtes | Grains condense into pasta pieces: grains rush to each piece's surface, the piece appears, grains fade. The four shapes tumble outward into an orbit. |
| 2.4–3.3 | Logo | The ring draws clockwise from the top (the official `logo-mark.svg` build), the wheat glyph rises into it; one bloom flash when the ring closes; pasta settles into a slow orbit. |
| 3.0–3.6 | Wordmark | `SONALIM ERP` + "PRODUCTION • QUALITÉ • PERFORMANCE" (HTML) fade up under the logo. |
| 3.6–4.0 | Handoff | Wordmark and tagline fade, the camera eases back, the splash overlay starts its existing 0.4 s exit at 3.6, the login card rises (its existing entrance) and the 3D logo flies into its login slot (§3). |

- **Skip:** click, tap or any key fast-forwards to the handoff pose (t = 3.6) in 0.3 s, then the
  handoff plays. A small "Passer / Skip" hint bottom-right (new i18n key, en + fr).
- A restored session keeps today's `BrandLoader` refresh path: signed-in users never download
  the 3D chunk.

## 3. Login page

- **Page:** `.theme-login` becomes navy `#071F43` (the base under the canvas and the poster).
  The three blurred blobs and the brand panel's light sweep are removed: the 3D scene replaces
  them.
- **Idle scene:** pasta drifts on lazy orbits through the depth (a tumble ≈ every 20–40 s),
  semolina dust floats slowly upward. Pointer parallax: camera ± 2–3°, eased; none on touch.
- **Desktop (`md`+), the brand panel becomes a window into the scene:** its navy fill and
  gradients go; a navy scrim (≥ 80 % `#071F43`) sits under the title block and the feature
  list so white text keeps ≥ 7:1 contrast whatever passes behind (white on 80 % navy over
  `#FFD45A` ≈ 10:1; the gold tagline ≈ 5:1). The live 3D logo floats in an empty **slot**
  `div` next to the wordmark, replacing the 2D tile.
- **Form side:** white at 95 % (`bg-white/95`), **no `backdrop-filter`**:
  blurring a live canvas re-composites every frame. The small tile above the form shows the
  baked 3D logo image (§5).
- **Phones (< `md`, no brand panel):** the scene fills the screen around the card; the live
  logo hovers in a hero slot above the card; the intro's last beat flies the logo there.
- **Slot placement:** the stage reads the active slot's `getBoundingClientRect()` each frame
  (one element, so cheap; it follows the card's entrance animation and any resize) and places
  the logo so its projection fills the slot at a fixed depth.
- **Reached without the intro** (after logout, or a direct visit later in the session): the
  poster shows first, the live scene crossfades in when its first frame is ready, and the logo
  plays the ring-draw build in its slot.
- **After a successful login** the stage is disposed (geometries, materials, textures,
  renderer), and the app runs exactly as today.

## 4. Architecture

New dependency: `three` (+ `@types/three`, dev). New folder
`frontend/src/components/patterns/brand3d/`, next to `AppSplash` and `BrandLoader`:

| File | Responsibility | WebGL? |
|---|---|---|
| `kit.ts` | Port of the parts of the skill's `kit/three.js` used here: stage (renderer, ACES, env, bloom composer, `untone`), `mat()` presets, seeded random, brand easing `bezier(0.22, 1, 0.36, 1)`, clamp/lerp. | yes (stage) |
| `logo.ts` | Builds the 3D logo from `logo-mark.svg` imported as raw text (`?raw`), parsed with three's `SVGLoader`: the `<circle>` → torus, glyph paths → tubes. The 3D follows the SVG file. Ring draw via `setDrawRange`. | yes |
| `pasta.ts`, `semolina.ts` | Procedural geometry; one `InstancedMesh` per pasta shape, one `Points` for grains (≈ 6 draw calls in all). | yes |
| `timeline.ts` | Pure functions: intro time → beat state (grain / piece progress, ring draw, wordmark opacity, camera pose), skip mapping, idle drift. | no |
| `quality.ts` | Pure: quality tier from measured frame times; slot rect → world position and scale. | no |
| `world.ts` | Assembles the scene; API `frame(t)`, `setMode("intro" \| "login")`, `setSlot(rect \| null)`, `setPointer(x, y)`, `setQuality(tier)`, `resize(w, h)`, `dispose()`. Loaded via dynamic `import()` → its own chunk with `three`. | yes |
| `stageStore.ts` | Small external store (`useSyncExternalStore`): intro active / clock / skip, login mounted, active slot element. | no |
| `BrandStage.tsx` | The one fixed full-viewport canvas (`z` under the splash overlay and the login card), mounted once in `App.tsx`. Renders while the intro is active or the login page is mounted; owns the rAF loop, visibility pause, idle stop, quality tiers, resize, poster fallback and crossfade. | owns it |
| `bake.ts` + `frontend/bake-brand.html` | Dev-only bake page (§5). | yes |

Wiring:

- `App.tsx` mounts `<BrandStage />` next to `AppSplash`.
- `AppSplash` intro mode: preloads the `world` chunk at boot, becomes a transparent overlay
  holding only the wordmark, tagline and skip hint, and drives the intro clock through the store.
  The current `Intro` raster component is removed (the splash `.webp` stays on disk as the
  art-direction reference named in `BRAND.md`, no longer imported).
- `LoginPage` registers itself and its slot element with the store on mount and unregisters on
  unmount. Under the splash the login page is already mounted, so intro and login share one
  canvas and one scene: no second WebGL context, no seam at the handoff.
- If the route under the splash is not the login page (a signed-out visitor on a public error
  page), the stage fades out and disposes after the intro.
- Resize: `ResizeObserver` on the viewport → `renderer.setSize` + camera aspect; the camera
  distance is fitted to the narrower axis so portrait screens keep the composition (the kit's
  9:16 "narrow slice" trap).

## 5. Performance and fallbacks

- **Pixel ratio:** `min(devicePixelRatio, 1.5)`.
- **Tiers, measured:** start *high* (bloom, ≈ 1,200 grains, ≈ 60 pieces). Median frame time of
  the first ≈ 60 frames > 22 ms → *low* (no bloom, ≈ 500 grains, ≈ 30 pieces, pixel ratio 1);
  still > 33 ms → *still* (freeze on the current frame).
- **Power:** pause while `document.hidden`; on the login page, after 60 s without pointer or
  keyboard input the motion eases to a stop, any input resumes it.
- **Fallback poster** (baked from the same scene, landscape + portrait WebP, `object-cover`) when:
  `prefers-reduced-motion`, WebGL unavailable or context creation fails, context lost, or the
  chunk + first frame not ready within 1.5 s of the intro start. The intro then plays as poster
  + wordmark, same length, still skippable. The login page shows the poster as its background.
- **Download:** the `three` chunk (≈ 150–180 KB gzipped) loads only for signed-out visitors
  (intro) or on the login page; the main bundle does not grow.

## 6. Baked assets (same 3D model)

`frontend/bake-brand.html` (dev only: `vite build` uses `index.html` alone, so it never ships)
renders the 3D logo and the scene at exact pixel sizes on a transparent background; the PNGs
and WebPs are captured with headless Chrome and committed. The page stays in the repo so the
images can be re-baked if the logo changes.

| Asset | Sizes | Path | Replaces / used by |
|---|---|---|---|
| 3D logo tile (navy rounded square, gold 3D mark) | 64, 96 px (32 px at 2x/3x) | `frontend/src/assets/icons/brand/logo-3d-{64,96}.png` | "SE" badge in `Sidebar.tsx` (open + collapsed) and the `AppLayout.tsx` mobile header |
| Same tile, larger | 88, 132 px (44 px at 2x/3x) | `frontend/src/assets/icons/brand/logo-3d-{88,132}.png` | Gradient tile above the login form |
| Favicon | 16, 32 px | `frontend/public/favicon-{16,32}.png` | none today; linked from `index.html` |
| Apple touch icon | 180 px | `frontend/public/apple-touch-icon.png` | none today |
| Posters | landscape 1920×1080, portrait 1080×1920, WebP | `frontend/src/assets/animations/sonalim-stage-{landscape,portrait}.webp` | Fallback only (§5) |

`frontend/public/` is new; the Docker build copies the whole folder (`COPY . .`) and nginx's
`try_files` serves root files, so no deploy change.

## 7. i18n

One new key for the skip hint (en "Skip", fr "Passer"), both languages in `lib/i18n.tsx`.
The `sr-only` "starting up" text and the login copy are unchanged.

## 8. Testing and verification

- **Vitest (no WebGL):** `timeline.ts` beat states at chosen times, the wordmark window, skip
  reaching the handoff pose in 0.3 s; `quality.ts` tier choice from frame-time samples and slot
  rect → world position/scale; seeded random repeatability; the SVG parser finds the ring and
  the 4 glyph strokes of `logo-mark.svg`.
- **Types:** `tsc -b --force`.
- **Browser** (private headless Chrome; the worktree is shared): intro stills at 0.6 / 1.8 / 2.9
  / 3.8 s, skip, login at desktop / tablet / phone widths, reduced-motion emulation, WebGL
  disabled (→ poster), text never covered by the scene, frame times logged. Headless Chrome
  uses software GL, so it should land on the *low* tier: that exercises the degrade path; real
  frame rates are checked on a GPU machine.
- **Bundle:** `vite build` shows `three` in its own chunk; the entry chunk size unchanged.
- **Checkpoint with the user** (the skill's "3 style frames"): stills of the intro's semolina
  beat, the logo beat and the login page before final polish.

## 9. Skill memory

Add to the skill's `videos/BRAND.md` (outside this repo): the 3D logo (gold wire build from
`logo-mark.svg`), the pasta world and its shapes, and the in-app live-3D choice, so future
films reuse them.

## Out of scope

- The "MSquare" website draft (`website/index.html`).
- Pre-rendered video.
- `BrandLoader` and the signed-in refresh path.
- A PWA manifest and 192/512 icons (no manifest exists; can follow with the native apps).

## Risks

- **Weak factory GPUs.** Mitigated by the measured tiers, the idle stop and the poster; the
  login page stays usable at any tier because the scene is behind the card.
- **Slot tracking during the card's entrance.** Reading one rect per frame keeps the logo glued
  to the card; checked in the browser stills.
- **Legibility of the mark at 16–32 px.** The hand-drawn glyph is thin; the bake renders the
  ring and tubes thicker at small sizes if the 32 px still reads as a blur (checked on the baked
  files before wiring them in).
