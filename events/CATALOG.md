# Event Catalog

| Event | Version | Producer | Consumers | Payload |
|---|---|---|---|---|
| `warehouse.stock.reserved` | 1.0 | warehouse | — | `product_id`, `location_id`, `quantity`, `reference` |
| `warehouse.stock.received` | 1.0 | warehouse | — | `product_id`, `location_id`, `quantity`, `reference` |
| `production.work_order.completed` | 1.0 | production | — | `work_order_id`, `product_id`, `quantity` |
| `crm.lead.qualified` | 1.0 | crm | — | `lead_id`, `email` |
| `crm.lead.converted` | 1.0 | crm | — | `lead_id`, `partner_id`, `opportunity_id` |
| `sales.order.confirmed` | 1.0 | sales | finance | `order_id`, `partner_id`, `total_amount`, `currency` |
| `finance.invoice.issued` | 1.0 | finance | — | `invoice_id`, `partner_id`, `amount`, `currency` |
| `finance.invoice.paid` | 1.0 | finance | — | `invoice_id`, `partner_id`, `amount`, `currency` |
| `procurement.purchase_order.status_changed` | 1.0 | procurement | — | `purchase_order_id`, `from_status`, `to_status` |
| `procurement.purchase_order_receipt.confirmed` | 1.0 | procurement | warehouse | `purchase_order_receipt_id`, `purchase_order_id`, `location_id`, `lines` (`product_id`, `quantity`, `uom_id`, `lot_number`) |

Every event uses the standard envelope defined in `.claude/skills/erp-platform-architecture/SKILL.md`. Add a row here before merging any new publishing code.
