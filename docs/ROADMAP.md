# Market-readiness roadmap

**This is the project's standing brief.** All work from 2026-11-16 onward is to fix and add
the pieces listed here, so the app can be sold to customers other than Sonalim.
Any session picking up work starts by reading this file, then takes the first unchecked
work package (or the one the user names).

Source: code review of 2026-11-16 (backend modules, migrations, event catalog, deploy
setup). **The review read `main`, which was 61 commits behind `huge_production_migration`.**
That branch already had treasury, purchase invoices, quotes, price lists, VAT on lines,
credit notes, credit control and dunning. The work packages below were re-checked against
`huge_production_migration` the same day and marked: `[x]` done, `[~]` exists and needs a
depth check before anything is added, `[ ]` not found. The re-check was by keyword and
table names, not a full read, so the first step of any `[~]` package is to read what is
there.

**Base branch for all work: `main`** (user's instruction, 2026-11-17). `main` already holds
everything from `huge_production_migration`, which is retired. Every push to `main` is
tested, built and deployed to the VPS.

## How to work through this (read before starting a package)

1. One work package (WP) per session. Do not start a second one in the same session.
2. Before coding a WP, write a short spec in `docs/superpowers/specs/` and a task plan in
   `docs/superpowers/plans/` (existing convention), unless the WP is marked *small*.
3. Follow `CLAUDE.md` and `.claude/skills/erp-platform-architecture/SKILL.md`: modules never
   read each other's tables, new events go in `backend/events/CATALOG.md`, migrations are
   new numbered files, both `en` and `fr` strings.
4. Commit to `main` and push there. A push deploys to the live server, so first run the
   `tests.yml` steps locally (backend on a real Postgres, frontend `tsc` + vitest).
5. When stopping, for any reason, update the **Progress log** at the bottom and tick the
   checkboxes, then commit and push. The log is what lets the next session resume.
6. A WP is done only when its tests pass against a real database (a green run full of
   skips proves nothing) and its "Done when" line is true.

## Why (the gaps found)

- Shop floor is deep (production, warehouse, HR/payroll, maintenance, QC). The commercial
  and financial side is now substantial on `huge_production_migration` (sales pricing and
  quotes, invoices with lines and VAT, purchase invoices, treasury with bank reconciliation).
- Remaining breaks in the module chain: stock value and production cost never reach the
  ledger; sales orders do not drive production; lots are not traced to the customer;
  treasury ledger posting is off until `ledger_posting_enabled` is set.
- Platform is single-customer: no way to create a company or user from the app, no
  password reset, no email, tenant isolation only by hand-written filters, Mali/XOF
  hardcoded, no PDFs, deploys go live with no test step and no backup job.

## Phase 0 — Safety net (do first; everything after depends on it)

- [x] **WP-0.1 CI tests before deploy.** Add a test job (Postgres service, backend pytest,
  frontend `tsc` + vitest) that `deploy` needs. *Done when* a failing test blocks deploy.
  *Built 2026-11-16* (`.github/workflows/tests.yml`, called by `deploy.yml`); tick once the
  workflow has run green on GitHub at least once. *Green on GitHub 2026-11-17* (run 44163478513).
- [ ] **WP-0.2 Backups.** Scheduled `pg_dump` with retention and an off-server copy, plus a
  documented restore drill. *Done when* a restore has been run once from a backup.
  *Built 2026-11-16* (`tools/backup/`, runbook `docs/backups.md`); tick once the one-time
  server setup is done and `restore.sh --drill --from-remote` has passed on the server.
- [x] **WP-0.3 Connection pool.** Replace per-request `psycopg.connect` in `core/db.py`
  with `psycopg_pool`. *Small.* *Done 2026-11-20.*
- [x] **WP-0.4 Money as Decimal.** Remove `float` for amounts in sales, finance invoices,
  procurement (about 37 annotations). Fix invoice currency default (`USD`). *Done 2026-11-20.*
- [x] **WP-0.5 Module manifests.** `depends` is declared but incomplete (production lists
  only `core` yet imports warehouse, qc, maintenance, procurement, hr). Complete `depends`
  and published/consumed events in every `module.json`; add a test that the manifests match real imports and the catalog. *Done 2026-11-20.*
- [x] **WP-0.6 Error tracking and alerts.** Error reporting for API and worker, alert on
  dead-letter queue growth and on `finance.posting_failures`. *Done 2026-11-20*; delivery
  needs `SENTRY_DSN` and/or `ALERT_WEBHOOK_URL` in the server `.env` (`docs/operations-alerts.md`).

## Phase 1 — Close the money loop

- [~] **WP-1.1 Tax engine.** (VAT rate per line exists in sales, finance, procurement; check
  tax accounts, exemptions and a tax report.) Tax codes and rates (per tenant), applied to sales and
  purchase lines; tax accounts in posting rules.
- [~] **WP-1.2 Real customer invoices.** (Lines, VAT, counters, instalments, credit notes
  exist.) Invoice lines, tax, numbering sequence, due date
  and payment terms, partial payments, credit notes. Migrate existing single-amount rows.
- [~] **WP-1.3 Invoice from shipment.** (Finance consumes `warehouse.shipment.shipped` and
  `warehouse.voucher.posted`.) Create the invoice from `warehouse.shipment.shipped`
  (shipped quantities) instead of `sales.order.confirmed` (ordered total).
- [~] **WP-1.4 Supplier bills and payables.** (Purchase invoices, receipt matching, credit
  notes and ledger posting exist.) Supplier invoice against PO and receipt
  (3-way match), posting to the purchases journal, supplier payments.
- [~] **WP-1.5 Payments, cash and bank.** (Treasury module exists: receipts,
  disbursements, cheques, deposit slips, statement import, reconciliation, payment orders.
  Check ageing reports and customer statement; decide when to enable ledger posting.) Payment records for customers and suppliers,
  cash/bank journals, bank statement import and reconciliation, ageing reports,
  customer statement.
- [ ] **WP-1.6 Stock to ledger.** Post receipts, issues, adjustments and cost of goods
  sold from the warehouse FIFO cost layers (new warehouse events consumed by finance).
- [ ] **WP-1.7 Production costing.** Cost of a validated shift (materials from cost
  layers, plus labour/energy rates), finished-goods cost layer, WIP and variance postings.
- [ ] **WP-1.8 Financial statements.** Balance sheet, income statement, SYSCOHADA
  outputs, year-end close.

## Phase 2 — Finish Sales and traceability

- [~] **WP-2.1 Quotes and price lists.** (Quotes, price lists, customer pricing exist.) Quotation → order, customer price lists,
  discounts, order currency.
- [~] **WP-2.2 Order lifecycle.** (Customer credit and dunning exist in finance; check
  cancel, edit, partial shipment.) Cancel, edit after confirm, partial shipment and
  backorder, customer credit limit check.
- [~] **WP-2.3 Delivery notes and returns.** (Stock vouchers and delivery settings exist;
  customer returns not found.) Delivery note per shipment, customer returns
  to stock or quarantine, linked credit note.
- [ ] **WP-2.4 Lots end to end.** Lot on pick/shipment lines; trace forward (lot →
  customers) and backward (shipment → shift → raw-material lots); recall report.
- [~] **WP-2.5 Printable documents.** (A printable voucher view exists; no server-side PDF.) PDF for quote, order, delivery note, invoice, PO,
  payslip, with company header and both languages.
- [ ] **WP-2.6 Procurement completion.** Purchase requisition, RFQ and supplier
  comparison, approval thresholds.

## Phase 3 — Make it multi-customer

- [ ] **WP-3.1 Company and user provisioning.** Create tenant, first admin, invite users;
  setup wizard (chart of accounts, sites, currency). (Fresh-database bootstrap is already
  handled by the migration runner.)
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

- 2026-11-20 — WP-0.6 done (spec `specs/2026-11-20-error-tracking-alerts-design.md`, plan
  `plans/2026-11-20-error-tracking-alerts.md`, runbook `docs/operations-alerts.md`). New
  `core/observability.py`: one log format, optional Sentry (`SENTRY_DSN`; the framework
  integrations are off, so `report_exception` is the only sender and each error goes once),
  `send_alert` (log + Sentry + JSON POST to `ALERT_WEBHOOK_URL`), `GrowthWatch`, and an ASGI
  middleware inside CORS that turns an escaped exception into the usual 500 `detail` with an
  en/fr message and a reference (before, the browser saw a CORS error). Worker: a failing
  consumer used to be dead-lettered with nothing logged; it is now reported with consumer,
  event type and id. The outbox dispatcher had no `try`, so one broker hiccup stopped all
  events for good; it now reports and reconnects. Sweeps call `report_exception` instead of
  `print`. `worker/alerts.py` checks the DLQ depth and open `finance.posting_failures` per
  tenant every 5 min, alerts on growth, and serves both as gauges on `:9101` (scraped by the
  compose Prometheus). Finance notifies `finance.view_ledger` holders in-app when a posting
  failure opens (not when an open one is refused again); `PostingRefused` is marked
  `expected_refusal`, so it is a warning, not a Sentry error. New dependency `sentry-sdk`.
  Postgres 16 local (migrations + `seed_dev`): backend 3265 passed / 11 skipped (known). No
  frontend change. **Server to-do:** set `SENTRY_DSN` and/or `ALERT_WEBHOOK_URL` in the server
  `.env`; without them, errors and alerts are only in `docker compose logs`. Next WP: WP-1.1
  (WP-0.2 still waits on its server drill). Branch `claude/exciting-hypatia-vlnkca`, then
  `main` (d6abcb6, which also makes `tools/git-hooks/pre-commit` executable: git had been
  skipping it). Run 44850869670 failed like the three before it (every job in 2–3 s, no logs):
  Actions is still not starting jobs, so WP-0.3 to WP-0.6 are on `main` but not built or
  deployed. Left: fix Actions (billing/spending limit under the account's Settings > Billing,
  as on 2026-11-17), then re-run the latest `Build and Deploy` run.

- 2026-11-20 — WP-0.5 done (spec `specs/2026-11-20-module-manifests-design.md`, plan
  `plans/2026-11-20-module-manifests.md`). The fields now have a defined meaning: `depends` =
  modules imported at module level by non-test code, `optional_depends` = modules imported only
  inside functions, both exact. `core/test_module_manifests.py` (no DB, 67 tests) checks them
  against the imports and checks that `depends` has no cycle. It also checks publishes against
  `publish_event` calls (computed names listed in `DYNAMIC_EVENT_TYPES`), subscribes against the
  consumer registry, that the worker imports every consumer file, that `CATALOG.md` producers
  and consumers are right, and `provides_api`. It found 22 mismatches, now fixed in ten
  manifests. Two other fixes: maintenance ↔ production imported each other at load time, so
  `history_export` now imports production's xlsx style lazily; the catalog now lists hr as a
  consumer of the payroll run events, and payroll is no longer listed for
  `hr.presence_month.closed`. Postgres 16 local (migrations + `seed_dev`): backend 3248 passed /
  11 skipped (known). No frontend change, so `tsc` and vitest were not run. Pushed to `main`
  (aec81c3) on the user's go-ahead. Run 44823962482 failed like the two before it: every job
  failed in 3 s, with no logs. Actions is still not starting jobs, so nothing was tested on
  GitHub, built or deployed. Left: the same as for WP-0.4. Next WP: WP-0.6.
  Branch `claude/elegant-cerf-f5ox2b`, then `main`.

- 2026-11-20 — WP-0.4 done (spec `specs/2026-11-20-money-as-decimal-design.md`, plan
  `plans/2026-11-20-money-as-decimal.md`). Sales orders, finance invoices and procurement
  orders/receipts keep amounts, and the quantities and rates they come from, as `Decimal` from
  the NUMERIC row to the API; `core/domain/money.py` (`to_decimal` via `str`, `json_number`):
  responses and event/audit payloads still carry JSON numbers, so no frontend or event change.
  Domain dataclasses coerce float callers (CRM, seeds). Fixed: 0.1 + 0.2 t received against
  0.3 t ordered was refused as an over-receipt. Left float on purpose: warehouse call
  arguments, the procurement read-only cost/price reports (production does float maths on
  them), `core` exchange rates. The `USD` default was already fixed by `finance/0002`.
  Postgres 16 local: backend 3176 passed / 11 skipped (known), frontend `tsc` + 194 vitest
  passed. Pushed to `main` (4d5966a) on the user's go-ahead. Run 44817101453 (and 44812738880,
  WP-0.3) failed in 3 s with no runner assigned and no logs: GitHub Actions is not starting jobs
  (likely billing / spending limit, as on 2026-11-17), so nothing was tested, built or deployed.
  Left: the user unblocks Actions, then "Re-run all jobs" on the latest run; the deploy secrets
  (`SERVER_HOST` / `SERVER_USER` / `SERVER_SSH_KEY`) are still needed for the deploy step.
  Next WP: WP-0.5. Branch `claude/epic-keller-b2cjzb`, then `main`.

