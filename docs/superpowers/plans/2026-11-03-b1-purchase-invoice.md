# B1 — Minimal purchase invoice (procurement) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or superpowers:executing-plans. Checkbox steps. Read `2026-11-03-treasury-interfaces.md` first.

**Goal:** Give `procurement` a supplier invoice (draft → validated → partially_paid → paid, or cancelled) that disbursements can allocate to.

**Architecture:** Pure state machine in `modules/procurement/domain/purchase_invoice.py`; `PurchaseInvoiceService` in `api/invoice_service.py`; router additions; migration `0006_procurement_purchase_invoices.sql`. The consumer of `treasury.disbursement.posted/cancelled` is added in B3; this plan builds the entity and the method it will call.

**Tech Stack:** FastAPI, psycopg, pytest; React + TanStack Query + RHF/Zod.

## Decisions

1. Owned by procurement (suppliers and POs live there). Optional link to a PO (`purchase_order_id`, same-module FK allowed); FK to `core.partners` allowed.
2. Header-only amounts are valid; lines are optional (`description, quantity, unit_price`) and, when given, must sum to the header total within 0.01 (`TOTAL_MISMATCH`).
3. `supplier_invoice_number` unique per `(tenant, partner)` (`DUPLICATE_SUPPLIER_INVOICE`).
4. Statuses: `draft`, `validated`, `partially_paid`, `paid`, `cancelled`. Only `validated`/`partially_paid` accept allocations. Cancel only while `amount_paid = 0`.
5. `amount_paid` is never set by the user; only through `apply_payment_delta` (called by the B3 consumer).
6. Withholding tax is not modelled (Tunisian-specific, spec "Not taken").

## Tasks

### Task 1 — Domain state machine
- [ ] Create `domain/purchase_invoice.py` + `test_purchase_invoice.py`. Failing tests first: legal transitions (draft→validated, validated→cancelled); status derived from `(amount, amount_paid)` (0 → validated, 0<paid<amount → partially_paid, paid>=amount → paid); illegal transitions refused; `remaining(amount, amount_paid)`; lines-sum check.
- [ ] Implement; run `.venv/Scripts/python -m pytest modules/procurement/domain -q`; commit.

### Task 2 — Migration
- [ ] `0006_procurement_purchase_invoices.sql`: `procurement.purchase_invoices (id, tenant_id, number NULL, partner_id, supplier_invoice_number, purchase_order_id NULL, invoice_date, due_date, currency DEFAULT 'XOF', amount NUMERIC(18,2) CHECK > 0, amount_paid NUMERIC(18,2) DEFAULT 0 CHECK >= 0, status CHECK IN (...), note, created_by, created_at, validated_at)`; `procurement.purchase_invoice_lines (id, invoice_id, description, quantity, unit_price)`; `procurement.invoice_counters (tenant_id, year, last_number)`; unique `(tenant_id, partner_id, supplier_invoice_number)` and `(tenant_id, number)` where not null; index `(tenant_id, status, due_date)`. Number `FA-YYYY-000001` allocated at validation under `FOR UPDATE`.
- [ ] Apply migration (command in the stock plan's Global Constraints); commit.

### Task 3 — Service and router
- [ ] Failing integration tests in `api/test_purchase_invoice_integration.py`: create draft with/without lines; edit only in draft; validate allocates a number and writes the `procurement.purchase_invoice.validated` outbox event; duplicate supplier number refused; cancel with payments refused; `get_invoice` returns remaining; `list_invoices(status, partner_id, overdue)`; `apply_payment_delta` rejects results <0 or >amount with `OVER_ALLOCATION` and re-derives status.
- [ ] Implement `PurchaseInvoiceService` (`create_draft`, `update_draft`, `validate`, `cancel`, `get_invoice`, `list_invoices`, `apply_payment_delta`).
- [ ] Router `/procurement/purchase-invoices`; `module.json`: permissions, `provides_api` += `PurchaseInvoiceService`, `publishes_events` += the event; CATALOG.md row; French messages. Run `core/test_error_translations.py`; commit.

### Task 4 — Frontend
- [ ] `features/procurement/PurchaseInvoicesPage.tsx` + hooks in `api.ts`: list with status tabs (draft / validated / partially paid / paid / overdue), create/edit dialog (supplier via the existing partner select, optional PO, optional lines), validate and cancel actions, remaining-amount column, overdue badge from `due_date`.
- [ ] Route + sidebar entry (see how `PurchaseOrdersPage` is registered in `routes/`), permission gating, i18n en+fr; `npx tsc -b --force` clean; commit.

### Task 5 — Handoff
- [ ] Run `modules/procurement` + `core` tests; report passed/skipped honestly. Grant the new permissions to the demo user through the API. Do not push.
