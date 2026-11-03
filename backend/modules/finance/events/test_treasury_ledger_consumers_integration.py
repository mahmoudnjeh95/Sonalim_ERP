"""Treasury events into the ledger, through the real consumer registry. Treasury documents are created
with the real treasury services so the envelopes are the ones treasury publishes."""
from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from ulid import ULID

from core.domain.result import Ok
from core.events.consumers import _process
from modules.finance.api.period_service import PeriodService
from modules.finance.api.posting_rule_service import PostingRuleService
from modules.finance.events import ledger_consumers  # noqa: F401  (registers the handlers)
from modules.finance.testing_support import NoCommitConnection
from modules.treasury.api.document_service import DocumentService
from modules.treasury.api.instrument_service import InstrumentService
from modules.treasury.api.service import AccountService, SettingsService

D = Decimal
DAY = datetime.date(2030, 3, 4)
DUE = datetime.date(2030, 4, 4)


@pytest.fixture
def env(ledger):
    db, tenant, actor = ledger["db"], ledger["tenant"], ledger["actor"]
    customer, supplier = str(ULID()), str(ULID())
    for pid, kind in ((customer, "customer"), (supplier, "supplier")):
        db.execute(
            "INSERT INTO core.partners (id, tenant_id, name, kind, status) VALUES (%s, %s, %s, %s, 'active')",
            (pid, tenant, f"P {pid}", kind),
        )
    accounts = AccountService(db)

    def account(name, code):
        fields = {"name": name, "currency": "XOF", "opening_balance": 100000}
        if code:
            fields["ledger_account_code"] = code
        return accounts.create_account(tenant_id=tenant, actor_id=actor, kind="cash", fields=fields).value["id"]

    return {
        **ledger,
        "customer": customer,
        "supplier": supplier,
        "cash": account("Caisse", "571"),
        "bank": account("Coffre", "521"),
        "nocode": account("Sans code", None),
    }


def _rule(env, kind, code, debit=None, credit=None, journal="BNQ"):
    result = PostingRuleService(env["db"]).create_rule(
        tenant_id=env["tenant"], actor_id=env["actor"], source="treasury", source_kind=kind, code=code,
        debit_account_code=debit, credit_account_code=credit, journal_code=journal,
    )
    assert isinstance(result, Ok), result


def _enable(env):
    SettingsService(env["db"]).set_setting(
        tenant_id=env["tenant"], actor_id=env["actor"], key="ledger_posting_enabled", value=True
    )


def _rules(env):
    _rule(env, "receipt_payment", "*", credit="411", journal="CAI")
    _rule(env, "disbursement_payment", "*", debit="401", journal="CAI")
    _rule(env, "receipt_payment", "cheque", debit="585", credit="411", journal="BNQ")
    _rule(env, "instrument_collected", "in", credit="585", journal="BNQ")
    _rule(env, "instrument_unpaid", "in", debit="411", credit="585", journal="OD")
    _rule(env, "receipt_advance", "*", debit="411", credit="585", journal="OD")
    _rule(env, "disbursement_advance", "*", debit="585", credit="401", journal="OD")


def _document(env, direction, amount=1000, account=None, payments=None):
    result = DocumentService(env["db"]).create_and_post(
        tenant_id=env["tenant"], actor_id=env["actor"], direction=direction,
        partner_id=env["customer"] if direction == "in" else env["supplier"], doc_date=DAY, currency="XOF",
        payments=payments or [{"method": "cash", "amount": amount, "account_id": account or env["cash"]}],
        reason="advance", with_details=False, correlation_id="c",
    )
    assert isinstance(result, Ok), result
    return result.value["id"]


def _envelope(env, event_type, key, entity_id):
    envelope = env["db"].execute(
        "SELECT payload FROM events.outbox WHERE event_type = %s AND payload -> 'payload' ->> %s = %s ORDER BY created_at DESC",
        (event_type, key, entity_id),
    ).fetchone()[0]
    envelope["occurred_at"] = "2030-03-05T10:00:00+00:00"
    return envelope


def _deliver(env, envelope) -> bool:
    return _process(NoCommitConnection(env["db"]), envelope)


