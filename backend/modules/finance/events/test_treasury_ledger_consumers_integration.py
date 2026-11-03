"""Treasury events into the ledger, through the real consumer registry. Treasury documents are created
with the real treasury services so the envelopes are the ones treasury publishes."""
from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from ulid import ULID

from core.domain.result import Err, Ok
from core.events.consumers import _process
from modules.finance.api.ledger_event_postings import retry_failure
from modules.finance.api.period_service import PeriodService
from modules.finance.api.posting_rule_service import PostingRuleService
from modules.finance.events import ledger_consumers  # noqa: F401  (registers the handlers)
from modules.finance.testing_support import NoCommitConnection
from modules.treasury.api.document_service import DocumentService
from modules.treasury.api.instrument_service import InstrumentService
from modules.treasury.api.service import AccountService, BankService, SettingsService

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
    treasury_bank = BankService(db).create_bank(tenant_id=tenant, actor_id=actor, name="BDM").value
    branch = BankService(db).add_branch(tenant_id=tenant, actor_id=actor, bank_id=treasury_bank["id"], name="Centre").value
    real_bank = accounts.create_account(
        tenant_id=tenant, actor_id=actor, kind="bank",
        fields={"name": "BDM XOF", "currency": "XOF", "branch_id": branch["id"], "account_number": "001",
                "opening_balance": 100000, "ledger_account_code": "521"},
    ).value["id"]
    mobile = accounts.create_account(
        tenant_id=tenant, actor_id=actor, kind="mobile_money",
        fields={"name": "Orange", "currency": "XOF", "operator": "orange_money", "phone": "7",
                "opening_balance": 100000, "ledger_account_code": "552"},
    ).value["id"]

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
        "real_bank": real_bank,
        "mobile": mobile,
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
    _rule(env, "receipt_payment", "transfer", credit="411", journal="BNQ")
    _rule(env, "receipt_payment", "mobile_money", credit="411", journal="BNQ")
    _rule(env, "disbursement_payment", "cheque", debit="401", credit="585", journal="BNQ")
    _rule(env, "instrument_collected", "out", debit="585", journal="BNQ")
    _rule(env, "instrument_unpaid", "out", debit="585", credit="401", journal="OD")


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


def _failure_id(env, source_id):
    return env["db"].execute(
        "SELECT id FROM finance.posting_failures WHERE tenant_id = %s AND source_id = %s", (env["tenant"], source_id)
    ).fetchone()[0]


def _cheque_payment(amount=400, number="CH1"):
    return {"method": "cheque", "amount": amount, "number": number, "bank_name": "BIM", "due_date": DUE}


def _instrument_of(env, document_id):
    return env["db"].execute("SELECT id FROM treasury.instruments WHERE document_id = %s", (document_id,)).fetchone()[0]


def _collect(env, instrument_id, account=None):
    slip = InstrumentService(env["db"]).post_slip(
        tenant_id=env["tenant"], actor_id=env["actor"], account_id=account or env["real_bank"], slip_date=DAY,
        items=[{"instrument_id": instrument_id, "outcome": "collected"}], correlation_id="c",
    )
    assert isinstance(slip, Ok), slip


def _bounce(env, instrument_id):
    bounced = InstrumentService(env["db"]).mark_unpaid(
        tenant_id=env["tenant"], actor_id=env["actor"], instrument_id=instrument_id, correlation_id="c"
    )
    assert isinstance(bounced, Ok), bounced


def _cancel(env, document_id, direction):
    return DocumentService(env["db"]).cancel(
        tenant_id=env["tenant"], actor_id=env["actor"], document_id=document_id, direction=direction, correlation_id="c"
    )


def _per_account(env, source_ids):
    """Debit minus credit per account over every entry of these sources, reversals included."""
    rows = env["db"].execute(
        "SELECT l.account_code, SUM(l.debit - l.credit) FROM finance.journal_lines l "
        "JOIN finance.journal_entries e ON e.id = l.entry_id "
        "WHERE e.tenant_id = %s AND e.source_module = 'treasury' AND e.source_id = ANY(%s) GROUP BY l.account_code",
        (env["tenant"], list(source_ids)),
    ).fetchall()
    return {code: total for code, total in rows if total != 0}


