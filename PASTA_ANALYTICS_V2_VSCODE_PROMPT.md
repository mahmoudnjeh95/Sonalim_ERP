# SONALIM ERP — PASTA MANUFACTURING ANALYTICS V2
## Decision Cockpit implementation prompt for VS Code

Act as a senior frontend architect, product designer, and manufacturing-ERP UX specialist.

This is NOT a generic BI dashboard. The application is an ERP for a PASTA MANUFACTURING FACTORY. Redesign/upgrade the Analytics module around actual pasta-production operations while preserving the existing codebase, routes, APIs, authentication, database model, and visual identity.

## 1. BUSINESS DOMAIN

The analytics module must understand and communicate these concepts:
- Production orders / OF
- Product/reference
- Pasta production lines
- Extrusion/forming
- Drying
- Packaging
- Raw material / semolina / flour
- Packaging material
- Production batches / lots
- Finished products
- Yield
- Material waste
- Broken/rejected pasta
- Quality conformity
- Machine runtime
- Machine downtime
- Machine availability
- Team / shift performance
- Production plan vs actual
- Delays
- Production cost
- Waste cost
- Stock impact
- Traceability

Use terminology already present in the existing application/database. Do not invent a domain term if the project already has an established name.

## 2. ANALYTICS INFORMATION ARCHITECTURE

Use this primary navigation where compatible with the current product:

Overview
Production
Yield & Waste
Machines
Teams / Shifts
Quality
Cost
Stock
Orders
Batch Detail

Each section should have:
- Overview
- Trend
- Breakdown
- Detail

Do not force every subtab if the existing product structure makes a better arrangement. The hierarchy must remain coherent.

## 3. OVERVIEW = MANAGEMENT COCKPIT

The Overview page must immediately answer:
1. Are we producing according to plan?
2. Is yield healthy?
3. Where are we losing material/time?
4. Is quality stable?
5. Which machine/team needs attention?
6. What is the financial impact?

Top KPI row: maximum 5 cards.

Recommended KPIs:
- Production vs plan
- Yield
- Waste rate
- Quality conformity
- Estimated production cost variance

Each KPI:
- current period
- previous period
- target
- variance %
- status
- concise explanation

Example:
"Yield 94.8%"
"−1.6% vs target"
"Main driver: Line 2 / Batch B-104"

## 4. PRODUCTION ANALYTICS

Show:
- planned kg vs produced kg
- OF completion
- production rate
- production by product
- production by line
- production by shift
- delayed OFs

Charts:
- line chart for production trend
- bar chart for line/team comparison
- progress bars for OF completion
- calendar/heatmap for shift performance if data supports it

Smart insights:
- Production gap
- Highest-output line
- Delayed production order
- Biggest negative production variance

## 5. YIELD & WASTE

This is a critical pasta-manufacturing page.

Show the material flow:

Raw material
→ process
→ good pasta
→ rejected/broken pasta
→ waste

KPIs:
- yield %
- waste %
- good output kg
- waste kg
- waste cost

Break waste down by:
- product
- batch
- line
- machine
- shift/team
- waste reason/category

Add:
- target benchmark
- previous period comparison
- top 3 waste drivers
- estimated cost impact

Use the supplied:
`yield-waste.svg`

## 6. MACHINE ANALYTICS

Track where machines affect production.

KPIs:
- availability
- runtime
- downtime
- downtime rate
- production contribution

Where the data supports it, show OEE as:
Availability × Performance × Quality

Do NOT calculate OEE if the required inputs are missing.

Show:
- worst downtime machine
- downtime reasons
- machine trend
- machine comparison
- stoppage duration
- production impact

Use:
`machine-monitoring.svg`
`machine-health-pulse.svg`

Critical machine alert:
"Line/Machine X: 74 min downtime — 41% of total downtime."

## 7. TEAMS / SHIFTS

Compare:
- production
- yield
- waste
- quality
- downtime
- target achievement