def _entries(env, source_id, advance=False):
    """The document's entries; the advance part (every test document is an advance) is left out unless asked for."""
    rows = env["db"].execute(
        "SELECT id, source_kind, journal_code, status FROM finance.journal_entries "
        "WHERE tenant_id = %s AND source_module = 'treasury' AND source_id = %s ORDER BY source_kind",
        (env["tenant"], source_id),
    ).fetchall()
    return [r for r in rows if advance or "_advance" not in r[1]]


def _lines(env, entry_id):
    return env["db"].execute(
        "SELECT account_code, debit, credit, partner_id FROM finance.journal_lines WHERE entry_id = %s ORDER BY line_no",
        (entry_id,),
    ).fetchall()


def _failures(env, source_id):
    return env["db"].execute(
        "SELECT source_kind, error_code, status FROM finance.posting_failures WHERE tenant_id = %s AND source_id = %s",
        (env["tenant"], source_id),
    ).fetchall()


def test_posting_is_off_by_default_and_leaves_no_entry_and_no_failure(env):
    document_id = _document(env, "in")
    assert _deliver(env, _envelope(env, "treasury.receipt.posted", "receipt_id", document_id)) is True
    assert _entries(env, document_id) == []
    assert _failures(env, document_id) == []


def test_enabled_without_rules_the_posting_is_refused_and_recorded(env):
    _enable(env)
    document_id = _document(env, "in")
    assert _deliver(env, _envelope(env, "treasury.receipt.posted", "receipt_id", document_id)) is False
    assert _failures(env, document_id) == [("receipt_payment", "POSTING_RULE_MISSING", "open")]
    assert _entries(env, document_id) == []


def test_a_cash_receipt_posts_a_balanced_entry_once(env):
    _rules(env)
    _enable(env)
    document_id = _document(env, "in", amount=2500)
    envelope = _envelope(env, "treasury.receipt.posted", "receipt_id", document_id)
    assert _deliver(env, envelope) is True
    assert _deliver(env, envelope) is True
    assert _deliver(env, _envelope(env, "treasury.receipt.posted", "receipt_id", document_id)) is True
    [(entry_id, kind, journal, status)] = _entries(env, document_id)
    assert (kind, journal, status) == ("receipt_payment_cash", "CAI", "posted")
    assert _lines(env, entry_id) == [("571", D(2500), D(0), None), ("411", D(0), D(2500), env["customer"])]


def test_a_disbursement_debits_the_supplier_against_the_account_code(env):
    _rules(env)
    _enable(env)
    document_id = _document(env, "out", amount=700)
    assert _deliver(env, _envelope(env, "treasury.disbursement.posted", "disbursement_id", document_id)) is True
    [(entry_id, kind, *_)] = _entries(env, document_id)
    assert kind == "disbursement_payment_cash"
    assert _lines(env, entry_id) == [("401", D(700), D(0), env["supplier"]), ("571", D(0), D(700), None)]


def test_an_account_without_a_ledger_code_is_refused_and_recorded(env):
    _rules(env)
    _enable(env)
    document_id = _document(env, "in", account=env["nocode"])
    assert _deliver(env, _envelope(env, "treasury.receipt.posted", "receipt_id", document_id)) is False
    assert _failures(env, document_id) == [("receipt_payment", "LEDGER_ACCOUNT_MISSING", "open")]


def test_a_closed_period_is_refused_and_recorded(env):
    _rules(env)
    _enable(env)
    PeriodService(env["db"]).close_period(tenant_id=env["tenant"], actor_id=env["actor"], period=datetime.date(2030, 3, 1))
    document_id = _document(env, "in")
    assert _deliver(env, _envelope(env, "treasury.receipt.posted", "receipt_id", document_id)) is False
    assert _failures(env, document_id) == [("receipt_payment", "PERIOD_CLOSED", "open")]


def test_cancelling_a_receipt_reverses_its_entry_and_cancelling_twice_adds_nothing(env):
    _rules(env)
    _enable(env)
    document_id = _document(env, "in", amount=900)
    assert _deliver(env, _envelope(env, "treasury.receipt.posted", "receipt_id", document_id)) is True
    cancelled = DocumentService(env["db"]).cancel(
        tenant_id=env["tenant"], actor_id=env["actor"], document_id=document_id, direction="in", correlation_id="c"
    )
    assert isinstance(cancelled, Ok), cancelled
    envelope = _envelope(env, "treasury.receipt.cancelled", "receipt_id", document_id)
    assert _deliver(env, envelope) is True
    assert _deliver(env, envelope) is True
    entries = _entries(env, document_id)
    assert [(kind, status) for _, kind, _, status in entries] == [
        ("receipt_payment_cash", "reversed"),
        ("receipt_payment_cash_reversal", "posted"),
    ]
    original, reversal = _lines(env, entries[0][0]), _lines(env, entries[1][0])
    assert [(a, d, c) for a, d, c, _ in reversal] == [(a, c, d) for a, d, c, _ in original]


