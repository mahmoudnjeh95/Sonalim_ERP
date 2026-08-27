from core.domain.result import Err, Ok
from core.domain.entities import (
    validate_new_product,
    validate_new_product_attribute,
    validate_new_product_attribute_value,
    validate_new_product_tag,
)


def test_validate_new_product_accepts_valid_input():
    result = validate_new_product(sku="doman-pl-500g", name="Doman PL 500gr", uom_id="uom-1")
    assert isinstance(result, Ok)


def test_validate_new_product_accepts_missing_weight():
    result = validate_new_product(sku="doman-pl-500g", name="Doman PL 500gr", uom_id="uom-1", net_weight_grams=None)
    assert isinstance(result, Ok)


def test_validate_new_product_rejects_non_positive_weight():
    result = validate_new_product(sku="doman-pl-500g", name="Doman PL 500gr", uom_id="uom-1", net_weight_grams=0)
    assert isinstance(result, Err)
    assert result.code == "INVALID_WEIGHT"


def test_validate_new_product_rejects_unknown_lot_serial_tracking():
    result = validate_new_product(sku="s1", name="Semoule", uom_id="uom-1", lot_serial_tracking="barcode")
    assert isinstance(result, Err)
    assert result.code == "INVALID_LOT_SERIAL_TRACKING"


def test_validate_new_product_rejects_unknown_expiry_date_policy():
    result = validate_new_product(sku="s1", name="Semoule", uom_id="uom-1", expiry_date_policy="best_before")
    assert isinstance(result, Err)
    assert result.code == "INVALID_EXPIRY_DATE_POLICY"


def test_validate_new_product_rejects_negative_selling_price():
    result = validate_new_product(sku="s1", name="Semoule", uom_id="uom-1", selling_price=-1)
    assert isinstance(result, Err)
    assert result.code == "INVALID_PRICE"


def test_validate_new_product_rejects_negative_purchase_price():
    result = validate_new_product(sku="s1", name="Semoule", uom_id="uom-1", purchase_price=-1)
    assert isinstance(result, Err)
    assert result.code == "INVALID_PRICE"


def test_validate_new_product_rejects_min_price_above_selling_price():
    result = validate_new_product(sku="s1", name="Semoule", uom_id="uom-1", selling_price=10, min_selling_price=20)
    assert isinstance(result, Err)
    assert result.code == "INVALID_PRICE"


def test_validate_new_product_accepts_min_price_below_selling_price():
    result = validate_new_product(sku="s1", name="Semoule", uom_id="uom-1", selling_price=10, min_selling_price=5)
    assert isinstance(result, Ok)


def test_validate_new_product_attribute_rejects_blank_name():
    result = validate_new_product_attribute(name="  ")
    assert isinstance(result, Err)
    assert result.code == "INVALID_NAME"


def test_validate_new_product_attribute_value_rejects_blank_value():
    result = validate_new_product_attribute_value(value="")
    assert isinstance(result, Err)
    assert result.code == "INVALID_VALUE"


def test_validate_new_product_tag_rejects_blank_name():
    result = validate_new_product_tag(name="")
    assert isinstance(result, Err)
    assert result.code == "INVALID_NAME"
