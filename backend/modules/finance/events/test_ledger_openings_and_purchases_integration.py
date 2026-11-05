"""The ledger catches up with reality once switched on: treasury account balances come in as opening
entries, and validated purchase invoices are booked against the supplier, so 401, 521 and 571 match the
treasury and the invoices (found missing when posting was first run end to end)."""
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
from modules.procurement.api.invoice_service import PurchaseInvoiceService
from modules.treasury.api.service import AccountService, SettingsService

D = Decimal
TODAY = datetime.date.today()


@pytest.fixture
def env(ledger):
    db, tenant, actor = ledger["db"], ledger["tenant"], ledger["actor"]
    if TODAY.year != ledger["year"]:
        # The opening entries are dated the day posting is switched on.
        assert isinstance(PeriodService(db).open_fiscal_year(tenant_id=tenant, actor_id=actor, year=TODAY.year), Ok)
    supplier = str(ULID())
    db.execute("INSERT INTO core.partners (id, tenant_id, name, kind, status) VALUES (%s, %s, 'Fournisseur', 'supplier', 'active')",
               (supplier, tenant))
    return {**ledger, "supplier": supplier}


def _account(env, kind, name, balance, code):
    fields = {"name": name, "currency": "XOF", "opening_balance": balance}
    if kind == "mobile_money":
        fields.update(operator="orange_money", phone="7")
    if code:
        fields["ledger_account_code"] = code
    return AccountService(env["db"]).create_account(tenant_id=env["tenant"], actor_id=env["actor"], kind=kind, fields=fields)


def _opening_rule(env, code="*"):
    result = PostingRuleService(env["db"]).create_rule(
        tenant_id=env["tenant"], actor_id=env["actor"], source="treasury", source_kind="account_opening", code=code,
        credit_account_code="471", journal_code="OD",
    )
    assert isinstance(result, Ok), result


def _switch_on(env):
    return SettingsService(env["db"]).set_setting(tenant_id=env["tenant"], actor_id=env["actor"], key="ledger_posting_enabled", value=True)


def _switch(env):
    return SettingsService(env["db"]).get_settings(tenant_id=env["tenant"])["ledger_posting_enabled"]


def _openings(env):
    return env["db"].execute(
        """
        SELECT e.source_id, e.journal_code, l.account_code, l.debit, l.credit FROM finance.journal_entries e
        JOIN finance.journal_lines l ON l.entry_id = e.id
        WHERE e.tenant_id = %s AND e.source_kind = 'account_opening' ORDER BY e.number, l.line_no
        """,
        (env["tenant"],),
    ).fetchall()


def test_switching_on_brings_every_account_balance_into_the_ledger_once(env):
    bank = _account(env, "cash", "Coffre", 250000, "521").value["id"]
    cash = _account(env, "cash", "Caisse", 40000, "571").value["id"]
    _account(env, "cash", "Caisse vide", 0, "571")  # a zero balance needs no entry
    _opening_rule(env)

    assert isinstance(_switch_on(env), Ok) and _switch(env) is True

    assert _openings(env) == [
        (bank, "OD", "521", D(250000), D(0)), (bank, "OD", "471", D(0), D(250000)),
        (cash, "OD", "571", D(40000), D(0)), (cash, "OD", "471", D(0), D(40000)),
    ]
    SettingsService(env["db"]).set_setting(tenant_id=env["tenant"], actor_id=env["actor"], key="ledger_posting_enabled", value=False)
    assert isinstance(_switch_on(env), Ok)
    assert len(_openings(env)) == 4  # switching on again opens nothing twice


def test_switching_on_without_the_opening_rule_refuses_and_posts_nothing(env):
    _account(env, "cash", "Coffre", 250000, "521")
    _account(env, "mobile_money", "Orange", 10000, "552")
    _opening_rule(env, code="cash")  # the cash account could be opened, the mobile-money one cannot

    refused = _switch_on(env)

    assert isinstance(refused, Err) and refused.code == "LEDGER_OPENING_REFUSED"
    assert "Orange" in refused.message and "reste désactivée" in refused.message_fr
    assert _switch(env) is False
    assert _openings(env) == []  # not half-opened: the cash account's entry went with the refusal


def test_an_account_without_a_ledger_code_keeps_posting_off(env):
    _account(env, "cash", "Sans code", 5000, None)
    _opening_rule(env)
    refused = _switch_on(env)
    assert isinstance(refused, Err) and refused.code == "LEDGER_OPENING_REFUSED" and "Sans code" in refused.message
    assert _switch(env) is False


def test_an_account_created_while_posting_is_on_is_opened_at_once_or_refused(env):
    _opening_rule(env)
    assert isinstance(_switch_on(env), Ok)

    created = _account(env, "cash", "Nouvelle caisse", 15000, "571")
    refused = _account(env, "cash", "Sans code", 15000, None)

    assert isinstance(created, Ok)
    assert _openings(env) == [(created.value["id"], "OD", "571", D(15000), D(0)), (created.value["id"], "OD", "471", D(0), D(15000))]
    assert isinstance(refused, Err) and refused.code == "LEDGER_OPENING_REFUSED"


def test_the_opening_balance_is_locked_once_it_is_in_the_ledger(env):
    _opening_rule(env)
    assert isinstance(_switch_on(env), Ok)
    account_id = _account(env, "cash", "Caisse", 15000, "571").value["id"]
    changed = AccountService(env["db"]).update_account(
        tenant_id=env["tenant"], actor_id=env["actor"], account_id=account_id, changes={"opening_balance": 20000})
    assert isinstance(changed, Err) and changed.code == "ACCOUNT_LOCKED"


