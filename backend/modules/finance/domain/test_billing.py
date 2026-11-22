from decimal import Decimal as D

from modules.finance.domain.billing import (
    BilledLine,
    CreditableInvoice,
    amount_due,
    customer_credit,
    lines_to_credit,
    lines_to_invoice,
    order_prices,
    whole_francs,
)
from modules.finance.domain.entities import status_for_payment


def test_a_product_on_several_order_lines_is_priced_at_their_weighted_average():
    prices = order_prices([("p", D(10), D(100)), ("p", D(30), D(200)), ("q", D(5), D(7))])
    assert prices["p"] == (D(40), D(175)) and prices["q"] == (D(5), D(7))


def test_a_delivery_bills_what_it_carried_never_past_the_order():
    ordered = {"p": (D(30), D(100)), "q": (D(5), D(10))}
    first = lines_to_invoice({"p": D(10), "x": D(3)}, ordered, {})
    assert first == [BilledLine("p", D(10), D(100))]  # x is not on the order, so it has no price
    rest = lines_to_invoice({"p": D(25), "q": D(5)}, ordered, {"p": D(10)})
    assert rest == [BilledLine("p", D(20), D(100)), BilledLine("q", D(5), D(10))]
    assert lines_to_invoice({"p": D(1)}, ordered, {"p": D(30)}) == []


def test_the_total_is_in_whole_francs():
    assert whole_francs([BilledLine("p", D("3"), D("33.5"))]) == D(101)  # 100.5 rounds half up


def test_a_return_credits_the_latest_invoice_first_and_only_what_was_billed():
    latest = CreditableInvoice("inv2", {"p": (D(20), D(100))}, {"p": D(15)})
    older = CreditableInvoice("inv1", {"p": (D(10), D(90))}, {})
    credit = lines_to_credit({"p": D(12), "z": D(4)}, [latest, older])
    assert credit == {"inv2": [BilledLine("p", D(5), D(100))], "inv1": [BilledLine("p", D(7), D(90))]}
    assert lines_to_credit({"p": D(50)}, [older]) == {"inv1": [BilledLine("p", D(10), D(90))]}


def test_what_is_due_and_a_customer_credit():
    assert amount_due(D(1000), D(300)) == D(700) and amount_due(D(100), D(150)) == 0
    assert customer_credit(D(700), D(1000)) == D(300) and customer_credit(D(700), D(200)) == 0


def test_a_fully_credited_invoice_is_settled_and_one_credited_below_its_payments_is_paid():
    assert status_for_payment(0.0, 0.0) == "paid"
    assert status_for_payment(700.0, 1000.0) == "paid"
    assert status_for_payment(700.0, 200.0) == "partially_paid"


# ---- manual invoice lines ---------------------------------------------------------------------------------

from core.domain.result import Err as _Err, Ok as _Ok  # noqa: E402
from modules.finance.domain.billing import ManualLine, check_manual_lines, document_totals  # noqa: E402


def _manual(**kw):
    base = dict(product_id=None, description="Transport", quantity=D("2"), list_price=D("1000"))
    return ManualLine(**{**base, **kw})


def test_manual_line_net_price_and_totals():
    line = _manual(discount_rate=D("10"), vat_rate=D("18"))
    assert line.net_unit_price == D("900.0000")
    assert document_totals([line.billed()]) == (D("1800"), D("324"), D("2124"))


def test_manual_lines_are_checked():
    assert isinstance(check_manual_lines([_manual()]), _Ok)
    assert check_manual_lines([]).code == "INVOICE_EMPTY"
    assert check_manual_lines([_manual(description=" ")]).code == "INVALID_LINE"
    assert check_manual_lines([_manual(product_id="p", description=None)]).__class__ is _Ok
    for bad in ({"quantity": D("0")}, {"list_price": D("-1")}, {"discount_rate": D("101")}, {"vat_rate": D("101")}):
        result = check_manual_lines([_manual(**bad)])
        assert isinstance(result, _Err) and result.code == "INVALID_LINE"
