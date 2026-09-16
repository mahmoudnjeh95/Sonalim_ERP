from __future__ import annotations


def average_landed_cost_by_product(receipt_lines: list[dict]) -> dict[str, float]:
    """Quantity-weighted average landed cost/unit per product, across every
    confirmed receipt regardless of supplier -- see
    PurchaseOrderService.list_confirmed_receipt_line_details for what a
    landed cost is built from. Shared by MaterialConsumptionService (MP has
    no per-line supplier at all) and daily_recap_export.py's packaging
    fallback (a shift's film/carton/scotch/ruban figures are often recorded
    with no supplier named -- see ConsumptionReportService._apply_costs,
    which requires one and leaves such rows unpriced by design)."""
    totals: dict[str, dict[str, float]] = {}
    for line in receipt_lines:
        bucket = totals.setdefault(line["product_id"], {"quantity": 0.0, "cost_base": 0.0})
        bucket["quantity"] += line["quantity"]
        bucket["cost_base"] += line["total_cost_base"]
    return {
        product_id: bucket["cost_base"] / bucket["quantity"]
        for product_id, bucket in totals.items() if bucket["quantity"] > 0
    }
