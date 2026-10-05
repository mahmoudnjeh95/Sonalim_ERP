"""The single write path of the ledger.

Every entry, manual or automatic, is inserted as a draft and posted through here, so the checks
(journal exists, period open, postable accounts, balanced sides), the entry number, the
`finance.journal_entry.posted` event and the audit row live in one place. `post_entry` checks
everything before it writes anything, so a refusal leaves nothing behind."""
from __future__ import annotations

import datetime
from typing import Iterable

import psycopg
from ulid import ULID

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from core.domain.sequences import next_sequence_value
from core.events.outbox import publish_event
from modules.finance.api.ledger_sql import ENTRY_SELECT, STATUS_FR, entry_dict
from modules.finance.api.period_service import PeriodService
from modules.finance.domain.ledger import (
    Account,
    EntryLine,
    SourceRef,
    build_entry,
    reverse_lines,
    totals,
    validate_lines,
)

SYSTEM_ACTOR = "system:event-consumer"


def entry_not_found(entry_id: str) -> Err:
    return Err("NOT_FOUND", f"journal entry {entry_id} not found", f"écriture {entry_id} introuvable")


class LedgerPostingService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection
        self._periods = PeriodService(connection)

    # Reads the writer needs.

    def load_accounts(self, *, tenant_id: str, codes: Iterable[str]) -> dict[str, Account]:
        rows = self._connection.execute(
            """
            SELECT code, name, class_no, account_type, is_postable, parent_code
            FROM finance.accounts
            WHERE tenant_id = %s AND code = ANY(%s)
            """,
            (tenant_id, sorted(set(codes))),
        ).fetchall()
        return {row[0]: Account(*row) for row in rows}

    def journal_codes(self, *, tenant_id: str) -> set[str]:
        rows = self._connection.execute("SELECT code FROM finance.journals WHERE tenant_id = %s", (tenant_id,)).fetchall()
        return {row[0] for row in rows}

    def get_summary(self, *, tenant_id: str, entry_id: str) -> dict | None:
        row = self._connection.execute(
            f"{ENTRY_SELECT} WHERE e.tenant_id = %s AND e.id = %s", (tenant_id, entry_id)
        ).fetchone()
        return None if row is None else entry_dict(row)

    def find_by_source(self, *, tenant_id: str, source: SourceRef) -> dict | None:
        row = self._connection.execute(
            f"""{ENTRY_SELECT}
            WHERE e.tenant_id = %s AND e.source_module = %s AND e.source_id = %s AND e.source_kind = %s""",
            (tenant_id, source.module, source.id, source.kind),
        ).fetchone()
        return None if row is None else entry_dict(row)

    def lines_of(self, entry_id: str) -> list[EntryLine]:
        rows = self._connection.execute(
            """
            SELECT account_code, debit, credit, label, partner_id, employee_ref
            FROM finance.journal_lines WHERE entry_id = %s ORDER BY line_no
            """,
            (entry_id,),
        ).fetchall()
        return [EntryLine(*row) for row in rows]

    # Checks, without writing.

    def _check_frame(self, *, tenant_id: str, journal_code: str, entry_date: datetime.date) -> Result[datetime.date]:
        if journal_code not in self.journal_codes(tenant_id=tenant_id):
            return Err("NOT_FOUND", f"journal {journal_code} does not exist", f"le journal {journal_code} n'existe pas")
        return self._periods.ensure_open(tenant_id=tenant_id, day=entry_date)

    def check_draft(
        self, *, tenant_id: str, journal_code: str, entry_date: datetime.date, label: str | None, lines: Iterable[EntryLine]
    ) -> Result[list[EntryLine]]:
        """What a draft needs: a label, an existing journal, an open period, valid lines (sides may differ)."""
        if not (label or "").strip():
            return Err("INVALID_ENTRY", "an entry needs a label", "une écriture doit avoir un libellé")
        frame = self._check_frame(tenant_id=tenant_id, journal_code=journal_code, entry_date=entry_date)
        if isinstance(frame, Err):
            return frame
        lines = list(lines)
        return validate_lines(lines, self.load_accounts(tenant_id=tenant_id, codes=[line.account_code for line in lines]))

    def check_postable(
        self, *, tenant_id: str, journal_code: str, entry_date: datetime.date, lines: Iterable[EntryLine]
    ) -> Result[list[EntryLine]]:
        """Everything posting checks: journal, open period, postable accounts, balanced sides."""
        frame = self._check_frame(tenant_id=tenant_id, journal_code=journal_code, entry_date=entry_date)
        if isinstance(frame, Err):
            return frame
        lines = list(lines)
        return build_entry(lines, self.load_accounts(tenant_id=tenant_id, codes=[line.account_code for line in lines]))

    # Writes.

    def insert_draft(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        journal_code: str,
        entry_date: datetime.date,
        label: str,
        lines: Iterable[EntryLine],
        reference: str | None = None,
        source: SourceRef | None = None,
        reversal_of: str | None = None,
    ) -> Result[str]:
        """Writes a draft (no audit row: the caller audits what the user did)."""
        checked = self.check_draft(
            tenant_id=tenant_id, journal_code=journal_code, entry_date=entry_date, label=label, lines=lines
        )
        if isinstance(checked, Err):
            return checked
        entry_id = str(ULID())
        self._connection.execute(
            """
            INSERT INTO finance.journal_entries
                (id, tenant_id, journal_code, entry_date, period, label, reference,
                 source_module, source_id, source_kind, reversal_of, created_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                entry_id, tenant_id, journal_code, entry_date, entry_date.replace(day=1), label.strip(), reference,
                source.module if source else None, source.id if source else None, source.kind if source else None,
                reversal_of, actor_id,
            ),
        )
        self.replace_lines(tenant_id=tenant_id, entry_id=entry_id, lines=checked.value)
        return Ok(entry_id)

    def replace_lines(self, *, tenant_id: str, entry_id: str, lines: list[EntryLine]) -> None:
        self._connection.execute("DELETE FROM finance.journal_lines WHERE entry_id = %s", (entry_id,))
        for line_no, line in enumerate(lines, start=1):
            self._connection.execute(
                """
                INSERT INTO finance.journal_lines
                    (id, tenant_id, entry_id, line_no, account_code, debit, credit, label, partner_id, employee_ref)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    str(ULID()), tenant_id, entry_id, line_no, line.account_code, line.debit, line.credit,
                    line.label, line.partner_id, line.employee_ref,
                ),
            )

    def post_draft(
        self, *, tenant_id: str, actor_id: str, entry_id: str, correlation_id: str, causation_id: str | None = None
    ) -> Result[dict]:
        row = self._connection.execute(
            """
            SELECT journal_code, entry_date, status, number, source_module, source_id
            FROM finance.journal_entries WHERE id = %s AND tenant_id = %s FOR UPDATE
            """,
            (entry_id, tenant_id),
        ).fetchone()
        if row is None:
            return entry_not_found(entry_id)
        journal_code, entry_date, status, number, source_module, source_id = row
        if status != "draft":
            return Err(
                "ENTRY_POSTED",
                f"journal entry {number or entry_id} is already {status}",
                f"l'écriture {number or entry_id} est déjà {STATUS_FR[status]}",
            )
        checked = self.check_postable(
            tenant_id=tenant_id, journal_code=journal_code, entry_date=entry_date, lines=self.lines_of(entry_id)
        )
        if isinstance(checked, Err):
            return checked
        number = next_sequence_value(
            self._connection,
            tenant_id=tenant_id,
            name=f"finance.entry.{journal_code}.{entry_date.year}",
            prefix=f"{journal_code}-{entry_date.year}-",
        )
        self._connection.execute(
            """
            UPDATE finance.journal_entries
            SET status = 'posted', number = %s, posted_by = %s, posted_at = NOW()
            WHERE id = %s
            """,
            (number, actor_id, entry_id),
        )
        publish_event(
            self._connection,
            event_type="finance.journal_entry.posted",
            producer="finance",
            tenant_id=tenant_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
            payload={
                "entry_id": entry_id,
                "journal_code": journal_code,
                "source_module": source_module,
                "source_id": source_id,
            },
        )
        total, _ = totals(checked.value)
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="journal_entry.posted",
            entity_type="journal_entry",
            entity_id=entry_id,
            payload={"number": number, "journal_code": journal_code, "entry_date": entry_date.isoformat(), "total": int(total)},
        )
        return Ok(self.get_summary(tenant_id=tenant_id, entry_id=entry_id))

    def post_entry(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        journal_code: str,
        entry_date: datetime.date,
        label: str,
        lines: Iterable[EntryLine],
        correlation_id: str,
        source: SourceRef | None = None,
        reference: str | None = None,
        reversal_of: str | None = None,
        causation_id: str | None = None,
    ) -> Result[dict]:
        """Insert and post in one go. With a source, a second call returns the entry already posted."""
        if source is not None:
            existing = self.find_by_source(tenant_id=tenant_id, source=source)
            if existing is not None:
                return Ok(existing)
        lines = list(lines)
        checked = self.check_postable(tenant_id=tenant_id, journal_code=journal_code, entry_date=entry_date, lines=lines)
        if isinstance(checked, Err):
            return checked
        inserted = self.insert_draft(
            tenant_id=tenant_id, actor_id=actor_id, journal_code=journal_code, entry_date=entry_date,
            label=label, lines=checked.value, reference=reference, source=source, reversal_of=reversal_of,
        )
        if isinstance(inserted, Err):
            return inserted
        return self.post_draft(
            tenant_id=tenant_id, actor_id=actor_id, entry_id=inserted.value,
            correlation_id=correlation_id, causation_id=causation_id,
        )

    def reverse_entry(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        entry_id: str,
        entry_date: datetime.date,
        correlation_id: str,
        causation_id: str | None = None,
    ) -> Result[dict]:
        """Posts the mirror of a posted entry, dated `entry_date`, and marks the original reversed."""
        row = self._connection.execute(
            """
            SELECT journal_code, number, status, source_module, source_id, source_kind
            FROM finance.journal_entries WHERE id = %s AND tenant_id = %s FOR UPDATE
            """,
            (entry_id, tenant_id),
        ).fetchone()
        if row is None:
            return entry_not_found(entry_id)
        journal_code, number, status, source_module, source_id, source_kind = row
        if status != "posted":
            return Err(
                "INVALID_TRANSITION",
                f"only a posted entry can be reversed; {number or entry_id} is {status}",
                f"seule une écriture comptabilisée peut être extournée ; {number or entry_id} est {STATUS_FR[status]}",
            )
        source = SourceRef(source_module, source_id, f"{source_kind}_reversal") if source_module else None
        posted = self.post_entry(
            tenant_id=tenant_id,
            actor_id=actor_id,
            journal_code=journal_code,
            entry_date=entry_date,
            label=f"Extourne de {number}",
            lines=reverse_lines(self.lines_of(entry_id)),
            correlation_id=correlation_id,
            source=source,
            reference=number,
            reversal_of=entry_id,
            causation_id=causation_id,
        )
        if isinstance(posted, Err):
            return posted
        self._connection.execute("UPDATE finance.journal_entries SET status = 'reversed' WHERE id = %s", (entry_id,))
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="journal_entry.reversed",
            entity_type="journal_entry",
            entity_id=entry_id,
            payload={"number": number, "reversal_entry_id": posted.value["id"], "reversal_number": posted.value["number"]},
        )
        return posted
