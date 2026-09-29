"""Trial balance, general ledger and the 42x/43x/44x balances over booked entries."""
from __future__ import annotations

import datetime
from decimal import Decimal

from ulid import ULID

from core.domain.result import Err, Ok
from modules.finance.api.ledger_posting_service import LedgerPostingService
from modules.finance.api.ledger_report_service import LedgerReportService
from modules.finance.api.manual_entry_service import ManualEntryService
from modules.finance.domain.ledger import EntryLine

D = Decimal
FEB_FROM, FEB_TO = datetime.date(2030, 2, 1), datetime.date(2030, 2, 28)


def _post(ledger, day: datetime.date, label: str, lines: list[EntryLine]) -> dict:
    result = LedgerPostingService(ledger["db"]).post_entry(
        tenant_id=ledger["tenant"], actor_id=ledger["actor"], journal_code="OD", entry_date=day,
        label=label, lines=lines, correlation_id=str(ULID()),
    )
    assert isinstance(result, Ok), result
    return result.value


def _book(ledger) -> None:
    """January: capital paid in. February: a payroll (661 against 422 and 431) and its payment,
    plus a draft that no report may count."""
    _post(ledger, datetime.date(2030, 1, 10), "Apport en capital",
          [EntryLine("521", debit=D(1000000)), EntryLine("101", credit=D(1000000))])
    _post(ledger, FEB_TO, "Paie 02/2030",
          [EntryLine("661", debit=D(320000)), EntryLine("422", credit=D(300000)), EntryLine("431", credit=D(20000))])
    _post(ledger, FEB_TO, "Virement des salaires",
          [EntryLine("422", debit=D(300000)), EntryLine("521", credit=D(300000))])
    ManualEntryService(ledger["db"]).create_draft(
        tenant_id=ledger["tenant"], actor_id=ledger["actor"], journal_code="OD", entry_date=datetime.date(2030, 2, 20),
        label="Brouillon ignoré", lines=[EntryLine("661", debit=D(5)), EntryLine("521", credit=D(5))],
    )


def test_the_trial_balance_splits_opening_period_and_closing(ledger):
    _book(ledger)
    report = LedgerReportService(ledger["db"]).trial_balance(tenant_id=ledger["tenant"], date_from=FEB_FROM, date_to=FEB_TO)
    rows = {row["account_code"]: row for row in report["rows"]}
    assert set(rows) == {"101", "422", "431", "521", "661"}
    assert (rows["101"]["opening_credit"], rows["101"]["closing_credit"]) == (D(1000000), D(1000000))
    assert (rows["521"]["opening_debit"], rows["521"]["period_credit"], rows["521"]["closing_debit"]) == (
        D(1000000), D(300000), D(700000),
    )
    assert (
        rows["422"]["period_debit"], rows["422"]["period_credit"], rows["422"]["closing_debit"], rows["422"]["closing_credit"]
    ) == (D(300000), D(300000), D(0), D(0))
    assert rows["431"]["closing_credit"] == D(20000)
    assert rows["661"]["closing_debit"] == D(320000)
    totals = report["totals"]
    assert totals["opening_debit"] == totals["opening_credit"] == D(1000000)
    assert totals["period_debit"] == totals["period_credit"] == D(620000)
    assert totals["closing_debit"] == totals["closing_credit"] == D(1020000)


def test_a_reversed_pair_nets_to_zero_but_stays_visible(ledger):
    _book(ledger)
    posted = _post(ledger, datetime.date(2030, 2, 10), "Erreur de saisie",
                   [EntryLine("661", debit=D(7000)), EntryLine("571", credit=D(7000))])
    LedgerPostingService(ledger["db"]).reverse_entry(
        tenant_id=ledger["tenant"], actor_id=ledger["actor"], entry_id=posted["id"],
        entry_date=datetime.date(2030, 2, 11), correlation_id=str(ULID()),
    )
    report = LedgerReportService(ledger["db"]).trial_balance(tenant_id=ledger["tenant"], date_from=FEB_FROM, date_to=FEB_TO)
    rows = {row["account_code"]: row for row in report["rows"]}
    assert (
        rows["571"]["period_debit"], rows["571"]["period_credit"], rows["571"]["closing_debit"], rows["571"]["closing_credit"]
    ) == (D(7000), D(7000), D(0), D(0))
    assert rows["661"]["closing_debit"] == D(320000)


def test_the_general_ledger_runs_a_balance_from_the_opening(ledger):
    _book(ledger)
    reports = LedgerReportService(ledger["db"])
    result = reports.general_ledger(tenant_id=ledger["tenant"], account_code="521", date_from=FEB_FROM, date_to=FEB_TO)
    assert isinstance(result, Ok), result
    view = result.value
    assert view["account"]["name"] == "Banques locales"
    assert view["opening_balance"] == D(1000000)
    assert [(line["label"], line["credit"], line["balance"]) for line in view["lines"]] == [
        ("Virement des salaires", D(300000), D(700000)),
    ]
    assert (view["total_debit"], view["total_credit"], view["closing_balance"]) == (D(0), D(300000), D(700000))
    missing = reports.general_ledger(tenant_id=ledger["tenant"], account_code="999", date_from=FEB_FROM, date_to=FEB_TO)
    assert isinstance(missing, Err) and missing.code == "NOT_FOUND"


def test_balances_show_what_is_owed_to_staff_social_bodies_and_the_state(ledger):
    _book(ledger)
    reports = LedgerReportService(ledger["db"])
    balances = reports.account_balances(tenant_id=ledger["tenant"], prefixes=["42", "43", "44"], as_of=FEB_TO)
    owed = {row["account_code"]: row["owed"] for row in balances}
    assert owed["422"] == D(0) and owed["431"] == D(20000) and owed["447"] == D(0)
    assert set(owed) >= {"421", "422", "431", "433", "441", "442", "443", "444", "445", "446", "447"}
    assert "42" not in owed  # headings are not listed
    january = reports.account_balances(tenant_id=ledger["tenant"], prefixes=["43"], as_of=datetime.date(2030, 1, 31))
    assert [row["owed"] for row in january] == [D(0), D(0)]
