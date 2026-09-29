"""Payroll events into the ledger, through the real event registry.

`core.events.consumers._process` commits after each handler, so it runs on a NoCommitConnection:
commits and rollbacks are no-ops and the fixture still rolls everything back. Payroll's
PayrollPostingService is replaced by a fake returning the contract's dicts."""
from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from ulid import ULID

from core.domain.result import Err, Ok
from core.events.consumers import _process
from modules.finance.api import payroll_ledger_service
from modules.finance.api.ledger_event_postings import retry_failure
from modules.finance.api.period_service import PeriodService
from modules.finance.events import ledger_consumers  # noqa: F401  (registers the handlers)
from modules.finance.testing_support import NoCommitConnection

D = Decimal
JANUARY = datetime.date(2030, 1, 1)

# One employee: gross 320 000 = INPS 11 040 + ITS 25 000 + advance 10 000 + net 273 960.
POSTING_LINES = [
    {"source_kind": "earning", "code": "BASE", "amount": D(300000), "employee_id": "e1"},
    {"source_kind": "earning", "code": "OT_DAY", "amount": D(20000), "employee_id": "e1"},
    {"source_kind": "employee_contribution", "code": "INPS_EE", "amount": D(11040), "employee_id": "e1"},
    {"source_kind": "tax", "code": "ITS", "amount": D(25000), "employee_id": "e1"},
    {"source_kind": "deduction", "code": "ADVANCE", "amount": D(10000), "employee_id": "e1"},
    {"source_kind": "net", "code": "NET", "amount": D(273960), "employee_id": "e1"},
    {"source_kind": "employer_contribution", "code": "INPS_ER", "amount": D(60000), "employee_id": "e1"},
    {"source_kind": "employer_charge", "code": "TL", "amount": D(3200), "employee_id": "e1"},
]
PAYMENT_LINES = [
    {"method": "bank", "amount": D(200000), "employee_id": "e1"},
    {"method": "cash", "amount": D(73960), "employee_id": "e1"},
]


class FakePayroll:
    def __init__(self) -> None:
        self.posting_calls = 0

    def posting_lines(self, *, tenant_id: str, run_id: str) -> list[dict]:
        self.posting_calls += 1
        return POSTING_LINES

    def payment_lines(self, *, tenant_id: str, run_id: str) -> list[dict]:
        return PAYMENT_LINES


@pytest.fixture
def payroll(ledger, monkeypatch) -> FakePayroll:
    fake = FakePayroll()
    monkeypatch.setattr(payroll_ledger_service, "PAYROLL_API_FACTORY", lambda connection: fake)
    return fake


@pytest.fixture
def run_id() -> str:
    return str(ULID())


def _envelope(ledger, event_type: str, run_id: str, *, occurred_at: str = "2030-02-05T09:00:00+00:00") -> dict:
    return {
        "event_id": str(ULID()),
        "event_type": event_type,
        "event_version": "1.0",
        "occurred_at": occurred_at,
        "producer": "payroll",
        "tenant_id": ledger["tenant"],
        "correlation_id": str(ULID()),
        "causation_id": None,
        "payload": {"run_id": run_id, "period": "2030-01-01", "run_type": "regular"},
    }


def _deliver(ledger, envelope: dict) -> bool:
    return _process(NoCommitConnection(ledger["db"]), envelope)


def _entries(ledger, run_id: str) -> list[tuple]:
    return ledger["db"].execute(
        """
        SELECT source_kind, journal_code, status, entry_date FROM finance.journal_entries
        WHERE tenant_id = %s AND source_module = 'payroll' AND source_id = %s
        ORDER BY source_kind
        """,
        (ledger["tenant"], run_id),
    ).fetchall()


def _lines(ledger, run_id: str, source_kind: str) -> dict[str, tuple[Decimal, Decimal]]:
    rows = ledger["db"].execute(
        """
        SELECT l.account_code, l.debit, l.credit FROM finance.journal_lines l
        JOIN finance.journal_entries e ON e.id = l.entry_id
        WHERE e.tenant_id = %s AND e.source_id = %s AND e.source_kind = %s
        """,
        (ledger["tenant"], run_id, source_kind),
    ).fetchall()
    return {code: (debit, credit) for code, debit, credit in rows}


def _net(ledger, run_id: str, account_code: str) -> Decimal:
    return ledger["db"].execute(
        """
        SELECT COALESCE(SUM(l.debit - l.credit), 0) FROM finance.journal_lines l
        JOIN finance.journal_entries e ON e.id = l.entry_id
        WHERE e.tenant_id = %s AND e.source_id = %s AND l.account_code = %s
        """,
        (ledger["tenant"], run_id, account_code),
    ).fetchone()[0]


