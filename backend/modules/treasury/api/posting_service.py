from __future__ import annotations

from typing import Any

import psycopg

from core.domain.result import Err, Ok, Result


class TreasuryPostingService:
    """Public read for the ledger. When finance posts treasury activity to the general ledger it asks
    for plain dicts here and never reads treasury tables itself. Nothing is written."""

    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def ledger_posting_enabled(self, *, tenant_id: str) -> bool:
        """The switch that lets finance post treasury activity; off until the accountant confirms the accounts."""
        row = self._connection.execute(
            "SELECT value_json FROM treasury.settings WHERE tenant_id = %s AND key = 'ledger_posting_enabled'", (tenant_id,)
        ).fetchone()
        return row is not None and row[0] is True

    def account_ledger_code(self, *, tenant_id: str, account_id: str | None) -> str | None:
        if account_id is None:
            return None
        row = self._connection.execute(
            "SELECT ledger_account_code FROM treasury.accounts WHERE id = %s AND tenant_id = %s", (account_id, tenant_id)
        ).fetchone()
        return row[0] if row else None

    def account_kind(self, *, tenant_id: str, account_id: str | None) -> str | None:
        if account_id is None:
            return None
        row = self._connection.execute(
            "SELECT kind FROM treasury.accounts WHERE id = %s AND tenant_id = %s", (account_id, tenant_id)
        ).fetchone()
        return row[0] if row else None

    def accounts_for_opening(self, *, tenant_id: str, account_id: str | None = None) -> list[dict[str, Any]]:
        """Every account (or one) with what the ledger needs to bring its balance in: the current balance,
        which is the opening balance until the account moves."""
        rows = self._connection.execute(
            "SELECT id, kind, name, currency, ledger_account_code, balance FROM treasury.accounts "
            "WHERE tenant_id = %s AND (%s::text IS NULL OR id = %s) ORDER BY created_at, id",
            (tenant_id, account_id, account_id),
        ).fetchall()
        keys = ["id", "kind", "name", "currency", "ledger_account_code", "balance"]
        return [dict(zip(keys, row, strict=True)) for row in rows]

    def document_lines(self, *, tenant_id: str, document_id: str) -> Result[dict[str, Any]]:
        """A posted receipt or disbursement: one line per payment with the ledger code of the account it
        moved, plus the part not tied to any invoice (an advance), which the ledger books differently. A
        payment waiting on the deposit slip has moved no account yet, so it reads like a cheque: no account."""
        head = self._connection.execute(
            "SELECT direction, number, partner_id, doc_date, currency, status, unallocated, withheld_amount "
            "FROM treasury.documents WHERE id = %s AND tenant_id = %s",
            (document_id, tenant_id),
        ).fetchone()
        if head is None:
            return Err("NOT_FOUND", f"document {document_id} not found", f"document {document_id} introuvable")
        payments = self._connection.execute(
            """
            SELECT p.id, p.method, p.amount, CASE WHEN i.id IS NULL THEN p.account_id END,
                   CASE WHEN i.id IS NULL THEN a.ledger_account_code END, a.kind
            FROM treasury.document_payments p
            LEFT JOIN treasury.accounts a ON a.id = p.account_id
            LEFT JOIN treasury.instruments i ON i.payment_id = p.id
            WHERE p.document_id = %s ORDER BY p.id
            """,
            (document_id,),
        ).fetchall()
        keys = ["payment_id", "method", "amount", "account_id", "ledger_account_code", "account_kind"]
        return Ok({
            "direction": head[0], "number": head[1], "partner_id": head[2], "date": head[3], "currency": head[4],
            "status": head[5], "unallocated": head[6], "withheld": head[7],
            "payments": [dict(zip(keys, p, strict=True)) for p in payments],
        })

    def instrument_lines(self, *, tenant_id: str, instrument_id: str) -> Result[dict[str, Any]]:
        row = self._connection.execute(
            """
            SELECT i.direction, i.method, i.number, i.amount, i.currency, i.status, i.account_id, a.ledger_account_code,
                   d.partner_id, d.number, i.rejection_fee, f.ledger_account_code
            FROM treasury.instruments i
            JOIN treasury.documents d ON d.id = i.document_id
            LEFT JOIN treasury.accounts a ON a.id = i.account_id
            LEFT JOIN treasury.accounts f ON f.id = i.rejection_fee_account_id
            WHERE i.id = %s AND i.tenant_id = %s
            """,
            (instrument_id, tenant_id),
        ).fetchone()
        if row is None:
            return Err("NOT_FOUND", f"instrument {instrument_id} not found", f"effet {instrument_id} introuvable")
        keys = ["direction", "method", "number", "amount", "currency", "status", "account_id", "ledger_account_code",
                "partner_id", "document_number", "rejection_fee", "rejection_fee_ledger_code"]
        return Ok(dict(zip(keys, row, strict=True)))