Avoid ranking people personally if the system is intended for operational management. Focus on team/shift performance.

Use:
`shift-team.svg`

## 8. QUALITY ANALYTICS

Show:
- conformity %
- rejected quantity
- defect rate
- defects by category
- defects by product
- defects by line
- defects by batch
- quality trend

If actual product-quality parameters exist in the backend, surface them contextually.

Do not invent measurements such as moisture, temperature, thickness, etc. unless they exist in the data model.

Use:
`quality-inspection.svg`
`quality-scan.svg`

Critical quality insight:
"Quality conformity dropped 1.8% vs previous period."
Then show the actual contributing category/batch/line if available.

## 9. COST ANALYTICS

Connect operational losses to money.

Show:
- planned cost
- actual cost
- cost variance
- waste cost
- downtime cost if calculable
- cost per kg
- cost by product/batch

Use a waterfall chart for cost variance.

Use:
`production-cost.svg`

Never fabricate financial estimates. If the required cost inputs are missing, explicitly say:
"Cost impact unavailable — required cost data is not configured."

## 10. STOCK + TRACEABILITY

Analytics should connect:
raw-material lot
→ production order
→ production batch
→ quality result
→ finished-product stock

Use:
`batch-traceability.svg`

Provide drill-down where possible.

Example:
Batch B-104
→ Product P-01
→ OF-2026-184
→ Line 2
→ Shift B
→ Quality result
→ Finished stock

## 11. PRODUCTION ORDER / DELAY ANALYTICS

Show:
- planned start/end
- actual start/end
- delay duration
- completion %
- remaining quantity
- bottleneck if known

Use:
`production-delay.svg`

A delay card must explain the reason when data supports it:
"OF-184 is 3h 20m late — 74 min machine downtime contributed."

## 12. SMART INSIGHT CARDS

Create a reusable component:
`ManufacturingInsightCard`

Types:
- Production gap
- Yield drift
- Highest waste batch
- Highest downtime machine
- Quality drift
- Delayed OF
- Cost variance
- Stock risk
- Best performing team/shift

Each card:
- icon
- title
- value
- variance
- status
- explanation
- recommended action
- drill-down button

Do not call these "AI insights" unless an actual AI service exists.

Use deterministic rules from real ERP data.

## 13. RECOMMENDATION ENGINE

Create a lightweight rules layer.

Examples:

IF yield < target
THEN identify largest contributing line/product/batch
AND recommend drill-down.

IF downtime > threshold
THEN identify machine
AND show downtime reason.

IF quality conformity < target
THEN identify defect category
AND show affected line/batch.

IF production < plan
THEN identify OF/line/shift contributing most.

IF waste cost > threshold
THEN show highest-cost waste source.

Recommendations must always be traceable to real data.

## 14. VISUAL LANGUAGE

This is a pasta factory ERP.

Use subtle visual references to:
- pasta shapes
- production lines
- raw material silos
- extrusion
- drying
- packaging
- batch/lot traceability
- quality inspection

Do NOT turn the UI into a cartoon or food-themed website.

The manufacturing references belong primarily in:
- empty states
- onboarding
- loading
- insight illustrations
- detail pages

The main dashboard should remain professional and executive.

## 15. SUPPLIED ASSET PACK

Use assets from:
`/public/assets/pasta-erp/`

Illustrations:
- production-line.svg
- yield-waste.svg
- quality-inspection.svg
- machine-monitoring.svg
- shift-team.svg
- batch-traceability.svg
- production-delay.svg
- production-cost.svg

Animations:
- production-flow.svg
- kpi-count-up.svg
- machine-health-pulse.svg
- quality-scan.svg
- alert-pulse.svg

Icons:
- production.svg
- yield.svg
- waste.svg
- quality.svg
- machine.svg
- batch.svg
- cost.svg
- shift.svg

Prefer these supplied assets. Do not create duplicate replacement illustrations.

Use Lucide/existing icon system for standard actions.

## 16. MOTION DESIGN

Use Framer Motion if already installed.

