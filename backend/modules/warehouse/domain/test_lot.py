import datetime

from core.domain.result import Err, Ok
from modules.warehouse.domain.lot import (
    Lot,
    LotStock,
    issue_from_lot,
    receive_into_lot,
    transition_lot,
    validate_expiry_date,
    validate_new_lot,
)


def _lot(status: str = "active") -> Lot:
    return Lot(
        id="lot1",
        tenant_id="t1",
        product_id="semolina",
        lot_number="LOT-2026-001",
        status=status,
        expiry_date="2026-12-01",
        produced_at=None,
        source_type="procurement_receipt",
        source_id="receipt1",
    )


def test_validate_new_lot_accepts_valid_input():
    result = validate_new_lot(lot_number="LOT-2026-001", quantity=5)
    assert isinstance(result, Ok)


def test_validate_new_lot_rejects_blank_lot_number():
    result = validate_new_lot(lot_number="  ", quantity=5)
    assert isinstance(result, Err)
    assert result.code == "INVALID_LOT_NUMBER"


def test_validate_new_lot_rejects_non_positive_quantity():
    result = validate_new_lot(lot_number="LOT-2026-001", quantity=0)
    assert isinstance(result, Err)
    assert result.code == "INVALID_QUANTITY"


def test_active_lot_can_be_consumed():
    result = transition_lot(_lot(), "consumed")
    assert isinstance(result, Ok)
    assert result.value.status == "consumed"


def test_active_lot_can_expire():
    result = transition_lot(_lot(), "expired")
    assert isinstance(result, Ok)
    assert result.value.status == "expired"


def test_consumed_lot_has_no_further_transitions():
    result = transition_lot(_lot("consumed"), "active")
    assert isinstance(result, Err)
    assert result.code == "INVALID_TRANSITION"


def test_receive_into_lot_increases_quantity():
    stock = LotStock(lot_id="lot1", location_id="loc1", quantity_on_hand=5)
    result = receive_into_lot(stock, 3)
    assert isinstance(result, Ok)
    assert result.value.quantity_on_hand == 8


def test_receive_into_lot_rejects_non_positive_quantity():
    stock = LotStock(lot_id="lot1", location_id="loc1", quantity_on_hand=5)
    result = receive_into_lot(stock, 0)
    assert isinstance(result, Err)
    assert result.code == "INVALID_QUANTITY"


def test_issue_from_lot_within_on_hand_succeeds():
    stock = LotStock(lot_id="lot1", location_id="loc1", quantity_on_hand=5)
    result = issue_from_lot(stock, 5)
    assert isinstance(result, Ok)
    assert result.value.quantity_on_hand == 0


def test_issue_from_lot_beyond_on_hand_fails():
    stock = LotStock(lot_id="lot1", location_id="loc1", quantity_on_hand=5)
    result = issue_from_lot(stock, 6)
    assert isinstance(result, Err)
    assert result.code == "INSUFFICIENT_STOCK"


def test_a_dlc_on_or_after_the_production_day_is_valid():
    assert isinstance(validate_expiry_date(expiry_date=datetime.date(2029, 7, 5), produced_at="2026-07-05T00:00:00"), Ok)
    assert isinstance(validate_expiry_date(expiry_date=datetime.date(2026, 7, 5), produced_at="2026-07-05T00:00:00"), Ok)


def test_a_dlc_before_the_production_day_is_refused():
    result = validate_expiry_date(expiry_date=datetime.date(2026, 7, 4), produced_at="2026-07-05T00:00:00")
    assert isinstance(result, Err)
    assert result.code == "INVALID_EXPIRY"


def test_a_lot_with_no_production_day_has_nothing_to_compare_a_dlc_against():
    assert isinstance(validate_expiry_date(expiry_date=datetime.date(2020, 1, 1), produced_at=None), Ok)
