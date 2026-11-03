from __future__ import annotations

import base64
import csv
import datetime
import io
import json
from typing import Any

import psycopg
from openpyxl import load_workbook
from ulid import ULID

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from modules.treasury.api.service import AccountService
from modules.treasury.domain.money import check_currency
from modules.treasury.domain.statement import DEFAULT_PROFILE, dedupe_key, parse_rows, suggest_matches

MAX_BYTES = 5 * 1024 * 1024
LINE_COLUMNS = "id, account_id, line_date, label, debit, credit, balance, partner_id, matched_payment_id, reconciled_at, seq"
LINE_KEYS = ["id", "account_id", "line_date", "label", "debit", "credit", "balance", "partner_id", "matched_payment_id",
             "reconciled_at", "seq"]


def read_rows(filename: str, content: bytes) -> list[list[Any]]:
    """Raw cell rows from an .xlsx or a CSV/TXT export. Anything else is refused by the caller."""
    if filename.lower().endswith((".xlsx", ".xlsm")):
        workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        return [list(row) for row in workbook.worksheets[0].iter_rows(values_only=True)]
    text = content.decode("utf-8-sig", errors="replace")
    delimiter = ";" if text.count(";") > text.count(",") else ("\t" if text.count("\t") > text.count(",") else ",")
    return [row for row in csv.reader(io.StringIO(text), delimiter=delimiter)]


