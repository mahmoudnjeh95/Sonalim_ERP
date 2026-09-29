"""Manual entries (typically in the OD journal): saved as drafts, edited while draft, posted
through the same path as automatic entries, corrected afterwards only by reversal."""
from __future__ import annotations

import datetime

import psycopg

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from modules.finance.api.ledger_posting_service import LedgerPostingService, entry_not_found
from modules.finance.api.ledger_query_service import LedgerQueryService
from modules.finance.api.ledger_sql import STATUS_FR
from modules.finance.domain.ledger import EntryLine


class ManualEntryService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection
        self._posting = LedgerPostingService(connection)
        self._query = LedgerQueryService(connection)

    def create_draft(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        journal_code: str,
        entry_date: datetime.date,
        label: str,
        lines: list[EntryLine],
        reference: str | None = None,
    ) -> Result[dict]:
        inserted = self._posting.insert_draft(
            tenant_id=tenant_id, actor_id=actor_id, journal_code=journal_code, entry_date=entry_date,
            label=label, lines=lines, reference=(reference or "").strip() or None,
        )
        if isinstance(inserted, Err):
            return inserted
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="journal_entry.created",
            entity_type="journal_entry",
            entity_id=inserted.value,
            payload={"journal_code": journal_code, "entry_date": entry_date.isoformat(), "label": label.strip(), "lines": len(lines)},
        )
        return Ok(self._query.get_entry(tenant_id=tenant_id, entry_id=inserted.value))

    def _draft(self, tenant_id: str, entry_id: str) -> Result[tuple]:
        row = self._connection.execute(
            """
            SELECT journal_code, entry_date, label, reference, status, number
            FROM finance.journal_entries WHERE id = %s AND tenant_id = %s FOR UPDATE
            """,
            (entry_id, tenant_id),
        ).fetchone()
        if row is None:
            return entry_not_found(entry_id)
        status, number = row[4], row[5]
        if status != "draft":
            return Err(
                "ENTRY_POSTED",
                f"entry {number} is {status}; a posted entry is never edited or deleted, reverse it instead",
                f"l'écriture {number} est {STATUS_FR[status]} ; une écriture comptabilisée ne se modifie ni ne se supprime, extournez-la",
            )
        return Ok(row)

    def update_draft(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        entry_id: str,
        journal_code: str | None = None,
        entry_date: datetime.date | None = None,
        label: str | None = None,
        reference: str | None = None,
        lines: list[EntryLine] | None = None,
    ) -> Result[dict]:
        """`None` leaves a field unchanged; `reference=""` clears it; `lines` replaces every line."""
        current = self._draft(tenant_id, entry_id)
        if isinstance(current, Err):
            return current
        current_journal, current_date, current_label, current_reference, _, _ = current.value
        new_journal = journal_code or current_journal
        new_date = entry_date or current_date
        new_label = current_label if label is None else label
        new_reference = current_reference if reference is None else (reference.strip() or None)
        new_lines = lines if lines is not None else self._posting.lines_of(entry_id)
        checked = self._posting.check_draft(
            tenant_id=tenant_id, journal_code=new_journal, entry_date=new_date, label=new_label, lines=new_lines
        )
        if isinstance(checked, Err):
            return checked
        self._connection.execute(
            """
            UPDATE finance.journal_entries
            SET journal_code = %s, entry_date = %s, period = %s, label = %s, reference = %s
            WHERE id = %s
            """,
            (new_journal, new_date, new_date.replace(day=1), new_label.strip(), new_reference, entry_id),
        )
        if lines is not None:
            self._posting.replace_lines(tenant_id=tenant_id, entry_id=entry_id, lines=checked.value)
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="journal_entry.updated",
            entity_type="journal_entry",
            entity_id=entry_id,
            payload={
                "journal_code": new_journal,
                "entry_date": new_date.isoformat(),
                "label": new_label.strip(),
                "reference": new_reference,
                "lines_replaced": lines is not None,
            },
        )
        return Ok(self._query.get_entry(tenant_id=tenant_id, entry_id=entry_id))

    def delete_draft(self, *, tenant_id: str, actor_id: str, entry_id: str) -> Result[dict]:
        current = self._draft(tenant_id, entry_id)
        if isinstance(current, Err):
            return current
        journal_code, entry_date, label, reference, status, _ = current.value
        self._connection.execute("DELETE FROM finance.journal_entries WHERE id = %s", (entry_id,))
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="journal_entry.deleted",
            entity_type="journal_entry",
            entity_id=entry_id,
            payload={
                "journal_code": journal_code,
                "entry_date": entry_date.isoformat(),
                "label": label,
                "reference": reference,
                "status": status,
            },
        )
        return Ok({"id": entry_id})

    def post(self, *, tenant_id: str, actor_id: str, entry_id: str, correlation_id: str) -> Result[dict]:
        return self._posting.post_draft(
            tenant_id=tenant_id, actor_id=actor_id, entry_id=entry_id, correlation_id=correlation_id
        )

    def reverse(
        self, *, tenant_id: str, actor_id: str, entry_id: str, entry_date: datetime.date, correlation_id: str
    ) -> Result[dict]:
        return self._posting.reverse_entry(
            tenant_id=tenant_id, actor_id=actor_id, entry_id=entry_id, entry_date=entry_date, correlation_id=correlation_id
        )
