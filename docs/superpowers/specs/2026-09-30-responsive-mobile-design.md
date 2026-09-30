# App-wide responsive / mobile support — design

Date: 2026-09-30
Status: draft, awaiting review

## Goal

Make every screen of the Sonalim ERP frontend usable on a phone, and fix the number
overflow that clips KPI figures on ordinary laptop widths today.

Two user decisions frame this design (2026-09-30):

1. **Every screen must work on a phone** — not a curated subset. All 46 pages, 64 tables
   and 95 dialogs are in scope.
2. **Large figures shrink to fit, never round** — the exact number and its unit stay
   visible at every width. No compact notation ("79,5 M"), no truncation, no tooltip
   standing in for the value. This follows the existing rule that a displayed figure must
   be the recorded figure.

Forward-looking constraint, stated by the user: **native Android/iOS apps will be
generated from this application later.** This design does not build them, but it avoids
choices that would have to be undone — see "Native-app readiness".

## Inventory (measured, 2026-09-30)

- 246 `.tsx` files under `features/`, 46 `*Page.tsx`, 64 files rendering `<Table`,
  95 rendering `<Dialog`.
- Responsive coverage is effectively unstarted: **14 `md:` occurrences across 10 files**
  in the whole app (plus ~130 `sm:`, 68 `lg:`, 30 `xl:`, mostly stat-grid column counts).
  Neither `routes/AppLayout.tsx` nor `components/ui/dialog.tsx` contains a single
  breakpoint — confirming Parts 1 and 3 are greenfield rather than rework.
- `index.html` already ships the correct `width=device-width` viewport meta. Nothing at
  the browser level is fighting mobile layout.
- The shell (`routes/AppLayout.tsx`) is a fixed two-column flex: `Sidebar` is `w-64`
  (`w-16` collapsed) with `shrink-0`, `<main>` is `px-8 py-8`. It never collapses, so on a
  390px phone the sidebar occupies roughly two thirds of the screen.
- `components/ui/table.tsx` already implements `fitToWidth`: proportional shrink with a
  **per-column** floor (`minWidth`, default 72) and redistribution, driven by a
  `ResizeObserver`, falling back to horizontal scroll. This is sound and is kept.
- **83 files define columns declaratively** through `ColumnDef<Row>`
  (`lib/useTableColumns.ts`): `{ key, header, cell, defaultWidth?, minWidth?,
  alwaysVisible?, hiddenByDefault?, filterCell?, sortValue? }`. 54 files render through
  the shared `ResizableTableHead`. **68 files already declare `alwaysVisible`.**
- Column visibility and widths are **per-user and server-backed**
  (`core.user_table_preferences`, GET/PUT `/core/table-preferences/{tableKey}`).
- `lib/api.ts` reads `BASE_URL` from `import.meta.env.VITE_API_BASE_URL` — already
  environment-driven.
- Auth session lives in `sessionStorage` (`lib/auth.tsx`); language in `localStorage`
  (`lib/i18n.tsx`); weight unit likewise.

### The overflow bug, measured

`components/patterns/StatCard.tsx` lays out `Card(flex) > [icon(shrink-0), textDiv]`. The
text div has **no `min-w-0`**, and the figure is a single nowrap line. A flex item's
automatic minimum size is its content, so the text div refuses to shrink and the figure
**spills past the card's right edge** instead of being compressed — the clipped `XOF` in
the reported screenshot.

Reproduced headlessly with the real markup and the reported CRM values
(`79 491 700`, `24 349 710`, `4 040 500`, `27,3`, `1 346 833`) in the page's
`grid-cols-1 sm:grid-cols-2 lg:grid-cols-5`, measuring spill past the card's padding box:

| Viewport | Card width | Worst spill |
|---|---|---|
| 1536 | 234px | +1px (borderline) |
| **1366** | 200px | **+35px** |
| **1280** | 182px | **+52px** |
| 1024 (2-up) | 346px | none |
| 390 (1-up) | 358px | none |

