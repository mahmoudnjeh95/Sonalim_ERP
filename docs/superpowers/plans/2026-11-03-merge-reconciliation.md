# Merge reconciliation: stock/treasury work vs `origin/huge_production_migration`

> **Status (2026-11-03): the merge is done** on branch `merge/stock-treasury-into-remote` (merge commit `4365f4b`, not pushed).
> - D1 valuation: **FIFO adopted, CMUP dropped.** Valued-stock report: `GET /warehouse/reports/valued-stock`.
> - D2 count: **cycle counts are the model**; freeze + two-count rule being added to them, our inventory feature being removed (in progress).
> - D3: the remote's `valuation.py` / `valuation_service.py` / `test_valuation.py` were taken.
> - D4: still open; belongs to B6.
> - Migrations renumbered: warehouse `0020`, finance `0005`, procurement `0007`/`0008`.
> - The 17 "modify/delete" conflicts were not intended deletions: commit `202eeb9` had accidentally committed 156 working-tree deletions; restored in `2443f86` before merging.
> - The 3 failing assistant tests (remote-branch mismatch) were fixed in `338bbc9`.
> The text below is the analysis written before the merge.

Written 2026-11-03 from a trial merge in a throwaway worktree (nothing in the real tree changed). Local `huge_production_migration` is **30 commits ahead and 343 behind** `origin/huge_production_migration` (merge base `d205bfc`). The remote carries the HR/payroll/scan/maintenance modules, the finance ledger (`0003`, `0004`), warehouse `0012`–`0019` and a large frontend rewrite.

The trial merge gives **32 conflicted files**. Most are mechanical; four are decisions.

## 1. Decisions (cannot be settled by editing)

| # | Overlap | Ours | Theirs | Recommendation |
|---|---|---|---|---|
| D1 | **Stock valuation** | `stock_valuation` table, weighted-average cost (CMUP), `receive_stock(unit_cost=)` | `cost_layers` + `cost_layer_consumptions`, FIFO, hooked at 6 places in `StockService` (`record_inflow/outflow/delta`) | Keep **their FIFO** (already wired through every stock path and feeds production costing). Drop our `stock_valuation` and `apply_receipt`; port the valued-stock screen and CSV/XLSX export onto `ValuationService.get_valuation`. Ask the accountant whether CMUP is legally required in Mali (SYSCOHADA allows both). |
| D2 | **Physical count** | `warehouse.inventories` (two equal counts, else a third; freezes the location) | `warehouse.cycle_counts` (start, count, resolve, complete) | Needs a business call. Our freeze (`LOCATION_FROZEN`) is the new rule the client asked for. Suggest: keep **their cycle counts** as the model and add the freeze + two-count rule on top, instead of two parallel tables. |
| D3 | **Same-named files** | `valuation.py`, `valuation_service.py`, `test_valuation.py` (add/add) | same paths, different content | Follows D1. Take theirs, rename ours if any part survives. |
| D4 | **Invoice paid event and ledger** | Treasury updates `amount_paid`/status silently through `apply_payment_delta` (no event). | `finance.invoice.paid` triggers a ledger entry on a single generic bank account (`invoice_ledger_service.post_paid`). | When B6 is written, treasury must post the real 5xx account itself and the generic `invoice_paid` posting must **not** also fire for treasury-settled invoices. Settle this before enabling both. Manual `mark_paid` is still the old path and would double post if used on an invoice that treasury paid (it is already refused with `INVOICE_HAS_PAYMENTS`). |

## 2. Migration numbers

The runner tracks files by name, so nothing breaks on a database that has both, but a clean install applies by sort order, so renumber to keep one sequence:

| Module | Theirs | Ours (rename to) |
|---|---|---|
| warehouse | `0012` … `0019` | `0012_warehouse_vouchers_inventory_valuation` → **`0020`** (and strip the `stock_valuation` part if D1 = FIFO) |
| finance | `0002_finance_invoice_currency_xof`, `0003`, `0004` | `0002_finance_invoice_amount_paid` → **`0005`** |
| procurement | `0006_procurement_line_currency_xof` | `0006_procurement_purchase_invoices` → **`0007`**, `0007_…invoice_payment_deltas` → **`0008`** |
| treasury | none | unchanged |

Because the shared dev database already recorded the other branch's names, renaming ours means the runner would re-apply them. All our migrations use `IF NOT EXISTS`, so re-applying is safe, but check each before the first run. Add the treasury module to `MODULE_ORDER` after finance and procurement.

## 3. Mechanical conflicts (keep both sides)

- `app/main.py`, `core/migrations/runner.py`, `worker/main.py`, `core/permissions_registry.py`, `events/CATALOG.md`, the four `module.json` files: both sides added entries to the same lists.
- `warehouse/api/router.py`, `service.py`: ours adds the freeze guard and two routers; theirs adds cycle counts, FIFO hooks, reservations, replenishment. The freeze guard must be re-applied to any new stock-writing path they added (reservations, fulfilment/pick, replenishment moves, cycle-count adjustments). Re-run `test_shift_validation_integration.py::…frozen`.
- `scripts/reset_operational_data.py`: classify their new tables and ours in one list (this also fixes the 3 failing reset tests).
- Frontend: `WarehousePage.tsx`, `i18n.tsx`, `AppLayout.tsx`, `Sidebar.tsx`, `router.tsx`, `StatusBadge.tsx`, `FinanceInvoicesPage.tsx`, `SalesOrdersPage.tsx`. i18n is the noisiest: both sides appended keys before the same line.
- **modify/delete (17 files)**: our local branch has deleted CRM, analytics and the old production shift screens that the remote changed. Confirm those deletions were intended before the merge; taking the remote version silently brings them back.

## 4. Unblocks B6 (ledger posting)

The ledger now exists on the remote: `finance.accounts`, `journals`, `journal_entries` (idempotent on `source_module/source_id/source_kind`), `posting_rules`, `posting_failures`, a consumer that records refusals and supports retry. B6 should be a new `treasury` source in `ledger_event_postings.SOURCES` (`treasury.receipt.posted`, `treasury.disbursement.posted`, `treasury.deposit_slip.collected`, `treasury.instrument.unpaid`, `treasury.transfer.posted`), with the rules in `posting_rules`, not hard-coded. Only after the accountant confirms the accounts and D4 is settled.

## 5. Suggested order

1. Answer D1, D2 (business) and D4 (accounting).
2. Merge `origin/huge_production_migration` into a new branch (not this one: pushing this branch deploys).
3. Resolve per section 3, renumber per section 2.
4. Run the full backend suite against a freshly migrated empty database (not the shared one) and the frontend type-check.
5. Write B6 on top.
