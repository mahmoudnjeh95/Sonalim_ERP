"""Manual OD entries (draft -> posted -> reversed) and the ledger's read side."""
from __future__ import annotations

import datetime
from decimal import Decimal

from ulid import ULID

from core.domain.result import Err, Ok
from modules.finance.api.ledger_posting_service import LedgerPostingService
from modules.finance.api.ledger_query_service import LedgerQueryService
from modules.finance.api.manual_entry_service import ManualEntryService
from modules.finance.api.period_service import PeriodService
from modules.finance.domain.ledger import EntryLine, SourceRef

D = Decimal
FEBRUARY = datetime.date(2030, 2, 1)
END_OF_FEBRUARY = datetime.date(2030, 2, 28)
DAY = datetime.date(2030, 2, 14)
BALANCED = [EntryLine("641", debit=D(150000)), EntryLine("521", credit=D(150000))]


def _draft(ledger, lines=BALANCED):
    return ManualEntryService(ledger["db"]).create_draft(
        tenant_id=ledger["tenant"], actor_id=ledger["actor"], journal_code="OD", entry_date=DAY,
        label="Patente 2030", lines=lines, reference="AVIS-2030-17",
    )


def _post(ledger, entry_id: str):
    return ManualEntryService(ledger["db"]).post(
        tenant_id=ledger["tenant"], actor_id=ledger["actor"], entry_id=entry_id, correlation_id=str(ULID())
    )


def test_a_draft_may_be_unbalanced_and_is_posted_only_once_it_balances(ledger):
    manual = ManualEntryService(ledger["db"])
    draft = _draft(ledger, [EntryLine("641", debit=D(150000)), EntryLine("521", credit=D(100000))])
    assert isinstance(draft, Ok), draft
    entry_id = draft.value["id"]
    assert draft.value["status"] == "draft" and draft.value["number"] is None
    refused = _post(ledger, entry_id)
    assert isinstance(refused, Err) and refused.code == "ENTRY_UNBALANCED"
    fixed = manual.update_draft(tenant_id=ledger["tenant"], actor_id=ledger["actor"], entry_id=entry_id, lines=BALANCED)
    assert isinstance(fixed, Ok), fixed
    assert fixed.value["total_credit"] == D(150000)
    posted = _post(ledger, entry_id)
    assert isinstance(posted, Ok), posted
    assert posted.value["number"] == "OD-2030-000001"
    actions = {row[0] for row in ledger["db"].execute("SELECT action FROM core.audit_log WHERE entity_id = %s", (entry_id,))}
    assert actions == {"journal_entry.created", "journal_entry.updated", "journal_entry.posted"}


def test_a_posted_entry_is_never_edited_or_deleted(ledger):
    manual = ManualEntryService(ledger["db"])
    entry_id = _draft(ledger).value["id"]
    _post(ledger, entry_id)
    edited = manual.update_draft(tenant_id=ledger["tenant"], actor_id=ledger["actor"], entry_id=entry_id, label="changed")
    assert isinstance(edited, Err) and edited.code == "ENTRY_POSTED" and edited.message_fr
    deleted = manual.delete_draft(tenant_id=ledger["tenant"], actor_id=ledger["actor"], entry_id=entry_id)
    assert isinstance(deleted, Err) and deleted.code == "ENTRY_POSTED"


def test_a_draft_can_be_deleted_and_the_deletion_is_audited(ledger):
    entry_id = _draft(ledger).value["id"]
    deleted = ManualEntryService(ledger["db"]).delete_draft(tenant_id=ledger["tenant"], actor_id=ledger["actor"], entry_id=entry_id)
    assert isinstance(deleted, Ok)
    assert LedgerQueryService(ledger["db"]).get_entry(tenant_id=ledger["tenant"], entry_id=entry_id) is None
    payload = ledger["db"].execute(
        "SELECT payload FROM core.audit_log WHERE entity_id = %s AND action = 'journal_entry.deleted'", (entry_id,)
    ).fetchone()[0]
    assert payload["label"] == "Patente 2030" and payload["status"] == "draft"