class StatementImportService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    # ---- profiles ---------------------------------------------------------------------------

    def get_profile(self, *, tenant_id: str, account_id: str) -> dict[str, Any]:
        row = self._connection.execute(
            "SELECT profile_json FROM treasury.statement_profiles WHERE account_id = %s AND tenant_id = %s", (account_id, tenant_id)
        ).fetchone()
        return {**DEFAULT_PROFILE, **(row[0] if row else {})}

    def set_profile(self, *, tenant_id: str, actor_id: str, account_id: str, profile: dict[str, Any]) -> Result[dict[str, Any]]:
        account = AccountService(self._connection).get_account(tenant_id=tenant_id, account_id=account_id)
        if isinstance(account, Err):
            return account
        self._connection.execute(
            "INSERT INTO treasury.statement_profiles (account_id, tenant_id, profile_json) VALUES (%s, %s, %s::jsonb) "
            "ON CONFLICT (account_id) DO UPDATE SET profile_json = EXCLUDED.profile_json",
            (account_id, tenant_id, json.dumps(profile)),
        )
        record_audit(self._connection, tenant_id=tenant_id, actor_id=actor_id, action="treasury.statement_profile.saved",
                     entity_type="treasury_account", entity_id=account_id, payload=profile)
        return Ok(self.get_profile(tenant_id=tenant_id, account_id=account_id))

    # ---- import -----------------------------------------------------------------------------

    def import_statement(self, *, tenant_id: str, actor_id: str, account_id: str, filename: str, content_base64: str,
                         commit: bool) -> Result[dict[str, Any]]:
        account = AccountService(self._connection).get_account(tenant_id=tenant_id, account_id=account_id)
        if isinstance(account, Err):
            return account
        if account.value["kind"] != "bank":
            return Err("ACCOUNT_NOT_BANK", "statements can only be imported for a bank account",
                       "un relevé ne peut être importé que pour un compte bancaire")
        in_xof = check_currency(account.value["currency"])
        if isinstance(in_xof, Err):
            return in_xof
        if not filename.lower().endswith((".xlsx", ".xlsm", ".csv", ".txt")):
            return Err("STATEMENT_FORMAT_INVALID", "upload an .xlsx or .csv file", "importez un fichier .xlsx ou .csv")
        try:
            content = base64.b64decode(content_base64, validate=True)
        except ValueError:
            return Err("STATEMENT_FORMAT_INVALID", "the file could not be decoded", "le fichier n'a pas pu être décodé")
        if len(content) > MAX_BYTES:
            return Err("STATEMENT_TOO_LARGE", "the file is larger than 5 MB", "le fichier dépasse 5 Mo")
        try:
            rows = read_rows(filename, content)
        except Exception:  # noqa: BLE001 - a corrupt workbook can raise anything; the user needs one clear message
            return Err("STATEMENT_FORMAT_INVALID", "the file could not be read", "le fichier n'a pas pu être lu")

        parsed = parse_rows(rows, self.get_profile(tenant_id=tenant_id, account_id=account_id))
        existing = {
            (r[0], r[1], r[2], r[3], r[4])
            for r in self._connection.execute(
                "SELECT line_date, label, debit, credit, balance FROM treasury.bank_statement_lines WHERE account_id = %s",
                (account_id,),
            ).fetchall()
        }
        fresh, duplicates = [], []
        for line in parsed.lines:
            (duplicates if dedupe_key(line) in existing else fresh).append(line)

        summary: dict[str, Any] = {
            "errors": parsed.errors,
            "warnings": parsed.warnings,
            "new_lines": [self._line_preview(l) for l in fresh],
            "duplicate_lines": [self._line_preview(l) for l in duplicates],
            "committed": False,
        }
        if not commit:
            return Ok(summary)
        if parsed.errors:
            return Err("STATEMENT_FORMAT_INVALID", f"{len(parsed.errors)} row(s) are invalid; fix the file and retry",
                       f"{len(parsed.errors)} ligne(s) invalide(s) ; corrigez le fichier et réessayez")
        if not fresh:
            return Err("STATEMENT_DUPLICATE_LINE", "every line of this file was already imported",
                       "toutes les lignes de ce fichier ont déjà été importées")

        import_id = str(ULID())
        self._connection.execute(
            "INSERT INTO treasury.statement_imports (id, tenant_id, account_id, filename, imported_by, row_count, skipped_count) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (import_id, tenant_id, account_id, filename, actor_id, len(fresh), len(duplicates)),
        )
        for line in fresh:
            self._connection.execute(
                "INSERT INTO treasury.bank_statement_lines (id, tenant_id, import_id, account_id, seq, line_date, label, debit, credit, balance) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (str(ULID()), tenant_id, import_id, account_id, line.row, line.line_date, line.label, line.debit, line.credit, line.balance),
            )
        record_audit(self._connection, tenant_id=tenant_id, actor_id=actor_id, action="treasury.statement.imported",
                     entity_type="statement_import", entity_id=import_id,
                     payload={"filename": filename, "rows": len(fresh), "skipped": len(duplicates)})
        return Ok({**summary, "committed": True, "import_id": import_id})

    # ---- lines ------------------------------------------------------------------------------

    def list_lines(self, *, tenant_id: str, account_id: str, unmatched_only: bool = False) -> list[dict[str, Any]]:
        clause = " AND matched_payment_id IS NULL" if unmatched_only else ""
        rows = self._connection.execute(
            f"SELECT {LINE_COLUMNS} FROM treasury.bank_statement_lines WHERE tenant_id = %s AND account_id = %s{clause} "
            "ORDER BY line_date, seq",
            (tenant_id, account_id),
        ).fetchall()
        return [dict(zip(LINE_KEYS, r, strict=True)) for r in rows]

    def set_partner(self, *, tenant_id: str, actor_id: str, line_id: str, partner_id: str | None) -> Result[dict[str, Any]]:
        line = self._line(tenant_id, line_id)
        if isinstance(line, Err):
            return line
        if partner_id is not None:
            row = self._connection.execute(
                "SELECT kind FROM core.partners WHERE id = %s AND tenant_id = %s", (partner_id, tenant_id)
            ).fetchone()
            if row is None:
                return Err("NOT_FOUND", f"partner {partner_id} not found", f"partenaire {partner_id} introuvable")
            wanted = ("customer", "both") if line.value["debit"] > 0 else ("supplier", "both")
            if row[0] not in wanted:
                return Err("PARTNER_KIND_MISMATCH", "a debit line takes a customer and a credit line a supplier",
                           "une ligne au débit prend un client et une ligne au crédit un fournisseur")
        self._connection.execute("UPDATE treasury.bank_statement_lines SET partner_id = %s WHERE id = %s", (partner_id, line_id))
        record_audit(self._connection, tenant_id=tenant_id, actor_id=actor_id, action="treasury.statement_line.partner_set",
                     entity_type="statement_line", entity_id=line_id, payload={"partner_id": partner_id})
        return self._line(tenant_id, line_id)

    def match(self, *, tenant_id: str, actor_id: str, line_id: str, payment_id: str | None) -> Result[dict[str, Any]]:
        line = self._line(tenant_id, line_id)
        if isinstance(line, Err):
            return line
        if payment_id is None:
            self._connection.execute(
                "UPDATE treasury.bank_statement_lines SET matched_payment_id = NULL, reconciled_at = NULL WHERE id = %s", (line_id,))
        else:
            candidate = next((p for p in self.candidate_payments(tenant_id=tenant_id, account_id=line.value["account_id"])
                              if p["id"] == payment_id), None)
            if candidate is None:
                return Err("PAYMENT_NOT_MATCHABLE", "this payment is unknown, already matched or not on this account",
                           "ce paiement est inconnu, déjà rapproché ou n'appartient pas à ce compte")
            direction = "in" if line.value["debit"] > 0 else "out"
            amount = line.value["debit"] if direction == "in" else line.value["credit"]
            if candidate["direction"] != direction or candidate["amount"] != amount:
                return Err("MATCH_MISMATCH", "the payment's direction and amount must equal the statement line's",
                           "le sens et le montant du paiement doivent égaler ceux de la ligne de relevé")
            self._connection.execute(
                "UPDATE treasury.bank_statement_lines SET matched_payment_id = %s, reconciled_at = NOW() WHERE id = %s",
                (payment_id, line_id))
        record_audit(self._connection, tenant_id=tenant_id, actor_id=actor_id, action="treasury.statement_line.matched",
                     entity_type="statement_line", entity_id=line_id, payload={"payment_id": payment_id})
        return self._line(tenant_id, line_id)

    def delete_line(self, *, tenant_id: str, actor_id: str, line_id: str) -> Result[None]:
        line = self._line(tenant_id, line_id)
        if isinstance(line, Err):
            return line
        if line.value["matched_payment_id"]:
            return Err("LINE_MATCHED", "unmatch the line before deleting it", "annulez le rapprochement avant de supprimer la ligne")
        self._connection.execute("DELETE FROM treasury.bank_statement_lines WHERE id = %s", (line_id,))
        record_audit(self._connection, tenant_id=tenant_id, actor_id=actor_id, action="treasury.statement_line.deleted",
                     entity_type="statement_line", entity_id=line_id, payload={})
        return Ok(None)

    # ---- reconciliation ---------------------------------------------------------------------

    def candidate_payments(self, *, tenant_id: str, account_id: str) -> list[dict[str, Any]]:
        """Recorded payments that hit this bank account and are not yet tied to a statement line: direct
        payments on the account, and cheques/drafts once collected into it."""
        rows = self._connection.execute(
            """
            SELECT p.id, d.direction, p.amount, d.doc_date, d.number
            FROM treasury.document_payments p JOIN treasury.documents d ON d.id = p.document_id
            WHERE d.tenant_id = %s AND d.status = 'posted' AND p.account_id = %s
              AND NOT EXISTS (SELECT 1 FROM treasury.bank_statement_lines l WHERE l.matched_payment_id = p.id)
            UNION ALL
            SELECT p.id, d.direction, p.amount, i.collected_at::date, d.number
            FROM treasury.instruments i
            JOIN treasury.document_payments p ON p.id = i.payment_id
            JOIN treasury.documents d ON d.id = i.document_id
            WHERE i.tenant_id = %s AND i.status = 'collected' AND i.account_id = %s
              AND NOT EXISTS (SELECT 1 FROM treasury.bank_statement_lines l WHERE l.matched_payment_id = p.id)
            """,
            (tenant_id, account_id, tenant_id, account_id),
        ).fetchall()
        return [{"id": r[0], "direction": r[1], "amount": r[2], "date": r[3], "document_number": r[4]} for r in rows]

    def suggestions(self, *, tenant_id: str, account_id: str) -> dict[str, str]:
        lines = self.list_lines(tenant_id=tenant_id, account_id=account_id, unmatched_only=True)
        return suggest_matches(lines, self.candidate_payments(tenant_id=tenant_id, account_id=account_id))

    def summary(self, *, tenant_id: str, account_id: str) -> Result[dict[str, Any]]:
        account = AccountService(self._connection).get_account(tenant_id=tenant_id, account_id=account_id)
        if isinstance(account, Err):
            return account
        lines = self.list_lines(tenant_id=tenant_id, account_id=account_id)
        with_balance = [l for l in lines if l["balance"] is not None]
        statement_balance = with_balance[-1]["balance"] if with_balance else None
        matched = sum(1 for l in lines if l["matched_payment_id"])
        return Ok({
            "account_balance": account.value["balance"],
            "statement_balance": statement_balance,
            "difference": (statement_balance - account.value["balance"]) if statement_balance is not None else None,
            "lines": len(lines),
            "matched": matched,
            "unmatched": len(lines) - matched,
        })

    # ---- helpers ----------------------------------------------------------------------------

    def _line(self, tenant_id: str, line_id: str) -> Result[dict[str, Any]]:
        row = self._connection.execute(
            f"SELECT {LINE_COLUMNS} FROM treasury.bank_statement_lines WHERE id = %s AND tenant_id = %s", (line_id, tenant_id)
        ).fetchone()
        if row is None:
            return Err("NOT_FOUND", f"statement line {line_id} not found", f"ligne de relevé {line_id} introuvable")
        return Ok(dict(zip(LINE_KEYS, row, strict=True)))

    @staticmethod
    def _line_preview(line) -> dict[str, Any]:
        return {"row": line.row, "line_date": line.line_date, "label": line.label, "debit": line.debit,
                "credit": line.credit, "balance": line.balance}