def test_retrying_a_refused_receipt_that_was_cancelled_since_posts_nothing_and_resolves_the_failure(env):
    _enable(env)
    document_id = _document(env, "in", amount=800)
    assert _deliver(env, _envelope(env, "treasury.receipt.posted", "receipt_id", document_id)) is False
    assert isinstance(_cancel(env, document_id, "in"), Ok)
    assert _deliver(env, _envelope(env, "treasury.receipt.cancelled", "receipt_id", document_id)) is True
    _rules(env)  # the cause of the refusal is fixed, so only the status check stops the posting
    failure_id = _failure_id(env, document_id)

    result = retry_failure(env["db"], tenant_id=env["tenant"], actor_id=env["actor"], failure_id=failure_id)

    assert isinstance(result, Ok) and result.value == []
    assert _entries(env, document_id, advance=True) == []
    assert _failures(env, document_id) == [("receipt_payment", "POSTING_RULE_MISSING", "resolved")]


def test_a_receipt_event_delivered_after_the_cancellation_posts_nothing(env):
    _rules(env)
    _enable(env)
    document_id = _document(env, "in")
    posted = _envelope(env, "treasury.receipt.posted", "receipt_id", document_id)
    assert isinstance(_cancel(env, document_id, "in"), Ok)
    assert _deliver(env, _envelope(env, "treasury.receipt.cancelled", "receipt_id", document_id)) is True
    assert _deliver(env, posted) is True
    assert _entries(env, document_id, advance=True) == []


def test_retrying_a_refused_collection_of_a_cheque_that_bounced_since_leaves_no_money_in_the_bank(env):
    _rule(env, "receipt_payment", "cheque", debit="585", credit="411", journal="BNQ")
    _rule(env, "receipt_advance", "*", debit="411", credit="585", journal="OD")
    _rule(env, "instrument_unpaid", "in", debit="411", credit="585", journal="OD")
    _enable(env)
    document_id = _document(env, "in", payments=[_cheque_payment()])
    instrument_id = _instrument_of(env, document_id)
    assert _deliver(env, _envelope(env, "treasury.receipt.posted", "receipt_id", document_id)) is True
    _collect(env, instrument_id)
    assert _deliver(env, _envelope(env, "treasury.instrument.collected", "instrument_id", instrument_id)) is False
    _bounce(env, instrument_id)
    assert _deliver(env, _envelope(env, "treasury.instrument.unpaid", "instrument_id", instrument_id)) is True
    _rule(env, "instrument_collected", "in", credit="585", journal="BNQ")
    failure_id = _failure_id(env, instrument_id)

    result = retry_failure(env["db"], tenant_id=env["tenant"], actor_id=env["actor"], failure_id=failure_id)

    assert isinstance(result, Ok) and result.value == []
    assert [kind for _, kind, *_ in _entries(env, instrument_id)] == ["instrument_unpaid"]
    assert "521" not in _per_account(env, [document_id, instrument_id])


@pytest.mark.parametrize("bounced", [False, True])
def test_treasury_refuses_to_cancel_a_document_whose_cheque_was_processed_so_the_ledger_never_sees_it(env, bounced):
    _rules(env)
    _enable(env)
    document_id = _document(env, "in", payments=[_cheque_payment()])
    instrument_id = _instrument_of(env, document_id)
    assert _deliver(env, _envelope(env, "treasury.receipt.posted", "receipt_id", document_id)) is True
    _collect(env, instrument_id)
    assert _deliver(env, _envelope(env, "treasury.instrument.collected", "instrument_id", instrument_id)) is True
    if bounced:
        _bounce(env, instrument_id)
        assert _deliver(env, _envelope(env, "treasury.instrument.unpaid", "instrument_id", instrument_id)) is True
    before = _entries(env, document_id, advance=True)

    refused = _cancel(env, document_id, "in")

    assert isinstance(refused, Err) and refused.code == "INSTRUMENT_ALREADY_PROCESSED"
    assert env["db"].execute(
        "SELECT count(*) FROM events.outbox WHERE event_type = 'treasury.receipt.cancelled' AND payload -> 'payload' ->> 'receipt_id' = %s",
        (document_id,),
    ).fetchone()[0] == 0
    assert _entries(env, document_id, advance=True) == before


