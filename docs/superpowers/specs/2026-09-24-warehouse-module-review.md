# Warehouse (Entrepôt) module review

**Date:** 2026-09-24
**Scope:** `backend/modules/warehouse`, `frontend/src/features/warehouse`, product pickers across the SPA.

## What the module did well before this review

- Stock is a ledger, not a number: every change is a `stock_moves` row with a type, a reference, an actor and, since phase 5, the report/OF that caused it.
- Three buckets per product and location (on hand, reserved, in production) with domain rules that refuse a reservation above availability while still letting a validated production report drive on-hand negative.
- Blocked locations model quarantine honestly (goods on the books, never promisable).
- Lots with DLC, a state machine, and a per-lot stock table.
- Landed-cost analysis (procurement) and finished-goods analysis (production) are surfaced in the warehouse screen.

## Gaps found

| Gap | Effect on the floor | Addressed |
|---|---|---|
| No KPI view: nothing said what the stock is worth, how many days of semolina or film are left, what sits unused, how often the books had to be corrected. | The manager reads the raw stock table and guesses. | **Yes** — Overview tab + `GET /warehouse/analytics/overview`. |
| Product dropdowns listed the entire catalog everywhere (reserve, adjust, sales lines, purchase lines, packaging BOM). | Picking a carton meant scrolling past every pasta and film reel; wrong picks. | **Yes** — shared `ProductSelect` grouped by category and packaging kind, with per-field filters. |
| Category lived only in Production > Product classifications; the product wizard never asked for it. | New products were unclassified by default and so appeared in every list. | **Yes** — category and packaging kind on the product wizard and edit dialog, category badge and filter on the product list, category filter on the stock table. |
| Movement history had no date filter. | Any period analysis pulled 5,000 rows to the browser. | **Yes** — `date_from`/`date_to` on `GET /warehouse/stock/moves`. |
| Stock value had no backend definition. | Every screen recomputed cost differently. | **Partly** — the overview values stock at the catalog purchase price and says which products have none. Landed-cost (weighted average of receipts) stays on the Stock tab. |

## KPIs now available (`/warehouse/analytics/overview`)

All quantities stay in the product's unit; only value (F CFA) and counts are summed.

- **As of today:** stock value at purchase cost, products below their minimum, products with under 7 days of cover, dormant products (no movement for 60 days), products in quarantine, negative stock lines, lots expiring within 30 days or expired, products in stock.
- **Over the period:** received / issued per unit, movement count, manual correction count, daily received-vs-issued series per unit.
- **Per product:** on hand, blocked, reserved, in production, minimum, average daily consumption, days of cover with a status (out / critical / low / ok / idle), last movement and idle days, dormant flag, consumed / received / corrections in the period, value.
- **Lists:** manual corrections with reason and actor; active lots close to or past their DLC with the quantity still on hand.

Rules live in `modules/warehouse/domain/analytics.py` (pure, tested) so the thresholds are one place to change.

## Recommended next steps (not done here)

1. **Promote the category to the product master.** `production.product_classifications.category` is a catalog attribute (SAP material type, Odoo product category). Today the frontend joins it; a `core.products.category` column with a backfill from production would let the warehouse backend filter and aggregate by category, and let sales/procurement enforce "only finished goods on a sales line" server-side.
2. **Physical inventory / cycle counts.** A count sheet per location (expected vs counted, variance, one adjustment per line posted on validation) replaces ad-hoc adjustments and makes the correction KPI meaningful.
3. **Reorder policy per product.** Minimum exists; add a reorder quantity and lead time so the "below minimum" alert can propose a purchase order quantity (the Analysis tab already creates one).
4. **Location types.** Tag locations as raw-material store, packaging store, finished-goods store, quarantine, so the stock table can group by area and the picker for a transfer destination only offers sensible targets.
5. **Valuation method.** Choose one (weighted average at receipt is the natural fit, the data is already in procurement) and post it to finance on each movement.
6. **Stock export.** A CSV/XLSX export of the stock table and of the overview product table for the monthly count and the auditor.
7. **Per-location KPIs.** The overview is plant-wide; a location switch is a small addition once location types exist.
8. **Retire the legacy History tab** (material receipt history) once procurement's receipt history covers it; it is the one tab that still talks about the dropped `material_receipts` table.
