from decimal import Decimal

from core.domain.result import Err, Ok
from modules.procurement.domain.entities import (
    PurchaseOrder,
    PurchaseOrderLine,
    apply_receipt_to_line,
    compute_cost_anomaly,
    compute_landed_cost,
    confirm_purchase_order_receipt,
    derive_order_status,
    receive_against_order,
    transition_purchase_order,
    validate_new_purchase_order,
    validate_new_purchase_order_line,
    validate_receipt_fees,
)


def _order(status: str = "draft", is_import: bool = False) -> PurchaseOrder:
    return PurchaseOrder(
        id="po1",
        tenant_id="t1",
        supplier_id="supplier1",
        status=status,
        order_date="2026-08-01",
        expected_date="2026-08-15",
        currency_code="EUR",
        notes=None,
        is_import=is_import,
    )


def _line(quantity_ordered: float, quantity_received: float = 0, status: str = "pending") -> PurchaseOrderLine:
    return PurchaseOrderLine(
        id="line1",
        tenant_id="t1",
        purchase_order_id="po1",
        product_id="semoule-ble-dur",
        uom_id="ton-uom",
        quantity_ordered=quantity_ordered,
        quantity_received=quantity_received,
        status=status,
        unit_price=500,
        unit_price_currency="EUR",
    )


def test_validate_new_purchase_order_rejects_blank_currency():
    result = validate_new_purchase_order(currency_code="")
    assert isinstance(result, Err)
    assert result.code == "INVALID_CURRENCY"


def test_validate_new_purchase_order_line_rejects_non_positive_quantity():
    result = validate_new_purchase_order_line(quantity_ordered=0)
    assert isinstance(result, Err)
    assert result.code == "INVALID_QUANTITY"


def test_draft_order_follows_manual_lifecycle_to_ordered():
    order = _order()
    for target in ["validated", "approved", "ordered"]:
        result = transition_purchase_order(order, target)
        assert isinstance(result, Ok), f"expected {order.status} -> {target} to succeed"
        order = result.value
        assert order.status == target


def test_draft_cannot_skip_ahead_to_approved():
    result = transition_purchase_order(_order(), "approved")
    assert isinstance(result, Err)
    assert result.code == "INVALID_TRANSITION"


def test_validated_can_be_refused():
    result = transition_purchase_order(_order("validated"), "refused")
    assert isinstance(result, Ok)
    assert result.value.status == "refused"


def test_cannot_manually_set_order_to_partially_received():
    result = transition_purchase_order(_order("ordered"), "partially_received")
    assert isinstance(result, Err)
    assert result.code == "INVALID_TRANSITION"


def test_cannot_manually_set_order_to_fully_received():
    result = transition_purchase_order(_order("ordered"), "fully_received")
    assert isinstance(result, Err)
    assert result.code == "INVALID_TRANSITION"


def test_receive_against_draft_order_is_rejected():
    result = receive_against_order(_order("draft"), ["partially_received"])
    assert isinstance(result, Err)
    assert result.code == "INVALID_TRANSITION"


def test_apply_receipt_to_line_partial_delivery():
    line = _line(quantity_ordered=10)
    result = apply_receipt_to_line(line, 5)
    assert isinstance(result, Ok)
    assert result.value.quantity_received == 5
    assert result.value.status == "partially_received"


def test_apply_receipt_to_line_completing_delivery():
    line = _line(quantity_ordered=10, quantity_received=5, status="partially_received")
    result = apply_receipt_to_line(line, 5)
    assert isinstance(result, Ok)
    assert result.value.quantity_received == 10
    assert result.value.status == "fully_received"


def test_apply_receipt_to_line_rejects_over_receipt():
    line = _line(quantity_ordered=10, quantity_received=8, status="partially_received")
    result = apply_receipt_to_line(line, 5)
    assert isinstance(result, Err)
    assert result.code == "OVER_RECEIPT"


def test_apply_receipt_to_line_rejects_non_positive_quantity():
    result = apply_receipt_to_line(_line(quantity_ordered=10), 0)
    assert isinstance(result, Err)
    assert result.code == "INVALID_QUANTITY"


def test_two_line_partial_delivery_matches_worked_example():
    """10t semoule ble dur + 20t semoule ble fine ordered; one truck brings 5t + 15t.
    Neither line is complete, so the order must read 'partially received', not
    'all products received' -- exactly the scenario walked through with the user."""
    dur = _line(quantity_ordered=10)
    fine = _line(quantity_ordered=20)

    dur_after = apply_receipt_to_line(dur, 5)
    fine_after = apply_receipt_to_line(fine, 15)
    assert isinstance(dur_after, Ok)
    assert isinstance(fine_after, Ok)
    assert dur_after.value.status == "partially_received"
    assert fine_after.value.status == "partially_received"

    order_result = receive_against_order(_order("ordered"), [dur_after.value.status, fine_after.value.status])
    assert isinstance(order_result, Ok)
    assert order_result.value.status == "partially_received"

    # Second truck brings the remaining 5t + 5t -> both lines complete -> order fully received.
    dur_final = apply_receipt_to_line(dur_after.value, 5)
    fine_final = apply_receipt_to_line(fine_after.value, 5)
    assert isinstance(dur_final, Ok)
    assert isinstance(fine_final, Ok)
    assert dur_final.value.status == "fully_received"
    assert fine_final.value.status == "fully_received"

    final_order_result = receive_against_order(order_result.value, [dur_final.value.status, fine_final.value.status])
    assert isinstance(final_order_result, Ok)
    assert final_order_result.value.status == "fully_received"


