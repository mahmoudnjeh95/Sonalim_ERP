# Event Catalog

| Event | Version | Producer | Consumers | Payload |
|---|---|---|---|---|
| `core.product.created` | 1.0 | core | warehouse | `product_id`, `sku`, `is_sellable` |
| `warehouse.stock.reserved` | 1.0 | warehouse | — | `product_id`, `location_id`, `quantity`, `reference` |
| `warehouse.stock.received` | 1.0 | warehouse | — | `product_id`, `location_id`, `quantity`, `reference` |
| `warehouse.stock.issued` | 1.0 | warehouse | — | `product_id`, `location_id`, `quantity`, `reference` |
| `production.work_order.closed` | 2.0 | production | — | `work_order_id`, `product_id`, `planned_quantity` — fires when an OF is closed. Closure is archival and posts no stock, so this carries what was planned, not what was produced. Replaces `production.work_order.completed`, which no longer exists: the OF stopped meaning "completed with output" in Phase 1. |
| `production.report.validated` | 1.0 | production | — | `report_id`, `of_id`, `report_type`, `report_date` — the event that means stock moved. |
| `production.report.rejected` | 1.0 | production | — | `report_id`, `of_id`, `report_type`, `reason` |
| `crm.lead.qualified` | 1.0 | crm | — | `lead_id`, `email` |
| `crm.lead.converted` | 1.0 | crm | — | `lead_id`, `partner_id`, `opportunity_id` |
| `crm.opportunity.won` | 1.0 | crm | — | `opportunity_id`, `partner_id`, `name`, `amount` |
| `crm.opportunity.lost` | 1.0 | crm | — | `opportunity_id`, `partner_id`, `name`, `amount` |
| `sales.order.confirmed` | 1.0 | sales | finance | `order_id`, `partner_id`, `total_amount`, `currency` |
| `finance.invoice.issued` | 1.0 | finance | — | `invoice_id`, `partner_id`, `amount`, `currency` |
| `finance.invoice.paid` | 1.0 | finance | — | `invoice_id`, `partner_id`, `amount`, `currency` |
| `procurement.purchase_order.status_changed` | 1.0 | procurement | — | `purchase_order_id`, `from_status`, `to_status` |
| `procurement.purchase_order_receipt.confirmed` | 1.0 | procurement | warehouse | `purchase_order_receipt_id`, `purchase_order_id`, `location_id`, `lines` (`product_id`, `quantity`, `uom_id`, `lot_number`) |
| `qc.quality_report.validated` | 1.0 | qc | — | `quality_report_id`, `of_id`, `is_conforming` |
| `qc.non_conformity.raised` | 1.0 | qc | — | `non_conformity_id`, `of_id`, `product_id`, `quantity`, `location_id` |
| `qc.non_conformity.dispositioned` | 1.0 | qc | production | `non_conformity_id`, `of_id`, `product_id`, `lines` (`component`, `disposition`, `quantity`) |

Every event uses the standard envelope defined in `.claude/skills/erp-platform-architecture/SKILL.md`. Add a row here before merging any new publishing code.
