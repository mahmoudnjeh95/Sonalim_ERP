from decimal import Decimal

from core.domain.result import Err, Ok
from modules.procurement.domain.purchase_invoice import (
    Line,
    OrderLineFacts,
    check_credit_lines,
    check_line,
    check_lines_total,
    check_not_over_received,
    check_payment_delta,
    check_transition,
    compute_totals,
    match_warnings,
    remaining,
    status_for_payment,
    supplier_credit,
)

D = Decimal


def test_draft_can_be_validated_or_cancelled():
    assert isinstance(check_transition("draft", "validated"), Ok)
    assert isinstance(check_transition("draft", "cancelled"), Ok)


def test_validated_can_only_be_cancelled_manually():
    assert isinstance(check_transition("validated", "cancelled"), Ok)
    assert isinstance(check_transition("validated", "paid"), Err)


def test_payment_states_are_not_manual_targets():
    assert check_transition("validated", "partially_paid").code == "INVALID_TRANSITION"
    assert check_transition("paid", "cancelled").code == "INVALID_TRANSITION"


def test_status_is_derived_from_amount_paid():
    assert status_for_payment(D("100"), D("0")) == "validated"
    assert status_for_payment(D("100"), D("40")) == "partially_paid"
    assert status_for_payment(D("100"), D("100")) == "paid"


def test_remaining_never_negative():
    assert remaining(D("100"), D("30")) == D("70")
    assert remaining(D("100"), D("100")) == D("0")


def test_payment_delta_bounds():
    assert check_payment_delta(D("100"), D("30"), D("70")) == Ok(D("100"))
    assert check_payment_delta(D("100"), D("30"), D("-30")) == Ok(D("0"))
    assert check_payment_delta(D("100"), D("30"), D("71")).code == "OVER_ALLOCATION"
    assert check_payment_delta(D("100"), D("30"), D("-31")).code == "OVER_ALLOCATION"


def test_lines_total_optional_and_tolerant():
    assert isinstance(check_lines_total(D("100"), []), Ok)
    assert isinstance(check_lines_total(D("100"), [(D("2"), D("50"))]), Ok)
    assert isinstance(check_lines_total(D("100"), [(D("3"), D("33.333"))]), Ok)
    assert check_lines_total(D("100"), [(D("1"), D("90"))]).code == "TOTAL_MISMATCH"


def test_totals_apply_the_line_discount_before_vat_and_round_to_the_franc():
    totals = compute_totals([Line(D("3"), D("1000"), D("10"), D("18")), Line(D("1"), D("333.33"), D("0"), D("0"))])
    # 3 x 1000 = 3000 less 10 % = 2700, VAT 18 % = 486; plus 333.33 without VAT.
    assert (totals.gross, totals.discount, totals.excl_tax, totals.vat, totals.incl_tax) == (D("3333"), D("300"), D("3033"), D("486"), D("3519"))


def test_vat_is_rounded_on_the_total_not_per_line():
    totals = compute_totals([Line(D("1"), D("10.25"), vat_rate=D("18")) for _ in range(4)])
    assert (totals.excl_tax, totals.vat, totals.incl_tax) == (D("41"), D("7"), D("48"))


def test_a_line_needs_a_product_or_a_description_and_sane_rates():
    ok = dict(description="Film", product_id=None, quantity=D("1"), unit_price=D("5"), discount_rate=D("0"), vat_rate=D("18"))
    assert isinstance(check_line(**ok), Ok)
    assert isinstance(check_line(**{**ok, "description": "", "product_id": "p1"}), Ok)
    assert check_line(**{**ok, "description": " "}).code == "LINE_DESCRIPTION_REQUIRED"
    assert check_line(**{**ok, "quantity": D("0")}).code == "INVALID_QUANTITY"
    assert check_line(**{**ok, "unit_price": D("-1")}).code == "INVALID_UNIT_PRICE"
    assert check_line(**{**ok, "discount_rate": D("101")}).code == "INVALID_DISCOUNT"
    assert check_line(**{**ok, "vat_rate": D("-1")}).code == "INVALID_VAT_RATE"


def test_a_fully_credited_or_overpaid_invoice_is_settled_and_shows_the_supplier_credit():
    assert status_for_payment(D("0"), D("0")) == "paid"
    assert status_for_payment(D("800"), D("1000")) == "paid"
    assert supplier_credit(D("800"), D("1000")) == D("200")
    assert supplier_credit(D("800"), D("300")) == D("0")
    # Taking back a payment from an invoice credited below what was paid stays possible.
    assert check_payment_delta(D("800"), D("1000"), D("-1000")) == Ok(D("0"))
    assert check_payment_delta(D("800"), D("1000"), D("1")).code == "OVER_ALLOCATION"


def test_three_way_match_warns_on_quantity_beyond_receipts_and_on_price():
    facts = {"po1": OrderLineFacts(received=D("10"), invoiced_elsewhere=D("4"), order_unit_price=D("100")),
             "po2": OrderLineFacts(received=D("5"), invoiced_elsewhere=D("0"), order_unit_price=None)}
    warnings = match_warnings([("a", "po1", D("4"), D("100")), ("b", "po1", D("3"), D("110")), ("c", "po2", D("5"), D("1")),
                               ("d", None, D("99"), D("1"))], facts)
    assert [(w["code"], w["line"]) for w in warnings] == [("QUANTITY_OVER_RECEIVED", "a"), ("PRICE_DIFFERS_FROM_ORDER", "b")]
    assert warnings[0]["receivable"] == D("6") and warnings[0]["invoiced"] == D("7")
    assert check_not_over_received(warnings, may_override=False).code == "INVOICED_MORE_THAN_RECEIVED"
    assert isinstance(check_not_over_received(warnings, may_override=True), Ok)
    assert isinstance(check_not_over_received(warnings[1:], may_override=False), Ok)


def test_a_credit_note_line_is_capped_by_what_the_invoice_line_has_left():
    invoice = {"l1": D("1000"), "l2": D("500")}
    assert isinstance(check_credit_lines(invoice, {"l1": D("600")}, [("l1", D("400")), ("l2", D("500"))]), Ok)
    assert check_credit_lines(invoice, {"l1": D("600")}, [("l1", D("300")), ("l1", D("101"))]).code == "CREDIT_EXCEEDS_INVOICE"
    assert check_credit_lines(invoice, {}, [("other", D("1"))]).code == "CREDIT_LINE_NOT_ON_INVOICE"