def test_an_issued_cheque_goes_through_holding_then_leaves_the_bank(env):
    _rules(env)
    _enable(env)
    document_id = _document(env, "out", payments=[_cheque_payment(650)])
    instrument_id = _instrument_of(env, document_id)
    assert _deliver(env, _envelope(env, "treasury.disbursement.posted", "disbursement_id", document_id)) is True
    [(issued, kind, journal, _)] = _entries(env, document_id)
    assert (kind, journal) == ("disbursement_payment_cheque", "BNQ")
    assert _lines(env, issued) == [("401", D(650), D(0), env["supplier"]), ("585", D(0), D(650), None)]

    _collect(env, instrument_id)
    assert _deliver(env, _envelope(env, "treasury.instrument.collected", "instrument_id", instrument_id)) is True
    [(collected, kind, *_)] = _entries(env, instrument_id)
    assert kind == "instrument_collected"
    assert _lines(env, collected) == [("585", D(650), D(0), None), ("521", D(0), D(650), None)]


def test_an_issued_cheque_that_bounces_puts_the_money_and_the_supplier_debt_back(env):
    _rules(env)
    _enable(env)
    document_id = _document(env, "out", payments=[_cheque_payment(650)])
    instrument_id = _instrument_of(env, document_id)
    assert _deliver(env, _envelope(env, "treasury.disbursement.posted", "disbursement_id", document_id)) is True
    _collect(env, instrument_id)
    assert _deliver(env, _envelope(env, "treasury.instrument.collected", "instrument_id", instrument_id)) is True
    _bounce(env, instrument_id)
    assert _deliver(env, _envelope(env, "treasury.instrument.unpaid", "instrument_id", instrument_id)) is True

    entries = _entries(env, instrument_id)
    assert {kind: status for _, kind, _, status in entries} == {
        "instrument_collected": "reversed",
        "instrument_collected_reversal": "posted",
        "instrument_unpaid": "posted",
    }
    unpaid_entry = next(entry_id for entry_id, kind, *_ in entries if kind == "instrument_unpaid")
    assert _lines(env, unpaid_entry) == [("585", D(650), D(0), None), ("401", D(0), D(650), env["supplier"])]
    assert "521" not in _per_account(env, [instrument_id])


def test_cancelling_a_disbursement_reverses_it_and_nets_every_account_to_zero(env):
    _rules(env)
    _enable(env)
    document_id = _document(env, "out", payments=[
        {"method": "cash", "amount": 700, "account_id": env["cash"]},
        _cheque_payment(300),
    ])
    assert _deliver(env, _envelope(env, "treasury.disbursement.posted", "disbursement_id", document_id)) is True
    assert _per_account(env, [document_id]) != {}
    assert isinstance(_cancel(env, document_id, "out"), Ok)
    envelope = _envelope(env, "treasury.disbursement.cancelled", "disbursement_id", document_id)
    assert _deliver(env, envelope) is True
    assert _deliver(env, envelope) is True
    statuses = {kind: status for _, kind, _, status in _entries(env, document_id, advance=True)}
    assert statuses == {
        "disbursement_payment_advance": "reversed",
        "disbursement_payment_advance_reversal": "posted",
        "disbursement_payment_cash": "reversed",
        "disbursement_payment_cash_reversal": "posted",
        "disbursement_payment_cheque": "reversed",
        "disbursement_payment_cheque_reversal": "posted",
    }
    assert _per_account(env, [document_id]) == {}
    assert _failures(env, document_id) == []


def _mixed_receipt(env):
    return _document(env, "in", payments=[
        {"method": "cash", "amount": 1000, "account_id": env["cash"]},
        {"method": "transfer", "amount": 2000, "account_id": env["real_bank"]},
        {"method": "mobile_money", "amount": 500, "account_id": env["mobile"]},
        _cheque_payment(400),
    ])


def test_a_mixed_receipt_posts_one_entry_per_method_each_in_its_journal(env):
    _rules(env)
    _enable(env)
    document_id = _mixed_receipt(env)
    assert _deliver(env, _envelope(env, "treasury.receipt.posted", "receipt_id", document_id)) is True
    entries = {kind: (entry_id, journal) for entry_id, kind, journal, _ in _entries(env, document_id, advance=True)}
    assert {kind: journal for kind, (_, journal) in entries.items()} == {
        "receipt_payment_advance": "OD",
        "receipt_payment_cash": "CAI",
        "receipt_payment_cheque": "BNQ",
        "receipt_payment_mobile_money": "BNQ",
        "receipt_payment_transfer": "BNQ",
    }
    assert _lines(env, entries["receipt_payment_mobile_money"][0]) == [("552", D(500), D(0), None), ("411", D(0), D(500), env["customer"])]
    # All of it is an advance: the customer account nets to zero, and in this test 585 is both the
    # cheque holding account (400 debit) and the advance account (3900 credit).
    assert _per_account(env, [document_id]) == {"571": D(1000), "521": D(2000), "552": D(500), "585": D(-3500)}


