import datetime
from decimal import Decimal as D

from core.domain.result import Err, Ok
from modules.sales.domain.pricing import (
    ListWindow,
    PriceBreak,
    PricedLine,
    best_break,
    check_discount_limit,
    check_line,
    check_price_list,
    check_quote_transition,
    compute_totals,
    conversion_rate,
    display_number,
    effective_discount,
    is_expired,
    resolve,
)

DAY = datetime.date(2026, 6, 1)


def test_totals_apply_line_discount_then_document_discount_then_vat():
    lines = [PricedLine(D(10), D(1000), D(10), D(18)), PricedLine(D(3), D(333), D(0), D(0))]
    totals = compute_totals(lines, D(5))
    # 10 000 + 999 gross; nets 8 550 and 949.05 -> 9 499 excl.; VAT 18 % of 8 550 = 1 539
    assert (totals.gross, totals.excl_tax, totals.vat, totals.incl_tax) == (D(10999), D(9499), D(1539), D(11038))
    assert totals.discount == D(1500)


def test_combined_discount_compounds():
    assert effective_discount(D(10), D(5)) == D("14.5")
    assert effective_discount(D(0), D(0)) == D(0)


def test_discount_limit_counts_line_and_document_together():
    assert isinstance(check_discount_limit([D(8)], D(0), limit=D(10), may_exceed=False), Ok)
    refused = check_discount_limit([D(8)], D(5), limit=D(10), may_exceed=False)  # 12.6 % combined
    assert isinstance(refused, Err) and refused.code == "DISCOUNT_ABOVE_LIMIT" and "12.6" in refused.message
    assert isinstance(check_discount_limit([D(8)], D(5), limit=D(10), may_exceed=True), Ok)
    assert check_discount_limit([], D(11), limit=D(10), may_exceed=False).code == "DISCOUNT_ABOVE_LIMIT"


def test_line_checks():
    assert isinstance(check_line(quantity=D(1), unit_price=D(0), discount_rate=D(0), vat_rate=D(18)), Ok)
    assert check_line(quantity=D(0), unit_price=D(1), discount_rate=D(0), vat_rate=D(0)).code == "INVALID_QUANTITY"
    assert check_line(quantity=D(1), unit_price=D(-1), discount_rate=D(0), vat_rate=D(0)).code == "INVALID_PRICE"
    assert check_line(quantity=D(1), unit_price=D(1), discount_rate=D(101), vat_rate=D(0)).code == "INVALID_DISCOUNT"
    assert check_line(quantity=D(1), unit_price=D(1), discount_rate=D(0), vat_rate=D(-1)).code == "INVALID_VAT_RATE"


def test_best_break_is_the_highest_reached():
    breaks = [PriceBreak("l", D(1), D(100)), PriceBreak("l", D(50), D(90)), PriceBreak("l", D(200), D(80))]
    assert best_break(breaks, D(49)).unit_price == D(100)
    assert best_break(breaks, D(50)).unit_price == D(90)
    assert best_break(breaks, D(1000)).unit_price == D(80)
    assert best_break([PriceBreak("l", D(10), D(5))], D(2)) is None


def test_resolution_prefers_the_customers_list_then_the_default_then_the_catalog():
    customer = ListWindow("c", "Grossistes", datetime.date(2026, 1, 1), datetime.date(2026, 12, 31))
    default = ListWindow("d", "Tarif public", None, None)
    breaks = [PriceBreak("c", D(1), D(900)), PriceBreak("d", D(1), D(1000))]
    got = resolve(quantity=D(5), on=DAY, customer_list=customer, default_list=default, breaks=breaks, catalog_price=D(1100),
                  customer_discount=D(3))
    assert (got.unit_price, got.price_list_id, got.source, got.discount_rate) == (D(900), "c", "price_list", D(3))
    # out of the customer list's dates: the default list
    got = resolve(quantity=D(5), on=datetime.date(2027, 1, 5), customer_list=customer, default_list=default, breaks=breaks,
                  catalog_price=D(1100))
    assert (got.unit_price, got.price_list_id) == (D(1000), "d")
    # the product is on no list: the catalog
    got = resolve(quantity=D(5), on=DAY, customer_list=customer, default_list=default, breaks=[], catalog_price=D(1100))
    assert (got.unit_price, got.source, got.price_list_id) == (D(1100), "catalog", None)
    # an inactive list is skipped
    inactive = ListWindow("c", "Grossistes", None, None, active=False)
    got = resolve(quantity=D(5), on=DAY, customer_list=inactive, default_list=None, breaks=breaks, catalog_price=D(1100))
    assert got.source == "catalog"


def test_price_list_checks():
    assert check_price_list(name=" ", valid_from=None, valid_to=None).code == "INVALID_PRICE_LIST"
    assert check_price_list(name="A", valid_from=DAY, valid_to=DAY - datetime.timedelta(days=1)).code == "INVALID_PRICE_LIST"
    assert isinstance(check_price_list(name="A", valid_from=DAY, valid_to=DAY), Ok)


def test_quote_lifecycle_rules():
    assert isinstance(check_quote_transition("draft", "sent"), Ok)
    assert isinstance(check_quote_transition("sent", "accepted"), Ok)
    assert check_quote_transition("accepted", "refused").code == "INVALID_TRANSITION"
    assert check_quote_transition("expired", "accepted").code == "INVALID_TRANSITION"
    assert is_expired("sent", DAY - datetime.timedelta(days=1), DAY)
    assert not is_expired("sent", DAY, DAY)
    assert not is_expired("accepted", DAY - datetime.timedelta(days=10), DAY)


def test_numbers_and_conversion_rate():
    assert display_number("DV-2026-000001", 1) == "DV-2026-000001"
    assert display_number("DV-2026-000001", 3) == "DV-2026-000001-3"
    assert conversion_rate(["accepted", "refused", "expired", "sent", "superseded", "accepted"]) == D("50.0")
    assert conversion_rate(["draft", "sent"]) is None
