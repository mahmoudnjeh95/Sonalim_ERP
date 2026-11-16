# Stock vouchers, inventory, valuation and Treasury — design

Date: 2026-11-03
Status: draft, awaiting spec review

Source of requirements: a vendor manual for a Tunisian ERP ("module stock" and "module
trésorerie", 51 pages, text only read — screenshots and annexes not reviewed). It is a
**reference for behaviour**, not a spec to copy. Tunisian-specific rules are dropped (see
"Not taken").

## Goal

1. Stock (`warehouse`): add document-level vouchers, a physical inventory with a depot freeze,
   weighted-average valuation and the missing reports, on top of the existing move ledger.
2. Treasury (new module `treasury`): receipts, disbursements, banks/accounts, cash registers,
   cheque/draft lifecycle, bank-statement import and due-date alerts, posting to the SYSCOHADA
   ledger. Currency F CFA.

## Current state (measured)

- `warehouse`: `stock_items`, `stock_moves` (move types receipt, issue, transfer_in/out,
  adjustment; with `location_id`, `actor_id`, `source_type/source_id/of_id`), `locations`
  (with `is_blocked`), `lots`/`lot_stock`. Services for receive/issue/transfer/adjust exist
  (`StockService`). No document header: a transfer is two unrelated-looking moves.
- Warehouse review (2026-09-24) already lists as next steps: physical inventory/cycle counts,
  valuation method, stock export. This spec delivers those.
- `finance`: only `finance.invoices`. The ledger (accounts, journals, entries, posting rules)
  is Phase 4 of `2026-09-25-hr-payroll-finance-design.md` and is **not built yet**.
- No supplier invoices / AP anywhere (explicitly out of scope in the HR/finance spec).

## Part A — Stock (`warehouse`)

### A1. Vouchers (document header over moves)

New tables `warehouse.vouchers` (id, tenant_id, number, type `receipt|issue|return|transfer`,
status `draft|posted|cancelled`, source_location_id, dest_location_id, partner_id,
source_ref_type/source_ref_id (PO, sales order, delivery), note, created_by, posted_by/at) and
`warehouse.voucher_lines` (voucher_id, product_id, lot_id, quantity, unit_cost nullable).
Posting a voucher calls the existing `StockService` methods in one transaction and stamps
`stock_moves.source_type='voucher'`, `source_id=voucher.id`. Numbering per type per year.
Posted vouchers are immutable; correction = new voucher (return/adjustment).

Rules taken from the manual, adapted:
- Issue refused if available (on hand − reserved − blocked) < line quantity (`STOCK_INSUFFICIENT`).
  The existing rule that production validation may drive on-hand negative is unchanged; this
  applies only to manual vouchers.
- Issue against a sales order: cumulative issued quantity across all vouchers of that order
  must not exceed ordered quantity (`ORDER_QTY_EXCEEDED`). "Create issue from order" prefills
  customer and lines; the user picks the location and may reduce quantities.
- Transfer: source and destination differ; quantity ≤ available at source.
- Return: references the original issue/delivery; returned ≤ issued − already returned.
  Restocks at the chosen location (a blocked location for damaged goods).
- Warn (non-blocking) when an issue/transfer takes a product below its minimum stock.
- Receipt requires `unit_cost` (needed for valuation); defaulted from the PO line when the
  receipt comes from procurement.
- Production receipts/consumption stay posted by shift validation. They do **not** get
  vouchers.

### A2. Inventory (physical count)

`warehouse.inventories` (id, number, location_id, type `full|interim`, status
`open|counting|closed|cancelled`, opened_by/at, closed_by/at) and `warehouse.inventory_lines`
(inventory_id, product_id, lot_id, theoretical_qty snapshot, count_1, count_2, count_3,
final_qty, variance, observation).

- Opening a **full** inventory freezes the location: receipt, issue, return, transfer and
  production postings to it are refused (`LOCATION_FROZEN`). One open inventory per location.
  An **interim** inventory never freezes and never adjusts stock.
- Count rules (one sign convention, decided here: `variance = final_qty − theoretical_qty`):
  counts 1 and 2 equal → `final = count_1`; differ → count 3 mandatory and `final = count_3`.
  Observation mandatory whenever `variance != 0`.
- Closing posts one `adjustment` move per non-zero variance (reason = inventory number),
  then unfreezes. Closing is `warehouse.admin_stock`; counting is `warehouse.adjust_stock`.
- Blank count sheet (products, theoretical qty, empty count columns) as PDF/print view.
- A shift validated while a location is frozen is **blocked** with `LOCATION_FROZEN`
  (decision 2).

### A3. Valuation (weighted average, CMUP)

`warehouse.stock_valuation` per (tenant, product): `avg_cost`, updated on each valued
inbound: `new = (old_qty·old_cost + in_qty·in_cost) / (old_qty + in_qty)`. Issues and
transfers do not change the average; returns re-enter at the original issue's cost. Inbound
without a cost uses the current average (never zero-weights it silently — flagged in the
report). Pure function in `warehouse/domain/valuation.py`, unit-tested without a DB.
Existing overview KPI "stock value at catalog purchase price" is switched to `avg_cost` where
present. Each valued move stores `unit_cost` so a posting to the ledger is possible later.

### A4. Reports

Stock by location (exists — add export), **valued stock** (qty × avg_cost, per product and
total), **movements** report with source document link and date/type filters (the
`date_from/date_to` filter exists). XLSX export for each.

### A5. Permissions

Add to `warehouse/module.json`: `warehouse.manage_vouchers`, `warehouse.post_vouchers`,
`warehouse.manage_inventory`, `warehouse.close_inventory`, `warehouse.view_valuation`.
Grant to users explicitly (not auto-granted).

### A6. Events (register in `events/CATALOG.md`)

`warehouse.voucher.posted`, `warehouse.inventory.closed`.

## Part B — Treasury (`treasury`, new module)

Depends on `core`, `finance` (ledger), and consumes sales invoices. Ledger posting
is deferred (decision 6); supplier-side flows rely on the minimal purchase invoice (decision 1).

### B1. Master data

`treasury.banks`, `treasury.bank_branches` (bank → many branches),
`treasury.bank_accounts` (branch, currency, account number, IBAN nullable, opening balance,
current balance; account number unique per tenant; format validation configurable per
country, not hard-coded), `treasury.cash_registers` (name, type, currency, balance; opening
balance locked after first use), each linked to a ledger account (52x / 57x).

### B2. Receipts (encaissements)

`treasury.receipts` + `receipt_invoice_allocations` + `receipt_payments`. A receipt belongs to
a customer, has a reason (`full|advance`), and either allocates to validated sales invoices
("with details", net-to-pay editable per invoice) or has no allocation ("without details").
Methods: cash, cheque, draft/traite, bank transfer, mobile money (Orange/Moov — Mali).
Invoice status is derived: `unpaid → partially_paid → paid` (event
`treasury.receipt.posted` → finance updates the invoice; treasury never writes
`finance.invoices`). Over-allocation refused. Posting writes a journal entry (BNQ/CAI).

### B3. Disbursements (décaissements) — gated on AP

Same shape against supplier/purchase invoices, plus payment orders (ordres de paiement) and a
notify-employee action. Built on the minimal purchase invoice (decision 1). "Without details"
disbursements (partner + amount + reason + account) remain supported.

### B4. Cheque / draft lifecycle (deposit slip)

Instruments table with status `pending → collected | unpaid`. `collected` credits the bank
account or cash register and posts the ledger entry; `unpaid` (cheques) reverses it and
re-opens the invoice allocation. Due-date alerts via worker job: lead/lag days **configurable
per instrument type and per direction** (manual defaults: received cheque alert at due date +1
day, received draft +15 days, issued cheque −1 day, issued draft −15 days — to be confirmed).

### B5. Journals and reports

- Cash journal: derived from cash-register movements.
- Bank journal: import a bank statement (CSV/XLSX), columns date / label / debit / credit /
  balance, per-bank column mapping and date format configurable; preview before commit;
  duplicate-line detection; each line assigned a partner (debit → customer, credit →
  supplier) and optionally matched to a receipt/disbursement (basic reconciliation — more
  than the manual offers).
- Customer/supplier invoice status reports with XLSX export.

### B6. Permissions and events

`treasury.view`, `treasury.manage_receipts`, `treasury.manage_disbursements`,
`treasury.manage_accounts`, `treasury.collect_instruments`, `treasury.import_statements`,
`treasury.add_prior_year_invoice`. Events: `treasury.receipt.posted`,
`treasury.disbursement.posted`, `treasury.instrument.collected`, `treasury.instrument.unpaid`.

## Not taken from the manual

- Tunisian withholding tax on supplier invoices and its 1,000 TND threshold.
- Tunisian RIB (20 digits) format, TND amounts, the 5,000 TND cash cap. If Mali imposes a cash
  ceiling, add as a configurable rule once the accountant confirms the value.
- The 16 March prior-year invoice cutoff — replaced by ledger fiscal-period close plus
  `treasury.add_prior_year_invoice`.
- Shipping / import-export / port-logistics files and shipowner "disbursement account"
  balances.
- The "bureau d'ordre / arrivée" registry as a precondition to attach documents; attachments
  are plain files on the record.
- .NET / DevExpress / SQL Server stack, menu paths, button names, screen layouts.
- Delivery-note (BL) coupling for returns and the non-billable re-delivery — Sonalim has no
  BL flow; revisit if sales adds one.

## Decisions (confirmed 2026-11-03)

1. **Supplier invoices:** build a minimal purchase-invoice entity (draft → validated →
   partially paid/paid; supplier, total or lines, currency, due date) so disbursements allocate
   to invoices. Owner module settled in the plan; its status follows treasury events.
2. **Frozen location vs production:** shift validation is **blocked** (`LOCATION_FROZEN`).
3. **Mobile money:** one treasury account per operator, each linked to its own 5xx ledger
   account set in configuration (the accountant supplies the codes).
4. **Cash ceiling:** none enforced; a configurable rule, empty by default.
5. **Alert offsets:** the manual's values seeded as editable defaults per instrument type and
   direction.
6. **Ledger timing:** treasury is built now and records payments and statuses; ledger postings
   are added by event consumers when Phase 4 lands (record now, post later).

## Delivery order

1. A1 vouchers (receipt, issue, transfer) → A2 inventory → A3 valuation → A4 reports.
   Independent of the ledger; can start now.
2. A1 returns (after sales order issue flow is wired).
3. Minimal purchase invoice → Treasury B1 → B2 → B3 → B4 → B5. No ledger dependency; posting
   consumers are added when Phase 4 lands.

## Testing

Domain (no DB): CMUP formula, count-resolution rules, over-issue/over-return checks,
allocation and invoice-status derivation. Integration (`db` fixture): voucher posting
atomicity, freeze enforcement, inventory close posts adjustments, idempotent consumers,
permission denial. Frontend: bilingual en/fr keys for every new string.