def test_a_mixed_receipt_partly_allocated_advances_only_the_rest(env):
    from modules.finance.api.service import InvoiceService

    _rules(env)
    _enable(env)
    invoices = InvoiceService(env["db"])
    invoice = invoices.create_draft_invoice(tenant_id=env["tenant"], partner_id=env["customer"], amount=1500, currency="XOF")
    invoices.issue_invoice(tenant_id=env["tenant"], actor_id=env["actor"], invoice_id=invoice.id, correlation_id="c")
    result = DocumentService(env["db"]).create_and_post(
        tenant_id=env["tenant"], actor_id=env["actor"], direction="in", partner_id=env["customer"], doc_date=DAY, currency="XOF",
        payments=[
            {"method": "cash", "amount": 1000, "account_id": env["cash"]},
            {"method": "transfer", "amount": 2000, "account_id": env["real_bank"]},
        ],
        allocations=[{"invoice_id": invoice.id, "amount": 1500}], reason="advance", can_add_prior_year=True, correlation_id="c",
    )
    assert isinstance(result, Ok), result
    document_id = result.value["id"]
    assert _deliver(env, _envelope(env, "treasury.receipt.posted", "receipt_id", document_id)) is True
    assert _per_account(env, [document_id]) == {"571": D(1000), "521": D(2000), "411": D(-1500), "585": D(-1500)}


def test_cancelling_a_mixed_receipt_nets_every_account_to_zero(env):
    _rules(env)
    _enable(env)
    document_id = _mixed_receipt(env)
    assert _deliver(env, _envelope(env, "treasury.receipt.posted", "receipt_id", document_id)) is True
    assert isinstance(_cancel(env, document_id, "in"), Ok)
    assert _deliver(env, _envelope(env, "treasury.receipt.cancelled", "receipt_id", document_id)) is True
    assert _per_account(env, [document_id]) == {}


def test_a_refusal_on_one_payment_of_a_receipt_posts_none_of_it(env):
    _rules(env)
    _enable(env)
    document_id = _document(env, "in", payments=[
        {"method": "transfer", "amount": 1000, "account_id": env["real_bank"]},
        {"method": "cash", "amount": 200, "account_id": env["nocode"]},
    ])
    assert _deliver(env, _envelope(env, "treasury.receipt.posted", "receipt_id", document_id)) is False
    assert _failures(env, document_id) == [("receipt_payment", "LEDGER_ACCOUNT_MISSING", "open")]
    assert _entries(env, document_id, advance=True) == []


def test_a_fractional_amount_never_reaches_the_ledger_because_treasury_refuses_it_first(env):
    _rules(env)
    _enable(env)
    refused = DocumentService(env["db"]).create_and_post(
        tenant_id=env["tenant"], actor_id=env["actor"], direction="in", partner_id=env["customer"], doc_date=DAY, currency="XOF",
        payments=[{"method": "cash", "amount": D("1000.50"), "account_id": env["cash"]}],
        reason="advance", with_details=False, correlation_id="c",
    )
    assert isinstance(refused, Err) and refused.code == "AMOUNT_NOT_WHOLE"
    published = env["db"].execute(
        "SELECT count(*) FROM events.outbox WHERE event_type = 'treasury.receipt.posted' AND tenant_id = %s", (env["tenant"],)
    ).fetchone()[0]
    assert published == 0


def test_a_foreign_currency_never_reaches_the_ledger_because_treasury_refuses_it_first(env):
    _rules(env)
    _enable(env)
    euro = AccountService(env["db"]).create_account(
        tenant_id=env["tenant"], actor_id=env["actor"], kind="cash",
        fields={"name": "Caisse EUR", "currency": "EUR", "opening_balance": 0, "ledger_account_code": "571"},
    )
    assert isinstance(euro, Err) and euro.code == "TREASURY_CURRENCY_NOT_XOF"
    refused = DocumentService(env["db"]).create_and_post(
        tenant_id=env["tenant"], actor_id=env["actor"], direction="in", partner_id=env["customer"], doc_date=DAY, currency="EUR",
        payments=[{"method": "cash", "amount": 100, "account_id": env["cash"]}],
        reason="advance", with_details=False, correlation_id="c",
    )
    assert isinstance(refused, Err) and refused.code == "TREASURY_CURRENCY_NOT_XOF"