- 2026-11-20 — WP-0.3 done. `core/db.py`: `get_connection()` draws from one lazy
  `psycopg_pool.ConnectionPool` per process (same commit-on-exit / rollback-on-error contract;
  `DB_POOL_MIN_SIZE` 1, `DB_POOL_MAX_SIZE` 20, `DB_POOL_TIMEOUT` 30 s, in `.env.example`);
  `/health` uses it, the app lifespan closes it. Connections are checked on checkout, and the
  first dead one purges the whole idle set: the pool's own per-connection backoff made the
  first request after a Postgres restart time out (reproduced, 20 dead connections > 30 s; now
  0.07 s). Pinned `psycopg-pool==3.2.6`. Tests `core/test_db_integration.py` (reuse, commit /
  rollback, dead connection, restart recovery). Postgres 16 local: backend 3172 passed /
  11 skipped (known); uvicorn smoke 400 requests at 40-way on 17 connections, 100/100 right
  after a Postgres restart. No frontend change. Next WP: WP-0.4. Branch
  `claude/serene-cray-5ygicm`.

- 2026-11-17 — Deploy fix: images moved from `ghcr.io/smarttoolsagro/*` (403 since
  2026-10-05) to `ghcr.io/mahmoudnjeh95/*`, linked to the repo; the server pulls with the
  run's `GITHUB_TOKEN`, then takes the pre-deploy dump, then restarts. Run 44177243620:
  tests and image push green; deploy stopped at the first step because the repo has no
  `SERVER_HOST` / `SERVER_USER` / `SERVER_SSH_KEY` secrets (left in the old repo). Left: a
  repo admin adds them, then "Re-run failed jobs". `SECRET_SONALIM` is no longer used.
  Branch `main`.

