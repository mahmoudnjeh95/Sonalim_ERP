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