def _bounce_with_fee(env, instrument_id, fee=2500, account=None):
    bounced = InstrumentService(env["db"]).mark_unpaid(
        tenant_id=env["tenant"], actor_id=env["actor"], instrument_id=instrument_id, correlation_id="c",
        rejection_fee=D(fee), rejection_fee_account_id=account or env["real_bank"],
    )
    assert isinstance(bounced, Ok), bounced


def _rejected_cheque_with_fee(env, account=None):
    document_id = _document(env, "in", payments=[_cheque_payment()])
    instrument_id = _instrument_of(env, document_id)
    assert _deliver(env, _envelope(env, "treasury.receipt.posted", "receipt_id", document_id)) is True
    _bounce_with_fee(env, instrument_id, account=account)
    return instrument_id


def test_a_rejection_fee_is_an_expense_against_the_account_the_bank_charged(env):
    _rules(env)
    _rule(env, "instrument_rejection_fee", "*", debit="585", journal="BNQ")
    _enable(env)
    instrument_id = _rejected_cheque_with_fee(env)
    envelope = _envelope(env, "treasury.instrument.unpaid", "instrument_id", instrument_id)
    assert _deliver(env, envelope) is True
    assert _deliver(env, envelope) is True
    entries = {kind: entry_id for entry_id, kind, *_ in _entries(env, instrument_id)}
    assert set(entries) == {"instrument_unpaid", "instrument_rejection_fee"}
    assert _lines(env, entries["instrument_rejection_fee"]) == [("585", D(2500), D(0), None), ("521", D(0), D(2500), None)]


def test_a_rejection_fee_entry_reversed_in_the_ledger_is_not_posted_again(env):
    from modules.finance.api.ledger_posting_service import SYSTEM_ACTOR, LedgerPostingService

    _rules(env)
    _rule(env, "instrument_rejection_fee", "*", debit="585", journal="BNQ")
    _enable(env)
    instrument_id = _rejected_cheque_with_fee(env)
    envelope = _envelope(env, "treasury.instrument.unpaid", "instrument_id", instrument_id)
    assert _deliver(env, envelope) is True
    fee_entry = next(entry_id for entry_id, kind, *_ in _entries(env, instrument_id) if kind == "instrument_rejection_fee")
    reversal = LedgerPostingService(env["db"]).reverse_entry(
        tenant_id=env["tenant"], actor_id=SYSTEM_ACTOR, entry_id=fee_entry, entry_date=DAY, correlation_id="c"
    )
    assert isinstance(reversal, Ok), reversal
    assert _deliver(env, _envelope(env, "treasury.instrument.unpaid", "instrument_id", instrument_id)) is True
    kinds = sorted(kind for _, kind, *_ in _entries(env, instrument_id))
    assert kinds == ["instrument_rejection_fee", "instrument_rejection_fee_reversal", "instrument_unpaid"]
    assert "521" not in _per_account(env, [instrument_id])


def test_a_rejection_fee_without_its_rule_refuses_the_whole_posting_and_the_retry_completes_it(env):
    _rules(env)
    _enable(env)
    instrument_id = _rejected_cheque_with_fee(env)
    assert _deliver(env, _envelope(env, "treasury.instrument.unpaid", "instrument_id", instrument_id)) is False
    assert _failures(env, instrument_id) == [("instrument_unpaid", "POSTING_RULE_MISSING", "open")]
    assert _entries(env, instrument_id) == []

    _rule(env, "instrument_rejection_fee", "*", debit="585", journal="BNQ")
    retried = retry_failure(env["db"], tenant_id=env["tenant"], actor_id=env["actor"], failure_id=_failure_id(env, instrument_id))
    assert isinstance(retried, Ok), retried
    assert sorted(kind for _, kind, *_ in _entries(env, instrument_id)) == ["instrument_rejection_fee", "instrument_unpaid"]


