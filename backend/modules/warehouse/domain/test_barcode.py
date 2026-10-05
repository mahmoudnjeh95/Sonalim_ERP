from __future__ import annotations

import datetime

from core.domain.result import Err, Ok
from modules.warehouse.domain.barcode import (
    gtin_check_digit,
    is_valid_gtin,
    looks_like_gs1,
    normalize_gtin,
    parse_gs1,
    validate_barcode,
)

EAN13 = "4006381333931"  # a real, valid EAN-13
GTIN14 = "14006381333938"  # the same item at a carton packaging level (indicator 1)


def test_the_check_digit_matches_known_codes():
    assert gtin_check_digit(EAN13[:-1]) == 1
    assert gtin_check_digit(GTIN14[:-1]) == 8


def test_gtin_validity_covers_length_and_check_digit():
    assert is_valid_gtin(EAN13)
    assert is_valid_gtin(GTIN14)
    assert not is_valid_gtin("4006381333932")  # wrong check digit
    assert not is_valid_gtin("40063813339")  # 11 digits
    assert not is_valid_gtin("40063813339A1")


def test_gtins_normalise_to_fourteen_digits():
    assert normalize_gtin(EAN13) == "0" + EAN13


def test_a_gtin_barcode_is_stored_normalised():
    assert validate_barcode(barcode=f" {EAN13} ", barcode_type="gtin", units_per_scan=1) == Ok("0" + EAN13)


def test_a_mistyped_gtin_is_refused():
    result = validate_barcode(barcode="4006381333932", barcode_type="gtin", units_per_scan=1)
    assert isinstance(result, Err) and result.code == "INVALID_GTIN"


def test_an_internal_code_is_only_trimmed():
    assert validate_barcode(barcode=" PAL-0042 ", barcode_type="internal", units_per_scan=1) == Ok("PAL-0042")


def test_units_per_scan_must_be_positive():
    assert isinstance(validate_barcode(barcode="X", barcode_type="internal", units_per_scan=0), Err)


def test_parses_the_human_readable_form():
    data = parse_gs1(f"(01){GTIN14}(17)270331(10)4187SNL")
    assert data is not None
    assert (data.gtin, data.lot_number, data.expiry_date) == (GTIN14, "4187SNL", datetime.date(2027, 3, 31))


def test_parses_the_raw_scanner_form_with_group_separators():
    data = parse_gs1(f"]C101{GTIN14}10LOT7\x1d3720")
    assert data is not None
    assert (data.gtin, data.lot_number, data.count) == (GTIN14, "LOT7", 20)


def test_day_zero_means_the_last_day_of_the_month():
    data = parse_gs1(f"(01){GTIN14}(17)270200")
    assert data is not None and data.expiry_date == datetime.date(2027, 2, 28)


def test_an_invalid_embedded_gtin_is_not_gs1():
    assert parse_gs1("(01)14006381333939") is None


def test_an_undelimitable_raw_ai_is_not_guessed():
    assert parse_gs1("99ABC") is None


def test_gs1_detection_needs_a_marker():
    assert looks_like_gs1("(01)123")
    assert looks_like_gs1("]C10112")
    assert not looks_like_gs1(EAN13)
