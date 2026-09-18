# Sonalim ERP SVG asset rules

## Core rule

When a UI task includes an uploaded SVG, always prefer the uploaded SVG file over generating a new illustration or recreating it from scratch, unless the design specifically asks for a new asset. Before choosing a component, think through where the asset belongs in the app and use the existing structure of the project.

## Correct asset placement

Use the existing asset folders and keep each SVG in the matching category:

- `frontend/src/assets/icons/` for UI icons, navigation icons, status icons, and compact action symbols.
- `frontend/src/assets/illustrations/` for empty states, auth screens, dashboard illustrations, error screens, and explanatory visuals.
- `frontend/src/assets/animations/` for splash screens, loaders, motion-based branded graphics, and animated status visuals.
- Do not place raw SVGs directly inside feature components unless they are truly local to that component and the project already uses that pattern.

### Naming guidance

- Keep names descriptive and application-specific.
- Prefer clear names such as `empty-no-orders.svg`, `secure.svg`, `sonalim-erp-loading.svg`, `warehouse.svg`.
- Match the existing naming pattern in the repo and keep the same visual category.

## Import and usage rules

- Prefer the existing project convention: import SVGs as React components using `?react`.
- Keep the uploaded SVG’s original proportions and viewBox unless the UI specifically requires a new crop or composition.
- Respect the original colors, strokes, and motion style from the uploaded asset.
- Reuse the same animation behavior already present in the project: subtle fade, scale, pulse, and slow motion loops in a polished, restrained way.
- If the SVG already contains embedded animation (`@keyframes`, transform-based motion, stroke animation), keep it unless the design requires a different behavior.
- If the animation is controlled by Framer Motion in the component, keep the wrapper animation subtle and consistent with the existing app design language.

## Visual consistency rules

- Follow the brand style already used in the app: deep navy, gold accents, soft borders, and clean UI proportions.
- Keep the same level of polish as the current app assets; do not make the SVG feel heavier, noisier, or more decorative than the rest of the UI.
- Preserve the intended hierarchy: promotional brand splash visuals should feel premium, while utility icons and empty-state illustrations should stay simple and readable.
- Use whitespace intentionally around the SVG so it sits comfortably in the layout and does not crowd surrounding text or controls.

## Sizing guidance for the best fit

Use these suggested size ranges to keep each SVG visually balanced in the app:

- Small utility icons: 16px to 24px
- Navigation and compact toolbar icons: 20px to 28px
- Primary action icons in cards or panels: 28px to 40px
- Empty-state and illustration blocks: 220px to 420px wide
- Auth and feature hero illustrations: 240px to 360px wide
- Full-screen splash screens: 100vw x 100vh or a full viewport-safe covered panel
- Loader/branding animation blocks: 120px to 220px for centered loading states

### Best-fit rule

- Keep the SVG within its container without stretching.
- Match the container size to the asset’s natural aspect ratio.
- If a square SVG is used in a square container, keep it visually centered and proportional.
- If a wide illustration is used, allow it to remain wide and avoid forcing it into a square box.
- Larger screens can use slightly larger assets, but avoid oversized visuals that overpower the UI.

## Default behavior for future AI work

When asked to place or update an SVG:

1. Determine the correct asset category first.
2. Choose the closest existing folder and naming pattern.
3. Use the uploaded SVG instead of recreating it from scratch.
4. Keep the same animation language and motion timing.
5. Size the asset to match the screen context and maintain clean visual balance.
6. Prefer the app’s existing styling tokens and color palette.
7. If the uploaded SVG does not fit a container cleanly, adjust the wrapper size rather than altering the SVG’s visual intent.

## Examples from this project

- `sonalim-erp-loading.svg` belongs in `frontend/src/assets/animations/` and is best displayed inside a centered motion container with a controlled loader size around 180px to 220px.
- `empty-no-orders.svg` belongs in `frontend/src/assets/illustrations/empty-states/` and is best shown around 240px to 360px when used in empty state panels.
- `warehouse.svg` and similar icons belong in `frontend/src/assets/icons/...` and should usually render around 20px to 28px in navigation and action buttons.

This guidance should be followed for all future frontend SVG additions and replacements in Sonalim ERP.