- 2026-11-17 — GitHub Actions unblocked (billing). WP-0.1 ticked: `tests.yml` green on
  GitHub on `main`. WP-0.2 merged to `main` (PR #17) after the `tests.yml` steps passed
  locally. By the user's instruction `main` is now the only branch and deploys to the VPS
  (`huge_production_migration` retired); each deploy first takes a `pre-deploy_*.dump` of
  the live database. Open: every deploy since 2026-10-05 failed with 403 pushing images to
  `ghcr.io/smarttoolsagro/*` (the repo needs Write under each package's "Manage Actions
  access", set by a `smarttoolsagro` owner); WP-0.2 server setup and first drill. Next WP:
  WP-0.3. Branch `main`.

- 2026-11-16 — WP-0.2 built (spec `specs/2026-11-16-backups-design.md`, plan
  `plans/2026-11-16-backups.md`). `tools/backup/`: `backup.sh` (nightly `pg_dump -Fc`
  through `docker compose exec`, verified by `pg_restore --list`, `.sha256`, GFS retention
  14 d / 8 w / 12 m, rclone copy to an encrypted `crypt` remote + `cryptcheck`, off-site
  retention, healthchecks.io ping), `restore.sh` (`--drill` into a scratch DB and
  `--into-live`, which restores beside the live DB and swaps by rename, keeping the old one),
  `retention.py` + tests, cron and env examples. `deploy.yml` copies `tools/backup/` to the
  server; `tests.yml` runs the retention tests and shellcheck. Tested on Postgres 18 in
  Docker with the server's layout (204 migrations + `seed_dev`): backup, 120 simulated days
  of retention (23 kept, same off-site), failures (no remote → exit 3, DB down, concurrent
  run, tampered dump), drill from the encrypted copy, live restore with a stand-in app
  holding connections; backend suite on the restored DB 3166 passed / 11 skipped. Left (on
  the server, by the user): rclone remote, `backup.env`, first backup + drill, cron — then
  tick. Branch `claude/wp-0.2-backups` (from `main`, which already includes
  `huge_production_migration`).

- 2026-11-16 — Merged `huge_production_migration` into the work branch (61 commits the
  review had not seen) and re-marked the packages above. WP-0.1 built: `tests.yml` (backend
  on an empty Postgres 18 with all migrations + `seed_dev`, frontend `tsc` + vitest);
  `deploy.yml` build now needs it. Local run on the merged branch (Postgres 16, Python 3.13):
  backend 3166 passed / 11 skipped (need a work center or a converted shift), frontend 194
  passed. Left: see it run green on GitHub, then tick. Branch `claude/zen-ptolemy-m1jrr1`.
- 2026-11-16 — Review done, roadmap written. No WP started. Branch `claude/zen-ptolemy-m1jrr1`.