def test_derive_order_status_all_pending_stays_ordered():
    assert derive_order_status(["pending", "pending"]) == "ordered"


def test_derive_order_status_mixed_is_partially_received():
    assert derive_order_status(["fully_received", "pending"]) == "partially_received"


def test_derive_order_status_all_fully_received():
    assert derive_order_status(["fully_received", "fully_received"]) == "fully_received"


def test_landed_cost_sums_all_fees():
    result = compute_landed_cost(
        base_cost=1000, license_fee=10, insurance_fee=20, transit_fee=30, transport_fee=40, customs_duty=50, quantity=20
    )
    assert isinstance(result, Ok)
    total_cost, cost_per_unit = result.value
    assert total_cost == 1150
    assert cost_per_unit == 57.5


def test_landed_cost_includes_handling_fee():
    result = compute_landed_cost(
        base_cost=1000,
        license_fee=0,
        insurance_fee=0,
        transit_fee=0,
        transport_fee=0,
        customs_duty=0,
        handling_fee=60,
        quantity=20,
    )
    assert isinstance(result, Ok)
    total_cost, cost_per_unit = result.value
    assert total_cost == 1060
    assert cost_per_unit == 53


def test_validate_receipt_fees_allows_local_receipt_with_only_handling_and_transport():
    result = validate_receipt_fees(is_import=False, license_fee=0, insurance_fee=0, transit_fee=0, customs_duty=0)
    assert isinstance(result, Ok)


def test_validate_receipt_fees_rejects_customs_duty_on_local_order():
    result = validate_receipt_fees(is_import=False, license_fee=0, insurance_fee=0, transit_fee=0, customs_duty=50)
    assert isinstance(result, Err)
    assert result.code == "IMPORT_FEE_ON_LOCAL_ORDER"


def test_validate_receipt_fees_allows_any_fee_on_import_order():
    result = validate_receipt_fees(is_import=True, license_fee=10, insurance_fee=10, transit_fee=10, customs_duty=10)
    assert isinstance(result, Ok)


def test_cost_anomaly_none_when_no_baseline():
    deviation_pct, is_anomaly = compute_cost_anomaly(cost_per_unit=1000, baseline_avg_cost_per_unit=None)
    assert deviation_pct is None
    assert is_anomaly is False


def test_cost_anomaly_flags_receipt_well_above_average():
    # 500 vs a 400 baseline is +25%, over the 15% threshold.
    deviation_pct, is_anomaly = compute_cost_anomaly(cost_per_unit=500, baseline_avg_cost_per_unit=400)
    assert deviation_pct == 25
    assert is_anomaly is True


def test_cost_anomaly_does_not_flag_receipt_within_threshold():
    # 440 vs a 400 baseline is +10%, under the 15% threshold.
    deviation_pct, is_anomaly = compute_cost_anomaly(cost_per_unit=440, baseline_avg_cost_per_unit=400)
    assert deviation_pct == 10
    assert is_anomaly is False


def test_cost_anomaly_does_not_flag_a_cheaper_than_usual_receipt():
    deviation_pct, is_anomaly = compute_cost_anomaly(cost_per_unit=200, baseline_avg_cost_per_unit=400)
    assert deviation_pct == -50
    assert is_anomaly is False


def test_landed_cost_rejects_zero_quantity():
    result = compute_landed_cost(
        base_cost=100, license_fee=0, insurance_fee=0, transit_fee=0, transport_fee=0, customs_duty=0, quantity=0
    )
    assert isinstance(result, Err)
    assert result.code == "INVALID_QUANTITY"


def test_confirm_purchase_order_receipt_from_draft_succeeds():
    result = confirm_purchase_order_receipt("draft")
    assert isinstance(result, Ok)
    assert result.value == "confirmed"


def test_confirm_purchase_order_receipt_rejects_already_confirmed():
    result = confirm_purchase_order_receipt("confirmed")
    assert isinstance(result, Err)
    assert result.code == "INVALID_TRANSITION"


def test_receipts_add_up_exactly_to_what_was_ordered():
    # In float, 0.1 + 0.2 > 0.3: the second delivery used to be refused as an over-receipt.
    first = apply_receipt_to_line(_line(quantity_ordered=0.3), 0.1)
    second = apply_receipt_to_line(first.value, 0.2)
    assert isinstance(second, Ok)
    assert second.value.quantity_received == Decimal("0.3")
    assert second.value.status == "fully_received"


def test_landed_cost_is_decimal_to_the_cent():
    result = compute_landed_cost(
        base_cost=0.1, license_fee=0, insurance_fee=0, transit_fee=0, transport_fee=0.2, customs_duty=0, quantity=1
    )
    total_cost, cost_per_unit = result.value
    assert total_cost == Decimal("0.3")
    assert isinstance(cost_per_unit, Decimal)
