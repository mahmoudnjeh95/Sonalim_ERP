"""Treasury into the ledger: receipts and disbursements, cheques and drafts collected or bounced.

The lines come from treasury's public API only (`TreasuryPostingService`); finance never reads
treasury tables. Treasury is an optional dependency, imported when a treasury event is posted.
Account numbers come from `finance.posting_rules` (source 'treasury') and from the ledger code of
each treasury account, never from this file; see `domain/treasury_posting.py`.

Posting is off until the tenant sets the treasury setting `ledger_posting_enabled` (see
`events/ledger_consumers.py`); events that arrive while it is off are skipped, not queued, so enabling
it later needs the backfill of earlier documents."""
from __future__ import annotations

import datetime
from typing import Callable

import psycopg

from core.atomic import atomic
from core.domain.result import Err, Ok, Result
from modules.finance.api.ledger_posting_service import SYSTEM_ACTOR, LedgerPostingService
from modules.finance.api.posting_rule_service import PostingRuleService
from modules.finance.domain.ledger import SourceRef
from modules.finance.domain.treasury_posting import (
    DIRECTION_NOUN,
    METHODS,
    TreasuryEntry,
    document_entries,
    instrument_entry,
    opening_entry,
    rejection_fee_entry,
)

TREASURY_MODULE = "treasury"
ADVANCE = "advance"
WITHHELD = "withheld"
KIND_COLLECTED = "instrument_collected"
KIND_UNPAID = "instrument_unpaid"
KIND_REJECTION_FEE = "instrument_rejection_fee"
KIND_OPENING = "account_opening"

# What a slip collected, in the words of its method: only cheques and drafts are "effets".
COLLECTED_NOUN = {
    ("in", "cheque"): "Encaissement chèque", ("in", "draft"): "Encaissement traite", ("in", "cash"): "Versement espèces",
    ("in", "transfer"): "Virement reçu", ("in", "mobile_money"): "Mobile money reçu",
    ("out", "cheque"): "Paiement chèque", ("out", "draft"): "Paiement traite",
}
UNPAID_NOUN = {"cheque": "Chèque impayé", "draft": "Traite impayée"}


def collection_label(direction: str, method: str, number: str) -> str:
    default = "Encaissement" if direction == "in" else "Paiement"
    return f"{COLLECTED_NOUN.get((direction, method), default)} {number}"


def _default_treasury_api(connection: psycopg.Connection):
    from modules.treasury.api.posting_service import TreasuryPostingService

    return TreasuryPostingService(connection)


# The one seam tests may replace with a fake; production code never reassigns it.
TREASURY_API_FACTORY: Callable[[psycopg.Connection], object] = _default_treasury_api


def ledger_posting_enabled(connection: psycopg.Connection, tenant_id: str) -> bool:
    return bool(TREASURY_API_FACTORY(connection).ledger_posting_enabled(tenant_id=tenant_id))


