# Event Catalog

| Event | Version | Producer | Consumers | Payload |
|---|---|---|---|---|
| `core.product.created` | 1.0 | core | warehouse | `product_id`, `sku`, `is_sellable` |
| `warehouse.stock.reserved` | 1.0 | warehouse | — | `product_id`, `location_id`, `quantity`, `reference` |
| `warehouse.stock.received` | 1.0 | warehouse | — | `product_id`, `location_id`, `quantity`, `reference` |
| `warehouse.stock.issued` | 1.0 | warehouse | — | `product_id`, `location_id`, `quantity`, `reference` |
| `warehouse.cycle_count.completed` | 1.0 | warehouse | — | `cycle_count_id`, `site_id`, `line_count`, `variance_count` |
| `warehouse.putaway.confirmed` | 1.0 | warehouse | — | `product_id`, `from_location_id`, `to_location_id`, `quantity`, `followed_suggestion` |
| `warehouse.pick_list.cancelled` | 1.0 | warehouse | — | `pick_list_id`, `source_type`, `source_id` — the order's reservation was released with it |
| `warehouse.shipment.shipped` | 1.0 | warehouse | sales | `shipment_id`, `pick_list_id`, `source_type`, `source_id`, `location_id`, `lines` (`product_id`, `quantity_requested`, `quantity_shipped`) — stock was issued; a short pick's remainder was released, not backordered |
| `warehouse.reservation.expired` | 1.0 | warehouse | — | `reservation_id`, `product_id`, `location_id`, `reference`, `quantity` — a hold made with an explicit `expires_at` lapsed and the worker gave `quantity` back to available stock |
| `warehouse.replenishment.approved` | 1.0 | warehouse | procurement | `proposal_id`, `product_id`, `uom_id`, `quantity`, `supplier_id`, `site_id` — a reorder-rule proposal was approved; procurement drafts a purchase order (notes `replenishment:{proposal_id}`, idempotent on it) |
| `maintenance.parts.purchase_requested` | 1.0 | maintenance | procurement | `request_id`, `job_number`, `lines` (`line_id`, `product_id`, `uom_id`, `quantity`) — a supervisor approved a spare-parts request and these lines (or their remainders) could not be issued from stock; only the purchase lines are listed, `quantity` in the product's own unit. Procurement drafts one purchase order with every line, no supplier, unit price 0 XOF (notes `maintenance:{request_id}`, idempotent on it) |
| `production.work_order.closed` | 2.0 | production | — | `work_order_id`, `product_id`, `planned_quantity` — fires when an OF is closed. Closure is archival and posts no stock, so this carries what was planned, not what was produced. Replaces `production.work_order.completed`, which no longer exists: the OF stopped meaning "completed with output" in Phase 1. |
| `production.report.validated` | 1.0 | production | — | `report_id`, `of_id`, `report_type`, `report_date` — the event that means stock moved. |
| `production.report.rejected` | 1.0 | production | — | `report_id`, `of_id`, `report_type`, `reason` |
| `crm.lead.qualified` | 1.0 | crm | — | `lead_id`, `email` |
| `crm.lead.converted` | 1.0 | crm | — | `lead_id`, `partner_id`, `opportunity_id` |
| `crm.opportunity.won` | 1.1 | crm | — | `opportunity_id`, `partner_id`, `name`, `amount`, `sales_order_id` — a draft sales order is created synchronously in the same transaction as the win, so `sales_order_id` is always populated |
| `crm.opportunity.lost` | 1.0 | crm | — | `opportunity_id`, `partner_id`, `name`, `amount` |
| `sales.order.confirmed` | 1.1 | sales | finance, warehouse | `order_id`, `partner_id`, `total_amount`, `currency`, `location_id`, `reservation_reference`, `lines` (`product_id`, `quantity`) — 1.1 added the last three (additive) so warehouse can open a pick list against the reservation confirm already made; warehouse skips 1.0 events, which lack them |
| `finance.invoice.issued` | 1.0 | finance | finance | `invoice_id`, `partner_id`, `amount`, `currency` |
| `finance.invoice.paid` | 1.0 | finance | finance | `invoice_id`, `partner_id`, `amount`, `currency` |
| `finance.journal_entry.posted` | 1.0 | finance | — | `entry_id`, `journal_code`, `source_module`, `source_id` — an entry was posted to the ledger (manual entries have null source fields); fires once per entry, reversals included |
| `procurement.purchase_order.status_changed` | 1.0 | procurement | — | `purchase_order_id`, `from_status`, `to_status` |
| `procurement.purchase_order_receipt.confirmed` | 1.0 | procurement | warehouse | `purchase_order_receipt_id`, `purchase_order_id`, `location_id`, `lines` (`product_id`, `quantity`, `uom_id`, `lot_number`) |
| `procurement.purchase_invoice.validated` | 1.0 | procurement | — | `invoice_id`, `partner_id`, `amount`, `currency`, `due_date` |
| `treasury.receipt.posted` | 1.0 | treasury | finance (invoices and ledger, when enabled) | `receipt_id`, `partner_id`, `allocations` (`invoice_id`, `amount`), `total`, `currency` |
| `treasury.receipt.cancelled` | 1.0 | treasury | finance (invoices and ledger, when enabled) | `receipt_id`, `allocations` (`invoice_id`, `amount`) |
| `treasury.disbursement.posted` | 1.0 | treasury | procurement, finance (ledger, when enabled) | `disbursement_id`, `partner_id`, `allocations` (`invoice_id`, `amount`), `total`, `currency` |
| `treasury.disbursement.cancelled` | 1.0 | treasury | procurement, finance (ledger, when enabled) | `disbursement_id`, `allocations` (`invoice_id`, `amount`) |
| `treasury.instrument.collected` | 1.0 | treasury | finance (ledger, when enabled) | `instrument_id`, `direction`, `method`, `amount`, `currency`, `account_id` |
| `treasury.instrument.unpaid` | 1.0 | treasury | finance (invoices and ledger, when enabled), procurement | `instrument_id`, `direction`, `amount`, `currency`, `rejection_fee` (null when none), `allocations` (`invoice_id`, `amount`) |
| `warehouse.voucher.posted` | 1.0 | warehouse | — | `voucher_id`, `type`, `number` |
| `qc.quality_report.validated` | 1.0 | qc | — | `quality_report_id`, `is_conforming` |
| `qc.non_conformity.raised` | 1.0 | qc | — | `non_conformity_id`, `of_id`, `product_id`, `quantity`, `location_id` |
| `qc.non_conformity.dispositioned` | 1.0 | qc | production | `non_conformity_id`, `of_id`, `product_id`, `lines` (`component`, `disposition`, `quantity`) |
| `hr.presence_month.closed` | 1.0 | hr | payroll (phase 3) | `period` (ISO date, first day of the month) — every presence day of the month is locked and complete; `PresenceService.month_summary` for it is final until the month is reopened. |
| `payroll.run.approved` | 1.0 | payroll | finance | `run_id`, `period`, `run_type` — a run's payslips are final (four-eyes, confirmed rule set, closed presence); finance posts the PAIE entry from `PayrollPostingService.posting_lines` |
| `payroll.run.paid` | 1.0 | payroll | finance | `run_id`, `period` — every payout batch of the run is confirmed; finance clears 422 from `PayrollPostingService.payment_lines` |
| `payroll.run.reversed` | 1.0 | payroll | finance | `run_id`, `period` — an approved or paid run was cancelled; its deductions are released; finance posts the mirror entry |

Every event uses the standard envelope defined in `.claude/skills/erp-platform-architecture/SKILL.md`. Add a row here before merging any new publishing code.
