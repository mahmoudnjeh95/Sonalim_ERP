"""The single posting path: checks, numbering, the posted event, immutability, reversal."""
from __future__ import annotations

import datetime
from decimal import Decimal

import psycopg
import pytest
from ulid import ULID

from core.domain.result import Err, Ok
from modules.finance.api.ledger_posting_service import LedgerPostingService
from modules.finance.api.period_service import PeriodService
from modules.finance.domain.ledger import EntryLine, SourceRef

D = Decimal
DAY = datetime.date(2030, 1, 20)
CAPITAL = [EntryLine("521", debit=D(1000000)), EntryLine("101", credit=D(1000000))]


def _post(ledger, *, lines=None, day=DAY, source=None, journal="OD"):
    return LedgerPostingService(ledger["db"]).post_entry(
        tenant_id=ledger["tenant"],
        actor_id=ledger["actor"],
        journal_code=journal,
        entry_date=day,
        label="Apport en capital",
        lines=lines or CAPITAL,
        correlation_id=str(ULID()),
        source=source,
    )


def _count(ledger) -> int:
    return ledger["db"].execute(
        "SELECT count(*) FROM finance.journal_entries WHERE tenant_id = %s", (ledger["tenant"],)
    ).fetchone()[0]


def test_a_balanced_entry_is_posted_numbered_announced_and_audited(ledger):
    result = _post(ledger)
    assert isinstance(result, Ok), result
    entry = result.value
    assert entry["status"] == "posted" and entry["number"] == "OD-2030-000001"
    assert entry["period"] == datetime.date(2030, 1, 1)
    assert entry["total_debit"] == entry["total_credit"] == D(1000000)
    db = ledger["db"]
    envelope = db.execute(
        "SELECT payload FROM events.outbox WHERE event_type = 'finance.journal_entry.posted' AND tenant_id = %s",
        (ledger["tenant"],),
    ).fetchone()[0]
    assert envelope["payload"] == {"entry_id": entry["id"], "journal_code": "OD", "source_module": None, "source_id": None}
    audited = db.execute(
        "SELECT count(*) FROM core.audit_log WHERE entity_id = %s AND action = 'journal_entry.posted'", (entry["id"],)
    ).fetchone()[0]
    assert audited == 1
    db.execute("SET CONSTRAINTS ALL IMMEDIATE")  # the deferred balance trigger accepts it


def test_posting_into_a_closed_period_is_refused_and_writes_nothing(ledger):
    PeriodService(ledger["db"]).close_period(tenant_id=ledger["tenant"], actor_id=ledger["actor"], period=datetime.date(2030, 1, 1))
    result = _post(ledger)
    assert isinstance(result, Err) and result.code == "PERIOD_CLOSED"
    assert _count(ledger) == 0


def test_a_date_outside_every_fiscal_year_is_period_missing(ledger):
    result = _post(ledger, day=datetime.date(2031, 2, 1))
    assert isinstance(result, Err) and result.code == "PERIOD_MISSING"


def test_an_unbalanced_entry_is_refused_and_writes_nothing(ledger):
    result = _post(ledger, lines=[EntryLine("521", debit=D(10)), EntryLine("101", credit=D(9))])
    assert isinstance(result, Err) and result.code == "ENTRY_UNBALANCED"
    assert _count(ledger) == 0


def test_a_heading_account_is_refused(ledger):
    result = _post(ledger, lines=[EntryLine("52", debit=D(10)), EntryLine("101", credit=D(10))])
    assert isinstance(result, Err) and result.code == "ACCOUNT_NOT_POSTABLE"


def test_an_unknown_journal_is_refused(ledger):
    result = _post(ledger, journal="XYZ")
    assert isinstance(result, Err) and result.code == "NOT_FOUND"


def test_the_same_source_posts_once(ledger):
    source = SourceRef("payroll", "RUN-1", "payroll_run")
    first = _post(ledger, source=source)
    second = _post(ledger, source=source)
    assert first.value["id"] == second.value["id"]
    assert _count(ledger) == 1


