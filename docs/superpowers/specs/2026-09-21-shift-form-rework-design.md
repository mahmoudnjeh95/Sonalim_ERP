# Shift form rework: lists, columns, derived fields

Date: 2026-09-21. Builds on `2026-09-20-shift-report-core-design.md` (the per-shift report, already built through M5/M6a).

## Why

The client reviewed the shift screen and asked for a set of changes section by section: pick from the right lists instead of free text or everything, drop fields the system can compute or already knows, and let the silo reading drive machine status. The screen still has to mirror the paper fiches in order; nothing here changes the section list or the permission keys.

## Decisions (agreed 2026-09-21)

1. **The line is the header's Ligne.** The shift is already one report per line (poste de charge) and shift. A run or packing row no longer names a machine.
2. **Silo "État de la ligne" drives machine status**, by side and stage, only once the shift is validated.
3. **Packed quantity comes from cartons.** "Conditionné (t)" and "Paquets" are removed from the screen.
4. **Packaging is classified once, stores come from each item.** Dropdowns list items by packaging kind; the store is the item's own default storage location.

## 1. Screen: lists, columns, order

Config lives in `frontend/src/features/production/shift/sectionConfig.ts`, option lists in `useShiftReferenceData.ts`.

| Section | Change |
|---|---|
| Production | OF options: `ongoing` OFs only, regrind OFs excluded (`is_regrind` is already on the work-order list). A row already holding another OF keeps showing it. Machine column removed. "Article rebroyat" lists products classified `finished_good` or `raw_material`. Mold options filtered by the row's OF type. Production's own stores (Magasin rebroyat, Silo/magasin on semoule lines) stay. |
| Pâtes non conformes | "Article perdu": same finished-good / raw-material list. |
| Lavage des moules | Mold options: molds whose `type` equals the type of the OFs in this shift's runs (OF `product_type`, else its product's `product_type`); all molds when the shift has no run yet. |
| Arrêts | Machines: unchanged (already the header line's machines). Column order Type, Système, Motif. |
| État du silo | "État de la ligne" becomes a select: `running` (En marche) / `stopped` (En arrêt). Existing text `En marche` reads as `running`. |
| Conditionnement | Removed: OF, Machine, Conditionné (t), Paquets, Cadence, Magasin emballage, Magasin produits finis. "De la production" is required, lists the shift's runs by product name (plus start time); the OF is taken from the chosen run. "Type de conditionnement" is read-only, shown from the run's product (packaging format + net weight, e.g. "Sachet 500 g"). Type film / carton / bobine / scotch / ruban are selects (2.1), each next to its quantity. |
| Vérification des paquets | Film, soudure longitudinale, soudure verticale, impression: select `good` / `not_good` (Bon / Non bon). A stored value outside the list (e.g. "Faible") still displays until edited. |
| Déchets de conditionnement | Columns: Heure, Type, Quantité (kg), Cause. Article perdu, Lot conditionné and N° lot removed. |

The blank-line and horizontal-progress changes from earlier today are unaffected.

## 2. Backend and data

### 2.1 Packaging kinds
`production.product_classifications` gets `packaging_kind` (`film | carton | bobine | scotch | ruban`, nullable; only valid when `category = 'packaging_component'`), in `validate_classification` and the classification service, with a field in the Classifications tab. The five packing selects list the products of their kind. Unclassified products do not appear until classified (nothing is guessed from names).

Column mapping on `shift_packing_rows` (columns exist, no new ones): film -> `film_product_id`, carton -> `carton_product_id`, bobine -> `tape_product_id` / `tape_quantity`, scotch -> `scotch_product_id`, ruban -> `ruban_product_id`. The free-text `film_type` is no longer written by the screen.

### 2.2 Packets and tonnage
Tonnage is already computed at validation from cartons, net weight and packets per carton (`tonnage_from_count`, `freeze_packaging_parameters`). Add: `packets_counted = (carton_quantity - waste_carton_quantity) x packets_per_carton` when the row has no packets typed, so the board's packet count and the packaging-variance check keep a value. Packing rows keep the columns; the screen no longer sends them.

### 2.3 OF and packing type from the run
On save of a packing row with `run_id`, the service sets `of_id` from the run and `packing_type` from the run's product. A packing row without a run is refused at submit (`RUN_REQUIRED`), since the OF can no longer be typed.

### 2.4 Stores
Filled when the row is saved (`packing_derivation_service.derive_packing_rows`), so the stored row is complete before it is handed in: `finished_goods_location_id` from the run's product `default_location_id`, `packaging_location_id` from the packaging items' `default_location_id` (packaging is taken from one store per row: items with different default stores are refused on save with `PACKAGING_STORES_DIFFER`). A row that already carries a store, or packets, keeps them. A missing default is not refused on save (a draft may be saved); `check_ready_to_submit` refuses the hand-in with `NO_DEFAULT_LOCATION` and says to set the default on the product or item. The screen does not send the derived fields back (`serverDerived` in the section config), so they follow the row on every save.

### 2.5 Machine for Analytics
Machine performance needs a machine on each validated report. `legacy_report_ledger.materialize_shift` fills `equipment_id` when the run/packing row has none: a run gets the line's `extrusion` machine, a packing row the line's `conditionnement` machine, only when the line has exactly one machine at that stage (`maintenance.equipment.production_stage`). Otherwise it stays empty. Read through `EquipmentService`, as the board does.

### 2.6 Silo -> machine status
After a shift validates (`shift_validation_service`), if no later shift on the same line is already validated:
- take the shift's `end` silo readings per side;
- side `production` -> line machines with stage `versement` and `extrusion`; side `packing` -> stage `conditionnement`;
- `stopped` -> `EquipmentService.transition_status(..., "down")`; `running` -> `"operational"`;
- a machine in `maintenance` is left alone (the transition table forbids it anyway); an invalid transition is skipped, not an error;
- each change is audited by the existing `equipment.status_changed` record. Reversing a shift does not undo it.

Production calls maintenance in process, the same dependency the dashboard already has (`module.json` unchanged). The state is stored as `running` / `stopped`; migration `0053` turns the old typed `En marche` / `En arrêt` into those codes. The work-order list already carries `is_regrind` (OFs with a `regrind_batches` row), so no backend change was needed for the OF filter.

### 2.7 Packet checks and waste
No schema change: `film_state`, `long_weld`, `vertical_weld`, `date_print` stay text and now receive `good` / `not_good`. Packing waste keeps `product_id`, `packing_row_id`, `lot_number` columns; the screen stops sending them. Waste lines do not move stock, so nothing in stock posting changes. Packing waste no longer has to name an item: `validate_conditionnement_stock_targets` no longer applies the waste-item rule (production waste still must name one).

## 3. Not in scope
- The board / Analytics design (live current shift, stops from `machine_stops`) is parked, not part of this.
- Production's stores, energy, staffing and the semoule child table are unchanged.
- No backfill of old rows: converted history keeps its values.

## 4. Testing
- Backend integration tests (real DB, existing pattern): packets derivation; OF/packing type from run and `RUN_REQUIRED`; store defaults and `NO_DEFAULT_LOCATION`; machine fill by stage (one / none / several); silo rule (stopped, running, `maintenance` untouched, later shift already validated, no reading); `packaging_kind` validation; packing waste needing no item; derived figures following the row across saves.
- Frontend: `npx tsc -b --force`, then each section driven in a real browser in French (no frontend test runner exists).
- Full backend suites for production, warehouse, maintenance stay green.

## 5. Risks
- Default storage locations and classifications were loaded from the client's sheet on 2026-09-21: all 52 products now have a `default_location_id` (30 Entrepôt Produits Finis, 22 Matières premières) and a category (30 `finished_good`, 22 `raw_material`; none `packaging_component`). Validating a packing row still fails with `NO_DEFAULT_LOCATION` for any product added later without one. Deliberate: no guessed store.
- Film, carton, scotch and ruban items are currently `raw_material`, so until they are set to `packaging_component` with a `packaging_kind` (2.1) they appear in the "Article rebroyat" / "Article perdu" lists and not in the packing dropdowns. Classifying them is a data step after 2.1 ships (Classifications tab), listed in the plan.
- Machine performance on lines with several machines at one stage loses per-machine attribution for runs and packing rows (stops keep theirs).
- `RUN_REQUIRED` applies when a packing section is submitted. Shifts already validated are not re-submitted, so history is untouched; still-open shifts whose packing rows have no run must get one before hand-in, and existing tests that submit a packing row without `run_id` are updated in the same change.
- Silo status can overwrite a status Maintenance set (`down` -> `operational`); the report is treated as the newest word from the floor, and every change is audited.
