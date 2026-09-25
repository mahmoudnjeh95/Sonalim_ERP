---
name: erp-frontend-stack
description: Recommended frontend technology stack and architecture guidance for building a full ERP (Enterprise Resource Planning) web application with a React-strong team. Use this skill whenever the user is starting, architecting, or making technology-choice decisions for an ERP, back-office, or large-scale internal business application — covers framework, state management, UI/component libraries, data tables, forms, and monorepo/module-federation architecture for scalability and performance. Trigger on mentions of "ERP", "enterprise app", "dashboard at scale", "back-office system", or requests to choose a frontend stack for a large, multi-module business application. Also holds Sonalim UI conventions — use it when adding or changing a module page's tab bar / page header layout (sticky tab bars).
---

# ERP Frontend Stack

Guidance for choosing and structuring a frontend stack for a full ERP application, optimized for professional UX, large-scale data, and long-term performance. Assumes a team with strong JavaScript/React experience.

## Core Framework

- **Next.js (React) + TypeScript**
  - TypeScript is treated as non-negotiable at ERP scale — hundreds of forms, data models, and modules make type safety essential for avoiding entire classes of bugs.
  - Next.js provides file-based routing, API routes, and flexible rendering (SSR for data-heavy pages, static rendering for docs/help pages).

## State & Data Layer

- **TanStack Query (React Query)** — server state management: caching, background refetching, optimistic updates. Essential for ERP's constant data syncing across modules.
- **Zustand** or **Redux Toolkit** — client state (UI state, filters, multi-step forms). Zustand for simpler needs, Redux Toolkit if the team wants more structure/conventions.
- **Zod** — schema validation, shared between frontend forms and API contracts, keeping validation consistent across the stack.

## UI / Component Layer

- **shadcn/ui + Tailwind CSS** — full control over components, since ERP UIs require heavy customization of tables, forms, and modals for business workflows. Avoids fighting a black-box component library.
- **TanStack Table** — critical for ERP: handles massive datasets, virtualization, sorting/filtering/grouping without performance degradation.
- **React Hook Form** — ERP means large, complex forms; this is the performance-friendly standard for form state management.

## Sonalim UI Conventions

### Sticky page tab bars

The top-level tab bar of a module page stays pinned to the top of the viewport while the user scrolls, so they can switch tabs without scrolling back up.

- Wrap the bar in `StickyTabBar` (`frontend/src/components/patterns/StickyTabBar.tsx`). It adds `sticky top-0 z-20` and a translucent `bg-background/85 backdrop-blur-sm`, so content slides underneath without clashing.
- Put `StickyTabBar` as a **direct child of the page's root container** (the `space-y-6` div), between the title block and the tab content. Sticky only works inside its parent, so wrapping only `<Tabs>` inside a small wrapper would pin nothing.
- `<main>` in `routes/AppLayout.tsx` is the scroll container. Don't add `overflow-*` to any ancestor between `<main>` and the bar, because that breaks sticky.
- Grouped bars (for example Analytics' "Production" / "Coûts et prix") put all groups inside one `StickyTabBar className="flex flex-wrap gap-x-6 gap-y-3"`.
- Applied on: Production, Analytics, Warehouse, Quality, Maintenance, Products. New module pages with a tab bar must use it too.
- In-page tables with a sticky header of their own sit under the bar (`z-20`). Keep their z-index below 20.

```tsx
<div className="space-y-6">
  <motion.div>{/* title + subtitle */}</motion.div>
  <StickyTabBar>
    <Tabs value={tab} onValueChange={...}>
      <TabsList>{/* TabsTrigger… */}</TabsList>
    </Tabs>
  </StickyTabBar>
  <AnimatePresence mode="wait">{/* active tab */}</AnimatePresence>
</div>
```

## Architecture for Scale

- **Monorepo (Turborepo or Nx)** — ERP naturally splits into modules (inventory, HR, finance, CRM). A monorepo allows shared types/components while still deploying/versioning modules independently.
- **Module Federation** — for larger orgs, allows different teams to own different ERP modules as separately deployable micro-frontends. Consider this a scaling option, not a day-one requirement.

## Performance Considerations Specific to ERP

- Virtualize all lists/tables (TanStack Virtual) — ERP tables can have 100k+ rows.
- Code-split per module so users loading one module (e.g. Inventory) don't download unrelated module bundles (e.g. Payroll).
- Use optimistic UI updates via React Query to keep the interface feeling responsive despite heavy backend writes.

## Key Early Architecture Decision

Before scaffolding the repo, decide between:
1. **Monolith Next.js app** — simpler to start, single deployable, good for small-to-mid teams.
2. **Micro-frontends via Module Federation** — better for large orgs with multiple independent squads owning separate ERP modules, at the cost of added complexity.

This choice shapes the repo structure from day one, so it should be made explicitly rather than defaulted into.

## Summary Table

| Layer | Recommendation |
|---|---|
| Framework | Next.js + TypeScript |
| Server state | TanStack Query |
| Client state | Zustand or Redux Toolkit |
| Validation | Zod |
| Styling/components | Tailwind CSS + shadcn/ui |
| Tables | TanStack Table + TanStack Virtual |
| Forms | React Hook Form |
| Repo structure | Turborepo or Nx (monorepo) |
| Large-scale option | Module Federation (micro-frontends) |

This stack mirrors what modern large-scale SaaS/ERP platforms use in production (e.g. Linear, Vercel's dashboard, many fintech back-offices), and is chosen for teams that can move fast immediately with strong React/TypeScript experience.
