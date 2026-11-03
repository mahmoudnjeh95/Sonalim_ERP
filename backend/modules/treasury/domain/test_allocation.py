import datetime
from decimal import Decimal

from core.domain.result import Err, Ok
from modules.treasury.domain.allocation import check_allocations, check_invoice_target, check_payments, check_prior_year

D = Decimal


def _cash(amount):
    return {"method": "cash", "amount": amount}


def _cheque(amount, **extra):
    return {"method": "cheque", "amount": amount, "number": "C1", "bank_name": "BDM", "due_date": "2026-05-01", **extra}


def test_payments_total_and_validation():
    assert check_payments(D("0"), [_cash(100), _cash(50)], None) == Ok(D("150"))
    assert check_payments(D("0"), [], None).code == "NO_PAYMENTS"
    assert check_payments(D("0"), [_cash(0)], None).code == "INVALID_AMOUNT"
    assert check_payments(D("0"), [{"method": "gold", "amount": 1}], None).code == "INVALID_METHOD"


def test_instrument_needs_identifying_fields():
    assert isinstance(check_payments(D("0"), [_cheque(10)], None), Ok)
    assert check_payments(D("0"), [{"method": "draft", "amount": 10}], None).code == "INSTRUMENT_FIELDS_REQUIRED"


def test_cash_limit_only_when_configured_and_per_payment():
    assert isinstance(check_payments(D("0"), [_cash(10_000_000)], None), Ok)
    assert check_payments(D("0"), [_cash(600)], D("500")).code == "CASH_LIMIT_EXCEEDED"
    assert isinstance(check_payments(D("0"), [_cash(500), _cash(500)], D("500")), Ok)
    assert isinstance(check_payments(D("0"), [_cheque(10_000)], D("500")), Ok)


def test_allocations_full_must_match_total():
    assert check_allocations(D("100"), [("a", D("60")), ("b", D("40"))], with_details=True, reason="full") == Ok(D("0"))
    assert check_allocations(D("100"), [("a", D("60"))], with_details=True, reason="full").code == "ALLOCATION_MISMATCH"
    assert check_allocations(D("100"), [("a", D("101"))], with_details=True, reason="full").code == "OVER_ALLOCATION"


def test_with_details_needs_allocations_but_advance_may_leave_credit():
    assert check_allocations(D("100"), [], with_details=True, reason="full").code == "ALLOCATIONS_REQUIRED"
    assert check_allocations(D("100"), [("a", D("30"))], with_details=True, reason="advance") == Ok(D("70"))
    assert check_allocations(D("100"), [], with_details=False, reason="full") == Ok(D("100"))


def test_duplicate_invoice_in_allocations_refused():
    assert check_allocations(D("100"), [("a", D("50")), ("a", D("50"))], with_details=True, reason="full").code == "DUPLICATE_ALLOCATION"


def _invoice(**over):
    return {"status": "issued", "partner_id": "p", "currency": "XOF", "remaining": D("100"), **over}


def test_invoice_target_checks():
    ok = dict(direction="in", document_currency="XOF", partner_id="p")
    assert isinstance(check_invoice_target(_invoice(), D("100"), **ok), Ok)
    assert check_invoice_target(_invoice(status="draft"), D("10"), **ok).code == "INVOICE_NOT_VALIDATED"
    assert check_invoice_target(_invoice(), D("101"), **ok).code == "OVER_ALLOCATION"
    assert check_invoice_target(_invoice(currency="EUR"), D("10"), **ok).code == "CURRENCY_MISMATCH"
    assert check_invoice_target(_invoice(partner_id="q"), D("10"), **ok).code == "PARTNER_MISMATCH"
    out = dict(direction="out", document_currency="XOF", partner_id="p")
    assert isinstance(check_invoice_target(_invoice(status="validated"), D("10"), **out), Ok)
    assert check_invoice_target(_invoice(status="issued"), D("10"), **out).code == "INVOICE_NOT_VALIDATED"


def test_prior_year_needs_permission():
    assert isinstance(check_prior_year(datetime.date(2025, 12, 1), datetime.date(2026, 1, 5), allowed=False), Err)
    assert isinstance(check_prior_year(datetime.date(2025, 12, 1), datetime.date(2026, 1, 5), allowed=True), Ok)
    assert isinstance(check_prior_year(datetime.date(2026, 1, 1), datetime.date(2026, 1, 5), allowed=False), Ok)