def test_a_draft_in_a_period_closed_later_cannot_be_posted_until_reopened(ledger):
    periods = PeriodService(ledger["db"])
    entry_id = _draft(ledger).value["id"]
    periods.close_period(tenant_id=ledger["tenant"], actor_id=ledger["actor"], period=FEBRUARY)
    refused = _post(ledger, entry_id)
    assert isinstance(refused, Err) and refused.code == "PERIOD_CLOSED"
    assert LedgerQueryService(ledger["db"]).get_entry(tenant_id=ledger["tenant"], entry_id=entry_id)["status"] == "draft"
    periods.reopen_period(tenant_id=ledger["tenant"], actor_id=ledger["actor"], period=FEBRUARY)
    assert isinstance(_post(ledger, entry_id), Ok)


def test_a_manual_entry_is_corrected_by_its_mirror(ledger):
    entry_id = _draft(ledger).value["id"]
    _post(ledger, entry_id)
    reversal = ManualEntryService(ledger["db"]).reverse(
        tenant_id=ledger["tenant"], actor_id=ledger["actor"], entry_id=entry_id,
        entry_date=END_OF_FEBRUARY, correlation_id=str(ULID()),
    )
    assert isinstance(reversal, Ok), reversal
    assert reversal.value["reversal_of"] == entry_id and reversal.value["source_kind"] is None
    assert LedgerQueryService(ledger["db"]).get_entry(tenant_id=ledger["tenant"], entry_id=entry_id)["status"] == "reversed"


def test_the_entry_detail_names_accounts_and_partners(ledger):
    partner_id = str(ULID())
    ledger["db"].execute(
        "INSERT INTO core.partners (id, tenant_id, name, kind) VALUES (%s, %s, %s, 'customer')",
        (partner_id, ledger["tenant"], f"Client {partner_id}"),
    )
    entry_id = _draft(
        ledger, [EntryLine("411", debit=D(5000), partner_id=partner_id, label="Facture manuelle"), EntryLine("702", credit=D(5000))]
    ).value["id"]
    detail = LedgerQueryService(ledger["db"]).get_entry(tenant_id=ledger["tenant"], entry_id=entry_id)
    assert [(line["account_code"], line["account_name"], line["partner_name"]) for line in detail["lines"]] == [
        ("411", "Clients", f"Client {partner_id}"),
        ("702", "Ventes de produits finis", None),
    ]


def test_entries_are_found_by_source_and_by_filters(ledger):
    posting = LedgerPostingService(ledger["db"])
    for kind, journal, lines in (
        ("payroll_run", "PAIE", [EntryLine("661", debit=D(100)), EntryLine("422", credit=D(100))]),
        ("payroll_payment_bank", "BNQ", [EntryLine("422", debit=D(100)), EntryLine("521", credit=D(100))]),
    ):
        posted = posting.post_entry(
            tenant_id=ledger["tenant"], actor_id=ledger["actor"], journal_code=journal, entry_date=DAY,
            label="Paie 02/2030", lines=lines, correlation_id=str(ULID()), source=SourceRef("payroll", "RUN-Q", kind),
        )
        assert isinstance(posted, Ok), posted
    _draft(ledger)
    query = LedgerQueryService(ledger["db"])
    found = query.entries_for_source(tenant_id=ledger["tenant"], source_module="payroll", source_id="RUN-Q")
    assert sorted(entry["source_kind"] for entry in found) == ["payroll_payment_bank", "payroll_run"]
    assert {entry["status"] for entry in found} == {"posted"}
    february = query.list_entries(tenant_id=ledger["tenant"], date_from=FEBRUARY, date_to=END_OF_FEBRUARY)
    assert len(february) == 3
    paie = query.list_entries(tenant_id=ledger["tenant"], date_from=FEBRUARY, date_to=END_OF_FEBRUARY, journal_code="PAIE")
    assert [entry["journal_code"] for entry in paie] == ["PAIE"]
    drafts = query.list_entries(tenant_id=ledger["tenant"], date_from=FEBRUARY, date_to=END_OF_FEBRUARY, status="draft")
    assert len(drafts) == 1
    march = query.list_entries(tenant_id=ledger["tenant"], date_from=datetime.date(2030, 3, 1), date_to=datetime.date(2030, 3, 31))
    assert march == []
