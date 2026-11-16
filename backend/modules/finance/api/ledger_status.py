"""The public read other modules' screens use to show whether a document reached the ledger.

A page of documents costs a fixed number of queries whatever its size: entries and open refusals (two),
plus, for treasury, its instruments and the posting switch. Callers pass (source_module, source_id) pairs
and never read finance's tables themselves.
"""
from __future__ import annotations

from typing import Any

import psycopg

from modules.finance.domain.ledger_status import (
    DOCUMENT,
    EntryRow,
    FailureRow,
    LedgerStatus,
    PartStatus,
    derive_document_status,
    derive_status,
    expected_parts,
    instrument_part,
)

# Modules whose posting can be switched off as a whole; their unposted documents read "off" while it is.
_SWITCHABLE = {"treasury"}
MAX_SOURCES = 2000


class LedgerStatusService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def statuses(self, *, tenant_id: str, sources: list[tuple[str, str]]) -> dict[tuple[str, str], LedgerStatus]:
        wanted = list(dict.fromkeys((str(m), str(i)) for m, i in sources))[:MAX_SOURCES]
        if not wanted:
            return {}
        # A treasury document's instruments post under their own id: ask treasury which they are, then read
        # their entries and refusals in the same two queries as the documents'.
        instruments = self._treasury_instruments(tenant_id, [i for m, i in wanted if m == "treasury"])
        keys = wanted + [("treasury", inst["id"]) for listed in instruments.values() for inst in listed]
        entries, failures = self._read(tenant_id, keys)
        off = {module: not self._posting_enabled(tenant_id, module) for module in {m for m, _ in wanted} & _SWITCHABLE}
        result: dict[tuple[str, str], LedgerStatus] = {}
        for key in wanted:
            module, source_id = key
            if module != "treasury":
                result[key] = derive_status(entries.get(key, []), failures.get(key, []), posting_off=off.get(module, False))
                continue
            own = [e for kind, e in entries.get(key, []) if instrument_part(kind) is None]
            own_failures = [f for f in failures.get(key, []) if instrument_part(f.source_kind) is None]
            parts = [PartStatus(DOCUMENT, None, True, derive_status(own, own_failures))]
            for inst in instruments.get(source_id, []):
                expected = expected_parts(inst["status"], inst["has_rejection_fee"])
                inst_entries = entries.get(("treasury", inst["id"]), [])
                inst_failures = failures.get(("treasury", inst["id"]), [])
                for part in ("collection", "unpaid", "rejection_fee"):
                    status = derive_status(
                        [e for kind, e in inst_entries if instrument_part(kind) == part],
                        [f for f in inst_failures if instrument_part(f.source_kind) == part],
                    )
                    parts.append(PartStatus(part, inst["number"], part in expected, status))
            result[key] = derive_document_status(parts, posting_off=off.get(module, False))
        return result

    def _read(self, tenant_id: str, keys: list[tuple[str, str]]):
        modules = [m for m, _ in keys]
        ids = [i for _, i in keys]
        entries: dict[tuple[str, str], list[Any]] = {}
        for module, source_id, kind, entry_id, number, entry_date, status, reversal_of in self._connection.execute(
            """
            SELECT e.source_module, e.source_id, e.source_kind, e.id, e.number, e.entry_date, e.status, e.reversal_of
            FROM finance.journal_entries e
            JOIN unnest(%s::text[], %s::text[]) AS w(module, id) ON w.module = e.source_module AND w.id = e.source_id
            WHERE e.tenant_id = %s
            """,
            (modules, ids, tenant_id),
        ).fetchall():
            row = EntryRow(entry_id, number, entry_date, status, reversal_of)
            entries.setdefault((module, source_id), []).append(row if module != "treasury" else (kind, row))
        failures: dict[tuple[str, str], list[FailureRow]] = {}
        for module, source_id, failure_id, kind, code, message, message_fr in self._connection.execute(
            """
            SELECT f.source_module, f.source_id, f.id, f.source_kind, f.error_code, f.error_message, f.error_message_fr
            FROM finance.posting_failures f
            JOIN unnest(%s::text[], %s::text[]) AS w(module, id) ON w.module = f.source_module AND w.id = f.source_id
            WHERE f.tenant_id = %s AND f.status = 'open'
            """,
            (modules, ids, tenant_id),
        ).fetchall():
            failures.setdefault((module, source_id), []).append(FailureRow(failure_id, kind, code, message, message_fr))
        return entries, failures

    def _treasury_instruments(self, tenant_id: str, document_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
        if not document_ids:
            return {}
        from modules.finance.api.treasury_ledger_service import TREASURY_API_FACTORY

        return TREASURY_API_FACTORY(self._connection).instruments_of_documents(tenant_id=tenant_id, document_ids=document_ids)

    def _posting_enabled(self, tenant_id: str, module: str) -> bool:
        if module == "treasury":
            from modules.finance.api.treasury_ledger_service import ledger_posting_enabled

            return ledger_posting_enabled(self._connection, tenant_id)
        return True


def _entry_dict(entry: EntryRow) -> dict[str, Any]:
    return {"id": entry.id, "number": entry.number, "entry_date": entry.entry_date.isoformat()}


def _failure_dict(failure: FailureRow | None) -> dict[str, Any] | None:
    if failure is None:
        return None
    return {
        "id": failure.id,
        "source_kind": failure.source_kind,
        "code": failure.error_code,
        "message": failure.error_message,
        "message_fr": failure.error_message_fr or failure.error_message,
    }


def status_to_dict(status: LedgerStatus) -> dict[str, Any]:
    return {
        "status": status.status,
        "entries": [_entry_dict(e) for e in status.entries],
        "failure": _failure_dict(status.failure),
        "parts": [
            {
                "part": part.part,
                "instrument_number": part.instrument_number,
                "status": part.status.status,
                "entries": [_entry_dict(e) for e in part.status.entries],
                "failure": _failure_dict(part.status.failure),
            }
            for part in status.parts
        ],
    }
