# Market-readiness roadmap

**This is the project's standing brief.** All work from 2026-11-16 onward is to fix and add
the pieces listed here, so the app can be sold to customers other than Sonalim.
Any session picking up work starts by reading this file, then takes the first unchecked
work package (or the one the user names).

Source: code review of 2026-11-16 (backend modules, migrations, event catalog, deploy
setup). Findings are summarised in "Why" below; the review did not run the app.

## How to work through this (read before starting a package)

1. One work package (WP) per session. Do not start a second one in the same session.
2. Before coding a WP, write a short spec in `docs/superpowers/specs/` and a task plan in
   `docs/superpowers/plans/` (existing convention), unless the WP is marked *small*.
3. Follow `CLAUDE.md` and `.claude/skills/erp-platform-architecture/SKILL.md`: modules never
   read each other's tables, new events go in `backend/events/CATALOG.md`, migrations are
   new numbered files, both `en` and `fr` strings.
4. Work on a feature branch. Never push to `huge_production_migration` (it deploys to the
   live server) unless the user asks.
5. When stopping, for any reason, update the **Progress log** at the bottom and tick the
   checkboxes, then commit and push. The log is what lets the next session resume.
6. A WP is done only when its tests pass against a real database (a green run full of
   skips proves nothing) and its "Done when" line is true.

## Why (the gaps found)

- Shop floor is deep (production, warehouse, HR/payroll, maintenance, QC). Commercial and
  financial side is thin: sales is a skeleton, an invoice is a single amount.
- The module chain breaks at the money: purchases, stock value and production cost never
  reach the ledger; sales orders do not drive production; lots stop at the warehouse.
- Platform is single-customer: no way to create a company or user from the app, no
  password reset, no email, tenant isolation only by hand-written filters, Mali/XOF
  hardcoded, no PDFs, deploys go live with no test step and no backup job.

## Phase 0 — Safety net (do first; everything after depends on it)

- [ ] **WP-0.1 CI tests before deploy.** Add a test job (Postgres service, backend pytest,
  frontend `tsc` + vitest) that `deploy` needs. *Done when* a failing test blocks deploy.
- [ ] **WP-0.2 Backups.** Scheduled `pg_dump` with retention and an off-server copy, plus a
  documented restore drill. *Done when* a restore has been run once from a backup.
- [ ] **WP-0.3 Connection pool.** Replace per-request `psycopg.connect` in `core/db.py`
  with `psycopg_pool`. *Small.*
- [ ] **WP-0.4 Money as Decimal.** Remove `float` for amounts in sales, finance invoices,
  procurement (about 37 annotations). Fix invoice currency default (`USD`).
- [ ] **WP-0.5 Module manifests.** Fill `dependencies` and published/consumed events in
  every `module.json`; add a test that the manifests match real imports and the catalog.
- [ ] **WP-0.6 Error tracking and alerts.** Error reporting for API and worker, alert on
  dead-letter queue growth and on `finance.posting_failures`.

## Phase 1 — Close the money loop

- [ ] **WP-1.1 Tax engine.** Tax codes and rates (per tenant), applied to sales and
  purchase lines; tax accounts in posting rules.
- [ ] **WP-1.2 Real customer invoices.** Invoice lines, tax, numbering sequence, due date
  and payment terms, partial payments, credit notes. Migrate existing single-amount rows.
- [ ] **WP-1.3 Invoice from shipment.** Create the invoice from `warehouse.shipment.shipped`
  (shipped quantities) instead of `sales.order.confirmed` (ordered total).
- [ ] **WP-1.4 Supplier bills and payables.** Supplier invoice against PO and receipt
  (3-way match), posting to the purchases journal, supplier payments.
- [ ] **WP-1.5 Payments, cash and bank.** Payment records for customers and suppliers,
  cash/bank journals, bank statement import and reconciliation, ageing reports,
  customer statement.
- [ ] **WP-1.6 Stock to ledger.** Post receipts, issues, adjustments and cost of goods
  sold from the warehouse FIFO cost layers (new warehouse events consumed by finance).
- [ ] **WP-1.7 Production costing.** Cost of a validated shift (materials from cost
  layers, plus labour/energy rates), finished-goods cost layer, WIP and variance postings.
- [ ] **WP-1.8 Financial statements.** Balance sheet, income statement, SYSCOHADA
  outputs, year-end close.

## Phase 2 — Finish Sales and traceability

- [ ] **WP-2.1 Quotes and price lists.** Quotation → order, customer price lists,
  discounts, order currency.
- [ ] **WP-2.2 Order lifecycle.** Cancel, edit after confirm, partial shipment and
  backorder, customer credit limit check.
- [ ] **WP-2.3 Delivery notes and returns.** Delivery note per shipment, customer returns
  to stock or quarantine, linked credit note.
- [ ] **WP-2.4 Lots end to end.** Lot on pick/shipment lines; trace forward (lot →
  customers) and backward (shipment → shift → raw-material lots); recall report.
- [ ] **WP-2.5 Printable documents.** PDF for quote, order, delivery note, invoice, PO,
  payslip, with company header and both languages.
- [ ] **WP-2.6 Procurement completion.** Purchase requisition, RFQ and supplier
  comparison, approval thresholds.

## Phase 3 — Make it multi-customer

- [ ] **WP-3.1 Company and user provisioning.** Create tenant, first admin, invite users;
  setup wizard (chart of accounts, sites, currency).
- [ ] **WP-3.2 Account security.** Email sending, password reset and change, 2FA,
  session list and revoke.
- [ ] **WP-3.3 Row-level security.** Postgres RLS on every tenant table, tenant set per
  connection; a test that fails for any tenant table without a policy.
- [ ] **WP-3.4 Country packs.** Move currency, payroll rules, chart of accounts and tax
  out of code into per-tenant configuration (Mali pack first, then one more country).
- [ ] **WP-3.5 Data import.** Templates and importers for products, partners, opening
  stock, opening balances, employees.
- [ ] **WP-3.6 Staging and release process.** Staging environment, versioned releases,
  migration dry-run before live.

## Phase 4 — Widen

- [ ] **WP-4.1 Planning and MRP.** Sales demand and stock levels propose work orders and
  purchase needs.
- [ ] **WP-4.2 Generic production.** Separate pasta/Sonalim specifics from the core so
  another manufacturer can configure its own lines and report sections.
- [ ] **WP-4.3 Food safety.** HACCP/CCP records, allergens, expiry management on shipment.
- [ ] **WP-4.4 HR extras.** Recruitment, training, appraisal.
- [ ] **WP-4.5 Integrations.** API keys, webhooks, public API docs.
- [ ] **WP-4.6 Commercial layer.** Licensing or subscription billing, plans, usage limits.
- [ ] **WP-4.7 Manual and tests.** Manual for the remaining modules, end-to-end tests for
  the main chains (order-to-cash, procure-to-pay, shift-to-stock).

## Open decision

Target market: other West African food manufacturers (Phases 0–3 suffice) or a general
ERP (WP-4.2 becomes the largest item and moves earlier). Not yet decided by the user.

## Progress log

Newest first. One line per session: date, WP, what was finished, what is left, branch.

- 2026-11-16 — Review done, roadmap written. No WP started. Branch `claude/zen-ptolemy-m1jrr1`.
