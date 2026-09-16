from core.domain.result import Err, Ok
from modules.warehouse.domain.entities import StockLevel, adjust, consume_in_production, issue, reserve, send_to_production


def test_reserve_within_available_quantity_succeeds():
    level = StockLevel(location_id="loc1", product_id="p1", quantity_on_hand=10, quantity_reserved=2)
    result = reserve(level, 5)
    assert isinstance(result, Ok)
    assert result.value.quantity_reserved == 7
    assert result.value.location_id == "loc1"


def test_reserve_beyond_available_quantity_fails():
    level = StockLevel(location_id="loc1", product_id="p1", quantity_on_hand=10, quantity_reserved=8)
    result = reserve(level, 5)
    assert isinstance(result, Err)
    assert result.code == "INSUFFICIENT_STOCK"


def test_reserve_non_positive_quantity_fails():
    level = StockLevel(location_id="loc1", product_id="p1", quantity_on_hand=10, quantity_reserved=0)
    result = reserve(level, 0)
    assert isinstance(result, Err)
    assert result.code == "INVALID_QUANTITY"


def test_issue_within_on_hand_quantity_succeeds():
    level = StockLevel(location_id="loc1", product_id="p1", quantity_on_hand=10, quantity_reserved=0)
    result = issue(level, 4)
    assert isinstance(result, Ok)
    assert result.value.quantity_on_hand == 6


def test_issue_beyond_on_hand_quantity_fails():
    level = StockLevel(location_id="loc1", product_id="p1", quantity_on_hand=10, quantity_reserved=0)
    result = issue(level, 11)
    assert isinstance(result, Err)
    assert result.code == "INSUFFICIENT_STOCK"


def test_issue_non_positive_quantity_fails():
    level = StockLevel(location_id="loc1", product_id="p1", quantity_on_hand=10, quantity_reserved=0)
    result = issue(level, 0)
    assert isinstance(result, Err)
    assert result.code == "INVALID_QUANTITY"


def test_adjust_positive_delta_increases_on_hand():
    level = StockLevel(location_id="loc1", product_id="p1", quantity_on_hand=10, quantity_reserved=0)
    result = adjust(level, 3)
    assert isinstance(result, Ok)
    assert result.value.quantity_on_hand == 13


def test_adjust_negative_delta_decreases_on_hand():
    level = StockLevel(location_id="loc1", product_id="p1", quantity_on_hand=10, quantity_reserved=0)
    result = adjust(level, -3)
    assert isinstance(result, Ok)
    assert result.value.quantity_on_hand == 7


def test_adjust_below_zero_fails():
    level = StockLevel(location_id="loc1", product_id="p1", quantity_on_hand=10, quantity_reserved=0)
    result = adjust(level, -11)
    assert isinstance(result, Err)
    assert result.code == "INVALID_QUANTITY"


def test_adjust_zero_delta_fails():
    level = StockLevel(location_id="loc1", product_id="p1", quantity_on_hand=10, quantity_reserved=0)
    result = adjust(level, 0)
    assert isinstance(result, Err)
    assert result.code == "INVALID_QUANTITY"


def test_send_to_production_within_on_hand_succeeds():
    level = StockLevel(location_id="loc1", product_id="p1", quantity_on_hand=10, quantity_reserved=0)
    result = send_to_production(level, 4)
    assert isinstance(result, Ok)
    assert result.value.quantity_on_hand == 6
    assert result.value.quantity_in_production == 4


def test_send_to_production_beyond_on_hand_fails():
    level = StockLevel(location_id="loc1", product_id="p1", quantity_on_hand=10, quantity_reserved=0)
    result = send_to_production(level, 11)
    assert isinstance(result, Err)
    assert result.code == "INSUFFICIENT_STOCK"


def test_send_to_production_non_positive_quantity_fails():
    level = StockLevel(location_id="loc1", product_id="p1", quantity_on_hand=10, quantity_reserved=0)
    result = send_to_production(level, 0)
    assert isinstance(result, Err)
    assert result.code == "INVALID_QUANTITY"


def test_consume_in_production_within_bucket_succeeds():
    level = StockLevel(location_id="loc1", product_id="p1", quantity_on_hand=6, quantity_reserved=0, quantity_in_production=4)
    result = consume_in_production(level, 4)
    assert isinstance(result, Ok)
    assert result.value.quantity_in_production == 0
    assert result.value.quantity_on_hand == 6


def test_consume_in_production_beyond_bucket_fails():
    level = StockLevel(location_id="loc1", product_id="p1", quantity_on_hand=6, quantity_reserved=0, quantity_in_production=4)
    result = consume_in_production(level, 5)
    assert isinstance(result, Err)
    assert result.code == "INSUFFICIENT_STOCK"


def test_consume_in_production_non_positive_quantity_fails():
    level = StockLevel(location_id="loc1", product_id="p1", quantity_on_hand=6, quantity_reserved=0, quantity_in_production=4)
    result = consume_in_production(level, 0)
    assert isinstance(result, Err)
    assert result.code == "INVALID_QUANTITY"
