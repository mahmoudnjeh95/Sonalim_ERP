import datetime

from modules.finance.domain.ledger_status import (
    FAILED,
    NOT_POSTED,
    OFF,
    POSTED,
    REVERSED,
    EntryRow,
    FailureRow,
    PartStatus,
    derive_document_status,
    derive_status,
    expected_parts,
    instrument_part,
)

DAY = datetime.date(2030, 1, 20)


def _entry(entry_id, status="posted", reversal_of=None, day=DAY, number=None):
    return EntryRow(entry_id, number or f"BNQ-{entry_id}", day, status, reversal_of)


def _failure(failure_id="F1", kind="receipt_payment"):
    return FailureRow(failure_id, kind, "RULE_MISSING", "no rule", "aucune règle")


def test_nothing_is_not_posted_or_off_when_the_switch_is_off():
    assert derive_status([], []).status == NOT_POSTED
    assert derive_status([], [], posting_off=True).status == OFF


def test_posted_lists_the_documents_own_entries_by_date():
    status = derive_status([_entry("2", day=DAY.replace(day=21)), _entry("1")], [])
    assert status.status == POSTED and [e.id for e in status.entries] == ["1", "2"]


def test_drafts_and_reversal_entries_do_not_count_as_posted():
    assert derive_status([_entry("1", status="draft")], []).status == NOT_POSTED
    status = derive_status([_entry("1", status="reversed"), _entry("2", reversal_of="1")], [])
    assert status.status == REVERSED and [e.id for e in status.entries] == ["1"]


def test_one_entry_still_standing_keeps_the_document_posted():
    status = derive_status([_entry("1", status="reversed"), _entry("2"), _entry("3", reversal_of="1")], [])
    assert status.status == POSTED and [e.id for e in status.entries] == ["2"]


def test_an_open_refusal_wins_over_everything():
    status = derive_status([_entry("1")], [_failure("F2"), _failure("F1")], posting_off=True)
    assert status.status == FAILED and status.failure.id == "F1"


def _part(part, status, expected=True, number="CH1"):
    return PartStatus(part, None if part == "document" else number, expected, status)


def test_instrument_parts_follow_the_instrument_and_the_source_kind():
    assert expected_parts("pending", False) == set()
    assert expected_parts("collected", False) == {"collection"}
    assert expected_parts("unpaid", True) == {"unpaid", "rejection_fee"}
    assert instrument_part("instrument_collected_reversal") == "collection"
    assert instrument_part("instrument_rejection_fee") == "rejection_fee"
    assert instrument_part("receipt_payment_cheque") is None


def test_a_document_is_posted_only_when_every_expected_part_is():
    doc = _part("document", derive_status([_entry("1")], []))
    waiting = _part("collection", derive_status([], []))
    assert derive_document_status([doc, _part("collection", derive_status([], []), expected=False)]).status == POSTED
    assert derive_document_status([doc, waiting]).status == NOT_POSTED
    assert derive_document_status([doc, waiting], posting_off=True).status == OFF
    # A reversed collection (the cheque bounced) counts as done, and stays listed.
    undone = _part("collection", derive_status([_entry("2", status="reversed")], []), expected=False)
    unpaid = _part("unpaid", derive_status([_entry("3")], []))
    status = derive_document_status([doc, undone, unpaid])
    assert status.status == POSTED and [p.part for p in status.parts] == ["document", "collection", "unpaid"]


def test_any_refused_part_makes_the_document_refused_and_a_reversed_document_is_reversed():
    doc = _part("document", derive_status([_entry("1")], []))
    refused = _part("rejection_fee", derive_status([], [_failure("F9", "instrument_rejection_fee")]))
    status = derive_document_status([doc, refused])
    assert status.status == FAILED and status.failure.id == "F9"
    gone = _part("document", derive_status([_entry("1", status="reversed"), _entry("2", reversal_of="1")], []))
    assert derive_document_status([gone]).status == REVERSED