Timing:
- micro interactions: 180–220ms
- card transitions: 220–300ms
- page/chart transitions: 280–350ms

Implement:
- KPI cards: fade + 8px upward entrance
- KPI values: subtle number transition
- tabs: crossfade/layout transition
- charts: restrained entrance animation
- rows: hover/selection transition
- insight cards: subtle entrance
- critical alerts: gentle pulse
- drill-down: smooth drawer/panel transition
- filter changes: crossfade
- loading: supplied loading/flow animation

Respect:
`prefers-reduced-motion`

When reduced motion is enabled:
- remove movement
- keep opacity changes minimal
- disable looping pulses

## 17. COLOR SEMANTICS

Preserve existing Sonalim brand colors.

Semantic:
- navy/blue = normal/information
- green = good/positive
- amber/gold = warning
- red = loss/risk

Never communicate status through color alone.
Always include:
icon + label + color.

## 18. EMPTY / LOADING / ERROR STATES

Do not show blank charts.

Use supplied illustrations.

Examples:
No production data:
"Production analytics unavailable for the selected period."

No cost data:
"Cost impact cannot be calculated because cost configuration is incomplete."

No quality data:
"No quality records found for this period."

Loading:
Use supplied animation assets.

Error:
Explain the business impact and provide Retry.

## 19. RESPONSIVE UX

Desktop-first management experience.

At desktop:
- KPI row
- main chart + insight panel
- breakdown table

At tablet/mobile:
- KPI cards become horizontal scroll or 2-column grid
- insight panel moves below chart
- tables become responsive cards where necessary
- filters collapse into a filter drawer

Do not make the dashboard excessively tall.

## 20. COMPONENT ARCHITECTURE

Create/reuse:
- ManufacturingAnalyticsHeader
- PeriodFilter
- ProductionKpiCard
- ManufacturingInsightCard
- StatusBadge
- BenchmarkIndicator
- ProductionTrendChart
- YieldWasteChart
- MachineComparisonChart
- QualityTrendChart
- CostWaterfallChart
- BreakdownTable
- RecommendationPanel
- BatchTraceabilityPanel
- ProductionOrderStatus
- AnalyticsEmptyState
- AnalyticsLoadingState
- DrilldownPanel

Keep calculations in reusable utilities/hooks rather than inside visual components.

## 21. PERFORMANCE

- avoid unnecessary chart re-renders
- memoize expensive calculations
- lazy-load heavy charts if useful
- avoid animating thousands of table rows
- virtualize very large datasets if already supported
- preserve API performance
- do not add unnecessary dependencies

## 22. DATA INTEGRITY

Absolute rule:
NEVER fabricate production, quality, stock, machine, or financial data.

Before implementing a metric:
- inspect the existing API/data model
- identify exact source fields
- calculate only when inputs exist

If inputs are missing:
- do not fake it
- display an explicit unavailable state
- optionally identify which field/configuration is missing

## 23. IMPLEMENTATION WORKFLOW

First inspect:
- AnalyticsPage.tsx
- all analytics components
- chart components
- existing design system
- existing API services/hooks
- production/order/team/machine/quality/stock models
- existing assets
- existing Framer Motion usage

Then:
1. map existing data to manufacturing KPIs
2. build reusable components
3. implement Overview first
4. implement Production
5. implement Yield & Waste
6. implement Machines
7. implement Teams/Shifts
8. implement Quality
9. implement Cost
10. implement Stock/Batch
11. implement Orders
12. add drill-downs
13. add animation polish
14. test all empty/loading/error states

## 24. FINAL QUALITY BAR

The result must feel like:

"A real pasta factory command center."

Not:
- generic admin dashboard
- generic Power BI clone
- decorative food website
- collection of disconnected charts

It should feel:
- industrial
- premium
- calm
- precise
- operational
- management-ready
- data-driven

Most importantly, every important chart should lead to a business conclusion:
WHAT happened → WHY → IMPACT → ACTION.