def test_a_rejection_fee_charged_to_an_account_without_a_ledger_code_is_refused(env):
    _rules(env)
    _rule(env, "instrument_rejection_fee", "*", debit="585", journal="BNQ")
    _enable(env)
    instrument_id = _rejected_cheque_with_fee(env, account=env["nocode"])
    assert _deliver(env, _envelope(env, "treasury.instrument.unpaid", "instrument_id", instrument_id)) is False
    assert _failures(env, instrument_id) == [("instrument_unpaid", "LEDGER_ACCOUNT_MISSING", "open")]


def test_a_rejection_fee_posts_nothing_while_the_switch_is_off(env):
    document_id = _document(env, "in", payments=[_cheque_payment()])
    instrument_id = _instrument_of(env, document_id)
    _bounce_with_fee(env, instrument_id)
    assert _deliver(env, _envelope(env, "treasury.instrument.unpaid", "instrument_id", instrument_id)) is True
    assert _entries(env, instrument_id) == []
    assert _failures(env, instrument_id) == []


def _retry_client(env, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from core.tenancy import TenantContext, require_session
    from modules.finance.api import ledger_router

    wrapped = NoCommitConnection(env["db"])
    monkeypatch.setattr(ledger_router, "get_connection", lambda: wrapped)
    monkeypatch.setattr("core.tenancy.get_connection", lambda: wrapped)
    app = FastAPI()
    app.include_router(ledger_router.router)
    app.dependency_overrides[require_session] = lambda: TenantContext(
        tenant_id=env["tenant"], user_id=env["actor"], session_token="t"
    )
    env["db"].execute(
        "INSERT INTO core.user_permissions (user_id, permission) VALUES (%s, 'finance.manage_entries')", (env["actor"],)
    )
    return TestClient(app)


def _set_switch(env, value):
    SettingsService(env["db"]).set_setting(
        tenant_id=env["tenant"], actor_id=env["actor"], key="ledger_posting_enabled", value=value
    )


def test_an_open_treasury_failure_cannot_post_while_the_switch_is_off_and_posts_once_it_is_back_on(env, monkeypatch):
    _enable(env)
    document_id = _document(env, "in", amount=800)
    assert _deliver(env, _envelope(env, "treasury.receipt.posted", "receipt_id", document_id)) is False
    _rules(env)  # the cause of the refusal is fixed, so only the switch can stop the posting
    failure_id = _failure_id(env, document_id)
    client = _retry_client(env, monkeypatch)

    _set_switch(env, False)
    refused = client.post(f"/finance/posting-failures/{failure_id}/retry")

    assert refused.status_code == 409
    detail = refused.json()["detail"]
    assert detail["code"] == "LEDGER_POSTING_DISABLED"
    assert "activez-la" in detail["message_fr"]
    assert _entries(env, document_id, advance=True) == []
    assert _failures(env, document_id) == [("receipt_payment", "POSTING_RULE_MISSING", "open")]

    _set_switch(env, True)
    posted = client.post(f"/finance/posting-failures/{failure_id}/retry")

    assert posted.status_code == 200, posted.text
    assert [kind for _, kind, *_ in _entries(env, document_id)] == ["receipt_payment_cash"]
    assert _failures(env, document_id) == [("receipt_payment", "POSTING_RULE_MISSING", "resolved")]


def test_the_switch_does_not_touch_the_retry_of_an_invoice_failure(env):
    invoice_id = str(ULID())

    def envelope(event_type):
        return {
            "event_id": str(ULID()), "event_type": event_type, "event_version": "1.0",
            "occurred_at": "2030-03-04T10:00:00+00:00", "producer": "finance", "tenant_id": env["tenant"],
            "correlation_id": str(ULID()), "causation_id": None,
            "payload": {"invoice_id": invoice_id, "partner_id": env["customer"], "amount": 1000.0, "currency": "XOF"},
        }

    assert _deliver(env, envelope("finance.invoice.paid")) is False
    assert _deliver(env, envelope("finance.invoice.issued")) is True
    assert SettingsService(env["db"]).get_settings(tenant_id=env["tenant"])["ledger_posting_enabled"] is False

    result = retry_failure(env["db"], tenant_id=env["tenant"], actor_id=env["actor"], failure_id=_failure_id(env, invoice_id))

    assert isinstance(result, Ok), result
    assert _failures(env, invoice_id) == [("invoice_paid", "INVOICE_NOT_POSTED", "resolved")]