def _failures(ledger, run_id: str) -> list[tuple]:
    return ledger["db"].execute(
        """
        SELECT id, source_kind, error_code, status FROM finance.posting_failures
        WHERE tenant_id = %s AND source_id = %s ORDER BY source_kind
        """,
        (ledger["tenant"], run_id),
    ).fetchall()


def test_an_approved_run_posts_one_balanced_paie_entry(ledger, payroll, run_id):
    assert _deliver(ledger, _envelope(ledger, "payroll.run.approved", run_id)) is True
    assert _entries(ledger, run_id) == [("payroll_run", "PAIE", "posted", datetime.date(2030, 1, 31))]
    assert _lines(ledger, run_id, "payroll_run") == {
        "641": (D(3200), D(0)),
        "661": (D(320000), D(0)),
        "664": (D(60000), D(0)),
        "421": (D(0), D(10000)),
        "422": (D(0), D(273960)),
        "431": (D(0), D(71040)),
        "442": (D(0), D(3200)),
        "447": (D(0), D(25000)),
    }
    ledger["db"].execute("SET CONSTRAINTS ALL IMMEDIATE")


def test_the_same_approved_event_delivered_twice_posts_once(ledger, payroll, run_id):
    envelope = _envelope(ledger, "payroll.run.approved", run_id)
    assert _deliver(ledger, envelope) is True
    assert _deliver(ledger, envelope) is True
    assert len(_entries(ledger, run_id)) == 1
    assert payroll.posting_calls == 1  # the second delivery was skipped on its event_id


def test_a_second_approval_event_for_the_same_run_does_not_post_again(ledger, payroll, run_id):
    assert _deliver(ledger, _envelope(ledger, "payroll.run.approved", run_id)) is True
    assert _deliver(ledger, _envelope(ledger, "payroll.run.approved", run_id)) is True
    assert len(_entries(ledger, run_id)) == 1


def test_a_paid_run_clears_net_pay_per_payment_method(ledger, payroll, run_id):
    _deliver(ledger, _envelope(ledger, "payroll.run.approved", run_id))
    assert _deliver(ledger, _envelope(ledger, "payroll.run.paid", run_id)) is True
    assert _entries(ledger, run_id) == [
        ("payroll_payment_bank", "BNQ", "posted", datetime.date(2030, 2, 5)),
        ("payroll_payment_cash", "CAI", "posted", datetime.date(2030, 2, 5)),
        ("payroll_run", "PAIE", "posted", datetime.date(2030, 1, 31)),
    ]
    assert _net(ledger, run_id, "422") == D(0)
    assert _net(ledger, run_id, "521") == D(-200000)
    assert _net(ledger, run_id, "571") == D(-73960)


def test_the_same_paid_event_delivered_twice_posts_once(ledger, payroll, run_id):
    _deliver(ledger, _envelope(ledger, "payroll.run.approved", run_id))
    envelope = _envelope(ledger, "payroll.run.paid", run_id)
    assert _deliver(ledger, envelope) is True
    assert _deliver(ledger, envelope) is True
    assert _deliver(ledger, _envelope(ledger, "payroll.run.paid", run_id)) is True  # new event id, same run
    assert len(_entries(ledger, run_id)) == 3


def test_a_reversed_run_mirrors_every_entry_once(ledger, payroll, run_id):
    _deliver(ledger, _envelope(ledger, "payroll.run.approved", run_id))
    _deliver(ledger, _envelope(ledger, "payroll.run.paid", run_id))
    envelope = _envelope(ledger, "payroll.run.reversed", run_id, occurred_at="2030-02-10T08:00:00+00:00")
    assert _deliver(ledger, envelope) is True
    assert _deliver(ledger, envelope) is True
    assert _deliver(ledger, _envelope(ledger, "payroll.run.reversed", run_id)) is True  # new event id: nothing left to reverse
    statuses = {kind: status for kind, _, status, _ in _entries(ledger, run_id)}
    assert statuses == {
        "payroll_run": "reversed",
        "payroll_payment_bank": "reversed",
        "payroll_payment_cash": "reversed",
        "payroll_run_reversal": "posted",
        "payroll_payment_bank_reversal": "posted",
        "payroll_payment_cash_reversal": "posted",
    }
    for account in ("422", "431", "447", "521", "571", "661"):
        assert _net(ledger, run_id, account) == D(0), account
    ledger["db"].execute("SET CONSTRAINTS ALL IMMEDIATE")