So this is deterministic, not incidental: **every 1366px and 1280px laptop clips the CRM
KPI row today**, and 1536px only just escapes. Narrow phones are unaffected because the
grid drops to one column. The fix is therefore valuable on desktop independently of any
mobile work, which is why it ships first and alone.

## Principles

1. **Never hide a number to make it fit.** Shrink the type, wrap the layout, or give the
   card more room — but the recorded figure and its unit always remain readable.
2. **Extend shared primitives; do not fork per page.** The leverage here is that
   `ColumnDef`, `Table`, `Dialog` and `AppLayout` are already shared. Mobile behaviour
   belongs in those files, not in 46 page-level rewrites.
3. **Desktop behaviour is unchanged.** Every change is additive below a breakpoint. At
   `md` and above the rendered output should be identical to today.
4. **Stored desktop preferences must not leak onto phones.** Column widths and
   visibility are per-user and persisted; replaying them on a 390px screen would produce a
   broken view. The mobile renderer ignores stored widths and `hiddenByDefault`.
5. **Each part is independently shippable and reviewable.** Work can stop after any part
   with the app in a better state than before.

## Breakpoint contract

Tailwind defaults, with one decision recorded: **`md` (768px) is the desktop/mobile
divide.** Below `md` the app is in "mobile" layout (drawer nav, card lists, sheets); at
`md` and above it is exactly today's app. `sm` is not used as a structural divide, because
the existing 130 `sm:` utilities are stat-grid column counts and re-purposing them would
change desktop output.

A single source of truth, `useIsMobile()` (matchMedia on `max-width: 767px`), backs the
JS-side decisions so that the CSS breakpoint and the component logic cannot drift.

## Part 0 — StatCard fits its number (ships first, standalone)

Two changes in `components/patterns/StatCard.tsx`:

- Add `min-w-0` to the text wrapper (and `min-w-0` on the card's flex row) so the text
  participates in shrinking instead of overflowing.
- Auto-fit the figure: measure the rendered figure against its container and step the
  type down `text-2xl → text-xl → text-lg` (24 → 20 → 18px) until it fits, via a
  `ResizeObserver`. Below the smallest step the unit wraps to its own line rather than the
  figure being cut. The label keeps `truncate` with a `title` for its full text.

The animated count-up is preserved. `value === null` still renders `—`.

Acceptance: at 1280, 1366 and 1536px the five CRM cards show the complete figure *and*
the `XOF`/`%` unit, with zero spill past the card. Verified by the same headless
measurement used to find the bug, plus a unit test on the step-down helper.

## Part 1 — Responsive shell

`routes/AppLayout.tsx` and `routes/Sidebar.tsx`:

- Below `md`: `<main>` becomes full width, padding `px-8 py-8` → `px-4 py-4`, and the
  `max-w-6xl` content wrapper is unconstrained.
- The sidebar becomes an off-canvas drawer: hidden by default, slid in over a scrim by a
  new mobile top bar (brand, page title, hamburger, language toggle). It closes on route
  change, on scrim tap and on `Escape`; focus is trapped while open and returns to the
  toggle on close.
- The existing `w-16` collapse and its `sonalim-erp.sidebar-collapsed` preference stay
  desktop-only and are not consulted on mobile.
- `StickyTabBar` keeps working; it gains horizontal scroll with momentum on mobile so
  module tab rows do not wrap into an unusable stack.

Acceptance: at 390px every route renders with no horizontal page scroll and no element
overlapping the viewport edge; the drawer opens, navigates and closes correctly.

## Part 2 — Responsive data tables (the long tail)

A new `components/patterns/ResponsiveTable.tsx` wrapping the existing table. At `md`+ it
renders exactly today's `<Table>`. Below `md` it renders a **card list built from the same
`ColumnDef[]`**, so no page duplicates its column logic:

- Columns marked `alwaysVisible` (already present in 68 files) form the card's title and
  subtitle.
- Remaining visible columns render as label/value rows inside the card, using each
  column's existing `cell` renderer — so badges, formatted quantities and actions keep
  working untouched.
- Stored widths are ignored entirely; `hiddenByDefault` columns stay hidden; the
  column-visibility menu is hidden on mobile (it has no meaning for a card list).
- Sorting stays available via a compact control using existing `sortValue`; per-column
  filter cells collapse into a single filter sheet.

An optional `mobilePriority?: number` is added to `ColumnDef` for tables where
`alwaysVisible` alone picks a poor title. It is optional — omitted, the wrapper falls back
to `alwaysVisible`, then to column order.

Rollout is **table by table**, highest-traffic first (production shift report → warehouse
→ sales/finance → HR → the rest), each adoption a reviewable change. Un-migrated tables
keep today's horizontal-scroll behaviour, which is degraded but not broken.

## Part 3 — Dialogs become bottom sheets

`components/ui/dialog.tsx` is a single shared primitive whose content is
`fixed left-1/2 top-1/2 ... w-full max-w-md`. Below `md` it becomes a bottom sheet:
full width, pinned to the bottom, `max-h-[90vh]` with internal scroll, rounded top
corners, and safe-area inset padding. Above `md` it is unchanged.

This one file improves all 95 dialogs at once. Individual dialogs whose *content* is too
wide (dense forms, embedded tables) are fixed in Part 4, not here.

## Part 4 — Per-module passes

Module by module, in traffic order, covering what the shared primitives cannot:

- Form layouts: multi-column grids collapse to one column; touch targets reach 44px;
  numeric fields get `inputMode="decimal"` so the shop floor gets a number keypad.
- Page headers and action rows reflow instead of overflowing.
- Charts (Recharts) get mobile-appropriate heights and reduced tick density.
- The production shift report — the heaviest data-entry screen and the most likely phone
  use — gets explicit attention as the first module.

Each module pass is its own reviewable change. Both i18n keys (en/fr) are added for any
new string, per the project rule.

## Native-app readiness (not built here)

Recorded because the user intends to generate Android/iOS apps later; each item is a thing
this design deliberately does not make worse:

- `BASE_URL` is already env-driven, so pointing a packaged app at a server needs no code
  change.
- **Auth in `sessionStorage` is the one real blocker.** A native shell has no
  tab-close semantics, so a session stored there behaves unpredictably. Migrating to a
  token store behind a small interface is out of scope here and should be its own task,
  but no new `sessionStorage` coupling is introduced by this work.
- Bottom sheets, drawer nav and card lists are the interaction patterns native shells
  expect, so Parts 1–3 move toward that target rather than away from it.
- Safe-area insets (`env(safe-area-inset-*)`) are honoured in the shell and sheets, which
  is what notched devices and native web views need.

Explicitly **not** decided here: whether the native apps are Capacitor/wrapper-based or a
separate React Native client. This design assumes only that the web UI must look right in
a phone-sized viewport.

## Testing

- Unit tests for the `StatCard` type step-down helper and for the `ColumnDef` →
  mobile-card mapping (title/subtitle selection, hidden-column handling).
- Existing table tests (`components/ui/table.test.tsx`) must keep passing unchanged —
  they are the guard that desktop behaviour did not move.
- `tsc -b --force` clean.
- Browser verification at 390px (phone), 768px (breakpoint edge) and 1280/1366px (the
  clipping widths) for each part, using a private headless Chrome profile so concurrent
  sessions sharing this worktree are not disturbed.

## Out of scope

- Backend changes of any kind.
- The native app shells themselves.
- The auth-storage migration (flagged above as its own task).
- Redesigning module information architecture; this is a responsive pass, not a redesign.
- The HR-specific work already specified in `2026-09-29-hr-ui-friendliness-design.md`,
  which stays independent and complementary.
