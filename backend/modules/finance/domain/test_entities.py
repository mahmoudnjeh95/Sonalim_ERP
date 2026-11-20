from decimal import Decimal

from core.domain.result import Err, Ok
from modules.finance.domain.entities import Invoice, transition


def _invoice(status: str) -> Invoice:
    return Invoice(id="1", partner_id="c1", amount=100.0, currency="USD", status=status)


def test_draft_invoice_can_be_issued():
    result = transition(_invoice("draft"), "issued")
    assert isinstance(result, Ok)
    assert result.value.status == "issued"


def test_draft_invoice_cannot_be_paid_directly():
    result = transition(_invoice("draft"), "paid")
    assert isinstance(result, Err)
    assert result.code == "INVALID_TRANSITION"


def test_issued_invoice_can_be_paid():
    result = transition(_invoice("issued"), "paid")
    assert isinstance(result, Ok)
    assert result.value.status == "paid"


def test_status_follows_amount_paid():
    from modules.finance.domain.entities import status_for_payment

    assert status_for_payment(100.0, 0) == "issued"
    assert status_for_payment(100.0, 30.0) == "partially_paid"
    assert status_for_payment(100.0, 100.0) == "paid"


def test_partially_paid_invoice_cannot_be_marked_paid_by_hand():
    assert transition(_invoice("partially_paid"), "paid").code == "INVALID_TRANSITION"


def test_invoice_amounts_are_decimal():
    invoice = Invoice(id="1", partner_id="c1", amount=0.1, currency="XOF", status="draft", amount_paid=0.2)
    assert invoice.amount + invoice.amount_paid == Decimal("0.3")