def test_a_closed_period_dead_letters_then_retry_posts_once(ledger, payroll, run_id):
    periods = PeriodService(ledger["db"])
    periods.close_period(tenant_id=ledger["tenant"], actor_id=ledger["actor"], period=JANUARY)
    envelope = _envelope(ledger, "payroll.run.approved", run_id)
    assert _deliver(ledger, envelope) is False  # nacked: the message goes to the dead-letter queue
    assert _entries(ledger, run_id) == []
    [(failure_id, kind, code, status)] = _failures(ledger, run_id)
    assert (kind, code, status) == ("payroll_run", "PERIOD_CLOSED", "open")

    periods.reopen_period(tenant_id=ledger["tenant"], actor_id=ledger["actor"], period=JANUARY)
    retried = retry_failure(ledger["db"], tenant_id=ledger["tenant"], actor_id=ledger["actor"], failure_id=failure_id)
    assert isinstance(retried, Ok), retried
    assert len(_entries(ledger, run_id)) == 1
    assert _failures(ledger, run_id)[0][3] == "resolved"

    # The dead-lettered message replayed later: still one entry, the failure stays resolved.
    assert _deliver(ledger, envelope) is True
    assert len(_entries(ledger, run_id)) == 1
    assert _failures(ledger, run_id)[0][3] == "resolved"
    again = retry_failure(ledger["db"], tenant_id=ledger["tenant"], actor_id=ledger["actor"], failure_id=failure_id)
    assert isinstance(again, Err) and again.code == "INVALID_TRANSITION"


def test_a_payment_before_its_run_is_refused_until_the_run_posts(ledger, payroll, run_id):
    assert _deliver(ledger, _envelope(ledger, "payroll.run.paid", run_id)) is False
    [(failure_id, kind, code, _)] = _failures(ledger, run_id)
    assert (kind, code) == ("payroll_payment", "RUN_NOT_POSTED")
    assert _entries(ledger, run_id) == []
    assert _deliver(ledger, _envelope(ledger, "payroll.run.approved", run_id)) is True
    retried = retry_failure(ledger["db"], tenant_id=ledger["tenant"], actor_id=ledger["actor"], failure_id=failure_id)
    assert isinstance(retried, Ok), retried
    assert _net(ledger, run_id, "422") == D(0)


def test_reversing_a_run_whose_posting_failed_cancels_the_failure(ledger, payroll, run_id):
    PeriodService(ledger["db"]).close_period(tenant_id=ledger["tenant"], actor_id=ledger["actor"], period=JANUARY)
    assert _deliver(ledger, _envelope(ledger, "payroll.run.approved", run_id)) is False
    assert _deliver(ledger, _envelope(ledger, "payroll.run.reversed", run_id)) is True
    [(failure_id, kind, _, status)] = _failures(ledger, run_id)
    assert (kind, status) == ("payroll_run", "cancelled")
    assert _entries(ledger, run_id) == []
    retried = retry_failure(ledger["db"], tenant_id=ledger["tenant"], actor_id=ledger["actor"], failure_id=failure_id)
    assert isinstance(retried, Err) and retried.code == "INVALID_TRANSITION"


def test_a_missing_posting_rule_is_refused_and_recorded(ledger, payroll, run_id):
    ledger["db"].execute(
        "DELETE FROM finance.posting_rules WHERE tenant_id = %s AND source = 'payroll' AND source_kind = 'tax'",
        (ledger["tenant"],),
    )
    assert _deliver(ledger, _envelope(ledger, "payroll.run.approved", run_id)) is False
    [(_, kind, code, status)] = _failures(ledger, run_id)
    assert (kind, code, status) == ("payroll_run", "POSTING_RULE_MISSING", "open")


def test_a_rule_pointing_at_a_heading_account_is_refused_and_recorded(ledger, payroll, run_id):
    ledger["db"].execute(
        "UPDATE finance.accounts SET is_postable = FALSE WHERE tenant_id = %s AND code = '661'", (ledger["tenant"],)
    )
    assert _deliver(ledger, _envelope(ledger, "payroll.run.approved", run_id)) is False
    [(_, _, code, _)] = _failures(ledger, run_id)
    assert code == "ACCOUNT_NOT_POSTABLE"


def test_a_failure_keeps_both_languages_and_its_envelope(ledger, payroll, run_id):
    PeriodService(ledger["db"]).close_period(tenant_id=ledger["tenant"], actor_id=ledger["actor"], period=JANUARY)
    envelope = _envelope(ledger, "payroll.run.approved", run_id)
    _deliver(ledger, envelope)
    message, message_fr, stored = ledger["db"].execute(
        "SELECT error_message, error_message_fr, envelope FROM finance.posting_failures WHERE tenant_id = %s AND source_id = %s",
        (ledger["tenant"], run_id),
    ).fetchone()
    assert message and message_fr
    assert stored["event_id"] == envelope["event_id"]
