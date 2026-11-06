"""Where a source document stands in the ledger -- pure rules, no database.

A document is identified by (source_module, source_id). Its automatic entries carry that pair plus a
source_kind (a receipt has one entry per payment method, an invoice one when issued and one when
paid...), so the status looks at every entry and refusal of the document together.
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass, field

POSTED = "posted"
FAILED = "failed"
REVERSED = "reversed"
NOT_POSTED = "not_posted"
OFF = "off"
STATUSES = (POSTED, FAILED, REVERSED, NOT_POSTED, OFF)


@dataclass(frozen=True)
class EntryRow:
    id: str
    number: str | None
    entry_date: datetime.date
    status: str  # draft | posted | reversed
    reversal_of: str | None


@dataclass(frozen=True)
class FailureRow:
    id: str
    source_kind: str
    error_code: str
    error_message: str
    error_message_fr: str | None


@dataclass(frozen=True)
class LedgerStatus:
    status: str
    entries: list[EntryRow] = field(default_factory=list)
    failure: FailureRow | None = None
    parts: list["PartStatus"] = field(default_factory=list)


# The parts of a treasury document: its own entries, then per instrument its collection, unpaid and fee.
DOCUMENT = "document"
COLLECTION = "collection"
UNPAID = "unpaid"
REJECTION_FEE = "rejection_fee"
INSTRUMENT_PARTS = {"instrument_collected": COLLECTION, "instrument_unpaid": UNPAID, "instrument_rejection_fee": REJECTION_FEE}


@dataclass(frozen=True)
class PartStatus:
    part: str
    instrument_number: str | None
    expected: bool  # whether the document has reached the point where this part should be in the ledger
    status: LedgerStatus


def instrument_part(source_kind: str) -> str | None:
    """Which part of its instrument an entry or refusal belongs to, by its source kind."""
    return next((part for prefix, part in INSTRUMENT_PARTS.items() if source_kind.startswith(prefix)), None)


def expected_parts(instrument_status: str, has_rejection_fee: bool) -> set[str]:
    """What an instrument should have in the ledger so far. A pending one, nothing; collected, its collection;
    unpaid, the unpaid entry and any fee (its collection, if there was one, was reversed by the unpaid)."""
    if instrument_status == "collected":
        return {COLLECTION}
    if instrument_status == "unpaid":
        return {UNPAID, REJECTION_FEE} if has_rejection_fee else {UNPAID}
    return set()


def derive_document_status(parts: list[PartStatus], *, posting_off: bool = False) -> LedgerStatus:
    """A document with several parts (a treasury document and its instruments). Refused wins if any part is
    refused; reversed when the document's own entries were undone; posted only when every part expected so
    far is in the ledger (a pending cheque doesn't hold it back); otherwise off or not posted."""
    shown = [p for p in parts if p.expected or p.status.status != NOT_POSTED]
    failed = next((p for p in parts if p.status.status == FAILED), None)
    if failed is not None:
        return LedgerStatus(FAILED, failure=failed.status.failure, parts=shown)
    document = next((p for p in parts if p.part == DOCUMENT), None)
    if document is not None and document.status.status == REVERSED:
        return LedgerStatus(REVERSED, entries=document.status.entries, parts=shown)
    required = [p for p in parts if p.expected]
    if required and all(p.status.status in (POSTED, REVERSED) for p in required):
        entries = [e for p in parts for e in p.status.entries if e.status == "posted"]
        return LedgerStatus(POSTED, entries=entries, parts=shown)
    return LedgerStatus(OFF if posting_off else NOT_POSTED, parts=shown)


def derive_status(entries: list[EntryRow], open_failures: list[FailureRow], *, posting_off: bool = False) -> LedgerStatus:
    """An open refusal comes first: it is the one state that needs someone to act. Then the document's
    own entries (reversal entries excluded): all of them reversed means the document was undone in the
    ledger, otherwise it is posted. Nothing at all is "off" when its module's posting is switched off,
    else "not_posted" -- the event may simply not have been processed yet."""
    if open_failures:
        return LedgerStatus(FAILED, failure=sorted(open_failures, key=lambda f: f.id)[0])
    originals = sorted(
        (e for e in entries if e.reversal_of is None and e.status in ("posted", "reversed")),
        key=lambda e: (e.entry_date, e.number or ""),
    )
    if originals:
        if all(e.status == "reversed" for e in originals):
            return LedgerStatus(REVERSED, entries=originals)
        return LedgerStatus(POSTED, entries=[e for e in originals if e.status == "posted"])
    return LedgerStatus(OFF if posting_off else NOT_POSTED)