def test_posted_lines_and_headers_are_frozen(ledger):
    entry_id = _post(ledger).value["id"]
    db = ledger["db"]
    for statement in (
        "UPDATE finance.journal_lines SET debit = debit + 1 WHERE entry_id = %s",
        "DELETE FROM finance.journal_lines WHERE entry_id = %s",
        "UPDATE finance.journal_entries SET label = 'changed' WHERE id = %s",
        "DELETE FROM finance.journal_entries WHERE id = %s",
    ):
        with pytest.raises(psycopg.errors.RaiseException, match="ENTRY_POSTED"):
            with db.transaction():
                db.execute(statement, (entry_id,))
    with pytest.raises(psycopg.errors.RaiseException, match="ENTRY_POSTED"):
        with db.transaction():
            db.execute(
                """
                INSERT INTO finance.journal_lines (id, tenant_id, entry_id, line_no, account_code, debit)
                VALUES (%s, %s, %s, 99, '521', 1)
                """,
                (str(ULID()), ledger["tenant"], entry_id),
            )


def test_the_deferred_trigger_refuses_a_posted_unbalanced_entry(ledger):
    db = ledger["db"]
    entry_id = str(ULID())
    with pytest.raises(psycopg.errors.RaiseException, match="ENTRY_UNBALANCED"):
        with db.transaction():
            db.execute(
                """
                INSERT INTO finance.journal_entries (id, tenant_id, journal_code, entry_date, period, label, created_by)
                VALUES (%s, %s, 'OD', '2030-01-20', '2030-01-01', 'bypass', %s)
                """,
                (entry_id, ledger["tenant"], ledger["actor"]),
            )
            db.execute(
                """
                INSERT INTO finance.journal_lines (id, tenant_id, entry_id, line_no, account_code, debit)
                VALUES (%s, %s, %s, 1, '521', 500)
                """,
                (str(ULID()), ledger["tenant"], entry_id),
            )
            db.execute(
                "UPDATE finance.journal_entries SET status = 'posted', number = 'OD-TEST-1', posted_at = NOW() WHERE id = %s",
                (entry_id,),
            )
            db.execute("SET CONSTRAINTS ALL IMMEDIATE")


def test_reversing_mirrors_the_entry_and_marks_it_reversed(ledger):
    posting = LedgerPostingService(ledger["db"])
    original = _post(ledger, source=SourceRef("payroll", "RUN-2", "payroll_run")).value
    reversal = posting.reverse_entry(
        tenant_id=ledger["tenant"], actor_id=ledger["actor"], entry_id=original["id"],
        entry_date=datetime.date(2030, 2, 3), correlation_id=str(ULID()),
    )
    assert isinstance(reversal, Ok), reversal
    assert reversal.value["reversal_of"] == original["id"]
    assert reversal.value["source_kind"] == "payroll_run_reversal"
    assert reversal.value["label"] == f"Extourne de {original['number']}"
    lines = ledger["db"].execute(
        "SELECT account_code, debit, credit FROM finance.journal_lines WHERE entry_id = %s ORDER BY line_no",
        (reversal.value["id"],),
    ).fetchall()
    assert lines == [("521", D(0), D(1000000)), ("101", D(1000000), D(0))]
    assert posting.get_summary(tenant_id=ledger["tenant"], entry_id=original["id"])["status"] == "reversed"
    again = posting.reverse_entry(
        tenant_id=ledger["tenant"], actor_id=ledger["actor"], entry_id=original["id"],
        entry_date=datetime.date(2030, 2, 3), correlation_id=str(ULID()),
    )
    assert isinstance(again, Err) and again.code == "INVALID_TRANSITION"
    ledger["db"].execute("SET CONSTRAINTS ALL IMMEDIATE")


def test_posting_an_entry_twice_is_refused(ledger):
    entry = _post(ledger).value
    again = LedgerPostingService(ledger["db"]).post_draft(
        tenant_id=ledger["tenant"], actor_id=ledger["actor"], entry_id=entry["id"], correlation_id=str(ULID())
    )
    assert isinstance(again, Err) and again.code == "ENTRY_POSTED"