def test_cancelling_a_document_that_was_never_posted_is_a_quiet_no_op(env):
    _rules(env)
    _enable(env)
    document_id = _document(env, "in")
    DocumentService(env["db"]).cancel(
        tenant_id=env["tenant"], actor_id=env["actor"], document_id=document_id, direction="in", correlation_id="c"
    )
    assert _deliver(env, _envelope(env, "treasury.receipt.cancelled", "receipt_id", document_id)) is True
    assert _entries(env, document_id) == []
    assert _failures(env, document_id) == []


def test_a_cheque_goes_through_holding_then_the_bank_and_back_when_it_bounces(env):
    _rules(env)
    _enable(env)
    payments = [{"method": "cheque", "amount": 400, "number": "CH1", "bank_name": "BIM", "due_date": DUE}]
    document_id = _document(env, "in", payments=payments)
    instrument_id = env["db"].execute("SELECT id FROM treasury.instruments WHERE document_id = %s", (document_id,)).fetchone()[0]

    assert _deliver(env, _envelope(env, "treasury.receipt.posted", "receipt_id", document_id)) is True
    [(received, kind, *_)] = _entries(env, document_id)
    assert kind == "receipt_payment_cheque"
    assert _lines(env, received) == [("585", D(400), D(0), None), ("411", D(0), D(400), env["customer"])]

    slip = InstrumentService(env["db"]).post_slip(
        tenant_id=env["tenant"], actor_id=env["actor"], account_id=env["bank"], slip_date=DAY,
        items=[{"instrument_id": instrument_id, "outcome": "collected"}], correlation_id="c",
    )
    assert isinstance(slip, Ok), slip
    assert _deliver(env, _envelope(env, "treasury.instrument.collected", "instrument_id", instrument_id)) is True
    [(collected, kind, journal, _)] = _entries(env, instrument_id)
    assert (kind, journal) == ("instrument_collected", "BNQ")
    assert _lines(env, collected) == [("521", D(400), D(0), None), ("585", D(0), D(400), None)]

    bounced = InstrumentService(env["db"]).mark_unpaid(
        tenant_id=env["tenant"], actor_id=env["actor"], instrument_id=instrument_id, correlation_id="c"
    )
    assert isinstance(bounced, Ok), bounced
    unpaid = _envelope(env, "treasury.instrument.unpaid", "instrument_id", instrument_id)
    assert _deliver(env, unpaid) is True
    assert _deliver(env, unpaid) is True
    entries = _entries(env, instrument_id)
    assert {kind: status for _, kind, _, status in entries} == {
        "instrument_collected": "reversed",
        "instrument_collected_reversal": "posted",
        "instrument_unpaid": "posted",
    }
    unpaid_entry = next(entry_id for entry_id, kind, *_ in entries if kind == "instrument_unpaid")
    assert _lines(env, unpaid_entry) == [("411", D(400), D(0), env["customer"]), ("585", D(0), D(400), None)]


def test_the_flag_is_a_real_boolean_setting_defaulting_to_off(env):
    settings = SettingsService(env["db"])
    assert settings.get_settings(tenant_id=env["tenant"])["ledger_posting_enabled"] is False
    refused = settings.set_setting(tenant_id=env["tenant"], actor_id=env["actor"], key="ledger_posting_enabled", value="yes")
    assert refused.code == "INVALID_SETTING"


def test_the_part_tied_to_no_invoice_is_booked_by_the_advance_rule(env):
    _rules(env)
    _enable(env)
    document_id = _document(env, "in", amount=1200)
    assert _deliver(env, _envelope(env, "treasury.receipt.posted", "receipt_id", document_id)) is True
    [advance] = [e for e in _entries(env, document_id, advance=True) if e[1].endswith("_advance")]
    assert advance[1:3] == ("receipt_payment_advance", "OD")
    assert _lines(env, advance[0]) == [("411", D(1200), D(0), env["customer"]), ("585", D(0), D(1200), None)]