class TreasuryLedgerService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection
        self._posting = LedgerPostingService(connection)
        self._rules = PostingRuleService(connection)
        self._treasury = TREASURY_API_FACTORY(connection)

    # -- receipts and disbursements -------------------------------------------------------------

    @atomic
    def post_document(
        self, *, tenant_id: str, direction: str, document_id: str, correlation_id: str, causation_id: str | None = None
    ) -> Result[list[dict]]:
        noun = DIRECTION_NOUN[direction]
        document = self._treasury.document_lines(tenant_id=tenant_id, document_id=document_id)
        if isinstance(document, Err):
            return document
        doc = document.value
        if doc["status"] != "posted":
            # Cancelled since the event was published (a late delivery, or the retry of a refused
            # posting): the cancellation found nothing to reverse, so posting now would never be undone.
            return Ok([])
        label = f"{'Encaissement' if direction == 'in' else 'Décaissement'} {doc['number']}"
        entries = document_entries(
            direction,
            payments=doc["payments"],
            unallocated=doc["unallocated"],
            partner_id=doc["partner_id"],
            currency=doc["currency"],
            label=label,
            rules=self._rules.rules_for(tenant_id=tenant_id, source=TREASURY_MODULE),
            withheld=doc.get("withheld", 0),
        )
        if isinstance(entries, Err):
            return entries
        return self._post_all(
            tenant_id=tenant_id, kind=f"{noun}_payment", source_id=document_id, entries=entries.value,
            entry_date=doc["date"], label=label, reference=doc["number"],
            correlation_id=correlation_id, causation_id=causation_id,
        )

    @atomic
    def cancel_document(
        self, *, tenant_id: str, direction: str, document_id: str, cancelled_on: datetime.date,
        correlation_id: str, causation_id: str | None = None,
    ) -> Result[list[dict]]:
        """Reverses whatever was posted for the document; a document that was never posted is a no-op."""
        noun = DIRECTION_NOUN[direction]
        reversed_entries: list[dict] = []
        for suffix in (*METHODS, ADVANCE, WITHHELD):
            original = self._posting.find_by_source(
                tenant_id=tenant_id, source=SourceRef(TREASURY_MODULE, document_id, f"{noun}_payment_{suffix}")
            )
            if original is None or original["status"] != "posted":
                continue
            done = self._posting.reverse_entry(
                tenant_id=tenant_id, actor_id=SYSTEM_ACTOR, entry_id=original["id"], entry_date=cancelled_on,
                correlation_id=correlation_id, causation_id=causation_id,
            )
            if isinstance(done, Err):
                return done
            reversed_entries.append(done.value)
        return Ok(reversed_entries)

    # -- cheques and drafts ---------------------------------------------------------------------

    def post_instrument_collected(
        self, *, tenant_id: str, instrument_id: str, account_id: str | None, collected_on: datetime.date,
        correlation_id: str, causation_id: str | None = None,
    ) -> Result[list[dict]]:
        instrument = self._treasury.instrument_lines(tenant_id=tenant_id, instrument_id=instrument_id)
        if isinstance(instrument, Err):
            return instrument
        inst = instrument.value
        if inst["status"] != "collected":
            # It bounced since: the unpaid posting found no collection to reverse, so posting one now
            # would leave the money in the bank account in the ledger for good.
            return Ok([])
        label = collection_label(inst["direction"], inst["method"], inst["number"])
        landed_in = account_id or inst["account_id"]
        entry = instrument_entry(
            KIND_COLLECTED, direction=inst["direction"], method=inst["method"], amount=inst["amount"], currency=inst["currency"],
            partner_id=inst["partner_id"],
            account_ledger_code=self._treasury.account_ledger_code(tenant_id=tenant_id, account_id=landed_in),
            label=label, rules=self._rules.rules_for(tenant_id=tenant_id, source=TREASURY_MODULE),
            account_kind=self._treasury.account_kind(tenant_id=tenant_id, account_id=landed_in),
        )
        if isinstance(entry, Err):
            return entry
        return self._post_all(
            tenant_id=tenant_id, kind=KIND_COLLECTED, source_id=instrument_id, entries=[entry.value],
            entry_date=collected_on, label=label, reference=inst["number"],
            correlation_id=correlation_id, causation_id=causation_id,
        )

    @atomic
    def post_instrument_unpaid(
        self, *, tenant_id: str, instrument_id: str, unpaid_on: datetime.date,
        correlation_id: str, causation_id: str | None = None,
    ) -> Result[list[dict]]:
        """A bounced cheque: undo its collection (when one was posted), then put the debt back."""
        posted: list[dict] = []
        collected = self._posting.find_by_source(
            tenant_id=tenant_id, source=SourceRef(TREASURY_MODULE, instrument_id, KIND_COLLECTED)
        )
        if collected is not None and collected["status"] == "posted":
            undone = self._posting.reverse_entry(
                tenant_id=tenant_id, actor_id=SYSTEM_ACTOR, entry_id=collected["id"], entry_date=unpaid_on,
                correlation_id=correlation_id, causation_id=causation_id,
            )
            if isinstance(undone, Err):
                return undone
            posted.append(undone.value)
        instrument = self._treasury.instrument_lines(tenant_id=tenant_id, instrument_id=instrument_id)
        if isinstance(instrument, Err):
            return instrument
        inst = instrument.value
        label = f"{UNPAID_NOUN.get(inst['method'], 'Effet impayé')} {inst['number']}"
        entry = instrument_entry(
            KIND_UNPAID, direction=inst["direction"], method=inst["method"], amount=inst["amount"], currency=inst["currency"],
            partner_id=inst["partner_id"], account_ledger_code=None, label=label,
            rules=self._rules.rules_for(tenant_id=tenant_id, source=TREASURY_MODULE),
        )
        if isinstance(entry, Err):
            return entry
        done = self._post_all(
            tenant_id=tenant_id, kind=KIND_UNPAID, source_id=instrument_id, entries=[entry.value],
            entry_date=unpaid_on, label=label, reference=inst["number"],
            correlation_id=correlation_id, causation_id=causation_id,
        )
        if isinstance(done, Err):
            return done
        posted += done.value
        if inst["rejection_fee"] is None:
            return Ok(posted)
        fee_label = f"Frais de rejet {inst['number']}"
        fee = rejection_fee_entry(
            direction=inst["direction"], amount=inst["rejection_fee"], currency=inst["currency"],
            account_ledger_code=inst["rejection_fee_ledger_code"], label=fee_label,
            rules=self._rules.rules_for(tenant_id=tenant_id, source=TREASURY_MODULE),
        )
        if isinstance(fee, Err):
            return fee
        charged = self._post_all(
            tenant_id=tenant_id, kind=KIND_REJECTION_FEE, source_id=instrument_id, entries=[fee.value],
            entry_date=unpaid_on, label=fee_label, reference=inst["number"],
            correlation_id=correlation_id, causation_id=causation_id,
        )
        if isinstance(charged, Err):
            return charged
        return Ok(posted + charged.value)

    # -- opening balances -----------------------------------------------------------------------

    @atomic
    def open_accounts(
        self, *, tenant_id: str, opened_on: datetime.date, correlation_id: str, account_id: str | None = None
    ) -> Result[list[dict]]:
        """Brings each treasury account's balance (or one account's) into the ledger, once per account.
        Called when posting is switched on, and for an account created while it is on. All or nothing: one
        refused account refuses the lot, so the switch never stays half-opened."""
        posted: list[dict] = []
        rules = self._rules.rules_for(tenant_id=tenant_id, source=TREASURY_MODULE)
        for account in self._treasury.accounts_for_opening(tenant_id=tenant_id, account_id=account_id):
            if self._posting.find_by_source(tenant_id=tenant_id, source=SourceRef(TREASURY_MODULE, account["id"], KIND_OPENING)):
                continue
            label = f"Solde d'ouverture {account['name']}"
            entry = opening_entry(
                account_kind=account["kind"], balance=account["balance"], currency=account["currency"],
                account_ledger_code=account["ledger_account_code"], label=label, rules=rules,
            )
            if isinstance(entry, Err):
                return Err(
                    "LEDGER_OPENING_REFUSED",
                    f"the opening balance of {account['name']} cannot be posted: {entry.message}",
                    f"le solde d'ouverture de {account['name']} ne peut pas être comptabilisé : {entry.message_fr or entry.message}",
                )
            if entry.value is None:
                continue
            done = self._post_all(
                tenant_id=tenant_id, kind=KIND_OPENING, source_id=account["id"], entries=[entry.value], entry_date=opened_on,
                label=label, reference=account["name"], correlation_id=correlation_id, causation_id=None,
            )
            if isinstance(done, Err):
                return Err(
                    "LEDGER_OPENING_REFUSED",
                    f"the opening balance of {account['name']} cannot be posted: {done.message}",
                    f"le solde d'ouverture de {account['name']} ne peut pas être comptabilisé : {done.message_fr or done.message}",
                )
            posted += done.value
        return Ok(posted)

    # -- shared ---------------------------------------------------------------------------------

    def _post_all(
        self, *, tenant_id: str, kind: str, source_id: str, entries: list[TreasuryEntry], entry_date: datetime.date,
        label: str, reference: str | None, correlation_id: str, causation_id: str | None,
    ) -> Result[list[dict]]:
        """One journal entry per TreasuryEntry, each idempotent on (treasury, source_id, kind[_suffix])."""
        posted: list[dict] = []
        for entry in entries:
            source_kind = f"{kind}_{entry.suffix}" if entry.suffix else kind
            result = self._posting.post_entry(
                tenant_id=tenant_id, actor_id=SYSTEM_ACTOR, journal_code=entry.journal_code, entry_date=entry_date,
                label=label, lines=entry.lines, correlation_id=correlation_id,
                source=SourceRef(TREASURY_MODULE, source_id, source_kind), reference=reference, causation_id=causation_id,
            )
            if isinstance(result, Err):
                return result
            posted.append(result.value)
        return Ok(posted)