def test_a_collection_rule_for_an_account_kind_may_name_only_its_journal(env):
    rules = PostingRuleService(env["db"])
    journal_only = rules.create_rule(tenant_id=env["tenant"], actor_id=env["actor"], source="treasury",
                                     source_kind="instrument_collected", code="cash", journal_code="CAI")
    no_account = rules.create_rule(tenant_id=env["tenant"], actor_id=env["actor"], source="treasury",
                                   source_kind="receipt_payment", code="cash", journal_code="CAI")
    assert isinstance(journal_only, Ok), journal_only
    assert isinstance(no_account, Err) and no_account.code == "INVALID_POSTING_RULE"


# Purchase invoices --------------------------------------------------------------------------------


def _purchase_invoice(env, amount=80000):
    service = PurchaseInvoiceService(env["db"])
    draft = service.create_draft(tenant_id=env["tenant"], actor_id=env["actor"], partner_id=env["supplier"],
                                 supplier_invoice_number=f"F-{ULID()}", invoice_date=datetime.date(2030, 3, 4), amount=D(amount))
    assert isinstance(draft, Ok), draft
    validated = service.validate(tenant_id=env["tenant"], actor_id=env["actor"], invoice_id=draft.value["id"], correlation_id="c")
    assert isinstance(validated, Ok), validated
    return draft.value["id"]


def _envelope(env, event_type, invoice_id):
    envelope = env["db"].execute(
        "SELECT payload FROM events.outbox WHERE event_type = %s AND payload -> 'payload' ->> 'invoice_id' = %s",
        (event_type, invoice_id),
    ).fetchone()[0]
    envelope["occurred_at"] = "2030-03-05T10:00:00+00:00"
    return envelope


def _deliver(env, envelope) -> bool:
    return _process(NoCommitConnection(env["db"]), envelope)


def _purchase_entries(env, invoice_id):
    rows = env["db"].execute(
        "SELECT id, source_kind, journal_code, status FROM finance.journal_entries "
        "WHERE tenant_id = %s AND source_module = 'procurement' AND source_id = %s ORDER BY source_kind",
        (env["tenant"], invoice_id),
    ).fetchall()
    return [(kind, journal, status, env["db"].execute(
        "SELECT account_code, debit, credit, partner_id FROM finance.journal_lines WHERE entry_id = %s ORDER BY line_no", (entry_id,)
    ).fetchall()) for entry_id, kind, journal, status in rows]


def test_a_validated_purchase_invoice_credits_the_supplier_once(env):
    invoice_id = _purchase_invoice(env)
    envelope = _envelope(env, "procurement.purchase_invoice.validated", invoice_id)

    assert _deliver(env, envelope) is True
    assert _deliver(env, {**envelope, "event_id": str(ULID())}) is True  # a second delivery finds the first entry

    assert _purchase_entries(env, invoice_id) == [
        ("purchase_invoice_validated", "ACH", "posted", [("601", D(80000), D(0), None), ("401", D(0), D(80000), env["supplier"])]),
    ]


def test_cancelling_a_validated_purchase_invoice_reverses_its_entry(env):
    invoice_id = _purchase_invoice(env)
    assert _deliver(env, _envelope(env, "procurement.purchase_invoice.validated", invoice_id)) is True
    cancelled = PurchaseInvoiceService(env["db"]).cancel(tenant_id=env["tenant"], actor_id=env["actor"], invoice_id=invoice_id)
    assert isinstance(cancelled, Ok), cancelled

    assert _deliver(env, _envelope(env, "procurement.purchase_invoice.cancelled", invoice_id)) is True

    kinds = [(kind, status) for kind, _, status, _ in _purchase_entries(env, invoice_id)]
    assert kinds == [("purchase_invoice_validated", "reversed"), ("purchase_invoice_validated_reversal", "posted")]


def test_cancelling_a_draft_publishes_nothing_for_the_ledger(env):
    service = PurchaseInvoiceService(env["db"])
    draft = service.create_draft(tenant_id=env["tenant"], actor_id=env["actor"], partner_id=env["supplier"],
                                 supplier_invoice_number="F-DRAFT", invoice_date=datetime.date(2030, 3, 4), amount=D(100))
    assert isinstance(service.cancel(tenant_id=env["tenant"], actor_id=env["actor"], invoice_id=draft.value["id"]), Ok)
    assert env["db"].execute(
        "SELECT COUNT(*) FROM events.outbox WHERE event_type = 'procurement.purchase_invoice.cancelled' AND payload -> 'payload' ->> 'invoice_id' = %s",
        (draft.value["id"],),
    ).fetchone()[0] == 0


def test_a_refused_purchase_posting_is_recorded_and_its_retry_skips_an_invoice_cancelled_since(env):
    env["db"].execute("DELETE FROM finance.posting_rules WHERE tenant_id = %s AND source = 'purchase_invoice'", (env["tenant"],))
    invoice_id = _purchase_invoice(env)
    assert _deliver(env, _envelope(env, "procurement.purchase_invoice.validated", invoice_id)) is False
    failure = env["db"].execute(
        "SELECT id, error_code FROM finance.posting_failures WHERE tenant_id = %s AND source_id = %s AND status = 'open'",
        (env["tenant"], invoice_id),
    ).fetchone()
    assert failure[1] == "POSTING_RULE_MISSING"
    PurchaseInvoiceService(env["db"]).cancel(tenant_id=env["tenant"], actor_id=env["actor"], invoice_id=invoice_id)
    assert _deliver(env, _envelope(env, "procurement.purchase_invoice.cancelled", invoice_id)) is True

    retried = retry_failure(env["db"], tenant_id=env["tenant"], actor_id=env["actor"], failure_id=failure[0])

    assert isinstance(retried, Ok) and retried.value == []
    assert _purchase_entries(env, invoice_id) == []
