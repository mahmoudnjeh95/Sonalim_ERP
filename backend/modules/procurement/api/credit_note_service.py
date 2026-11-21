"""Supplier credit notes (avoirs): corrections to a validated purchase invoice. Validating one takes its
total including tax off what the invoice still has due; a validated credit note is final."""
from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any

import psycopg
from ulid import ULID

from core.atomic import atomic
from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from core.domain.tax import breakdown_payload, vat_breakdown
from core.events.outbox import publish_event
from modules.procurement.domain.purchase_invoice import Line, check_credit_lines, check_line, compute_totals

COLUMNS = ("id, number, invoice_id, partner_id, note_date, reason, status, total_gross, total_discount, total_excl_tax, "
           "total_vat, total_incl_tax, created_at, validated_at")
LINE_COLUMNS = "id, line_no, invoice_line_id, description, quantity, unit_price, discount_rate, vat_rate"
CREDITABLE_STATUSES = ("validated", "partially_paid", "paid")
TWO_PLACES = Decimal("0.01")


def _not_found(note_id: str) -> Err:
    return Err("NOT_FOUND", f"credit note {note_id} not found", f"avoir {note_id} introuvable")


def _to_dict(row: tuple) -> dict[str, Any]:
    keys = ["id", "number", "invoice_id", "partner_id", "note_date", "reason", "status", "total_gross", "total_discount",
            "total_excl_tax", "total_vat", "total_incl_tax", "created_at", "validated_at"]
    return dict(zip(keys, row, strict=True))


def _line_tax_code(line: dict[str, Any], invoice_line: dict[str, Any]) -> str | None:
    return invoice_line.get("tax_code") if Decimal(str(line["vat_rate"])) == Decimal(str(invoice_line["vat_rate"])) else None


def _line_dict(row: tuple) -> dict[str, Any]:
    keys = ["id", "line_no", "invoice_line_id", "description", "quantity", "unit_price", "discount_rate", "vat_rate"]
    line = dict(zip(keys, row, strict=True))
    amounts = Line(line["quantity"], line["unit_price"], line["discount_rate"], line["vat_rate"])
    line["total_excl_tax"] = amounts.net.quantize(TWO_PLACES)
    line["total_vat"] = amounts.vat.quantize(TWO_PLACES)
    line["total_incl_tax"] = (amounts.net + amounts.vat).quantize(TWO_PLACES)
    return line


class PurchaseCreditNoteService:
    """Callers commit; this class only executes writes."""

    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    # ---- reads -------------------------------------------------------------------------------

    def get_credit_note(self, *, tenant_id: str, note_id: str) -> Result[dict[str, Any]]:
        row = self._connection.execute(
            f"SELECT {COLUMNS} FROM procurement.purchase_credit_notes WHERE id = %s AND tenant_id = %s", (note_id, tenant_id)
        ).fetchone()
        if row is None:
            return _not_found(note_id)
        return Ok({**_to_dict(row), "lines": self._lines(tenant_id, note_id)})

    def list_credit_notes(self, *, tenant_id: str, invoice_id: str | None = None) -> list[dict[str, Any]]:
        rows = self._connection.execute(
            f"SELECT {COLUMNS} FROM procurement.purchase_credit_notes WHERE tenant_id = %s AND (%s::text IS NULL OR invoice_id = %s) "
            "ORDER BY note_date DESC, id DESC",
            (tenant_id, invoice_id, invoice_id),
        ).fetchall()
        return [{**_to_dict(r), "lines": self._lines(tenant_id, r[0])} for r in rows]

    # ---- writes ------------------------------------------------------------------------------

    def create_draft(self, *, tenant_id: str, actor_id: str, invoice_id: str, note_date: datetime.date, reason: str,
                     lines: list[dict]) -> Result[dict[str, Any]]:
        invoice = self._creditable_invoice(tenant_id, invoice_id)
        if isinstance(invoice, Err):
            return invoice
        prepared = self._prepare(tenant_id, invoice.value, reason, lines, exclude_note_id=None)
        if isinstance(prepared, Err):
            return prepared
        note_id = str(ULID())
        totals = prepared.value
        self._connection.execute(
            "INSERT INTO procurement.purchase_credit_notes (id, tenant_id, invoice_id, partner_id, note_date, reason, total_gross, "
            "total_discount, total_excl_tax, total_vat, total_incl_tax, created_by) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (note_id, tenant_id, invoice_id, invoice.value["partner_id"], note_date, reason.strip(), totals["totals"].gross,
             totals["totals"].discount, totals["totals"].excl_tax, totals["totals"].vat, totals["totals"].incl_tax, actor_id),
        )
        self._replace_lines(tenant_id, note_id, totals["lines"])
        record_audit(self._connection, tenant_id=tenant_id, actor_id=actor_id, action="purchase_credit_note.created",
                     entity_type="purchase_credit_note", entity_id=note_id,
                     payload={"invoice_id": invoice_id, "amount": str(totals["totals"].incl_tax)})
        return self.get_credit_note(tenant_id=tenant_id, note_id=note_id)

    def update_draft(self, *, tenant_id: str, actor_id: str, note_id: str, changes: dict[str, Any]) -> Result[dict[str, Any]]:
        current = self._lock(tenant_id, note_id)
        if isinstance(current, Err):
            return current
        if current["status"] != "draft":
            return Err("CREDIT_NOTE_NOT_DRAFT", "only a draft credit note can be edited", "seul un avoir brouillon peut être modifié")
        invoice = self._creditable_invoice(tenant_id, current["invoice_id"])
        if isinstance(invoice, Err):
            return invoice
        reason = changes.get("reason", current["reason"])
        lines = changes.get("lines") if changes.get("lines") is not None else self._lines(tenant_id, note_id)
        prepared = self._prepare(tenant_id, invoice.value, reason, lines, exclude_note_id=note_id)
        if isinstance(prepared, Err):
            return prepared
        totals = prepared.value["totals"]
        self._connection.execute(
            "UPDATE procurement.purchase_credit_notes SET note_date = %s, reason = %s, total_gross = %s, total_discount = %s, "
            "total_excl_tax = %s, total_vat = %s, total_incl_tax = %s WHERE id = %s AND tenant_id = %s",
            (changes.get("note_date", current["note_date"]), reason.strip(), totals.gross, totals.discount, totals.excl_tax,
             totals.vat, totals.incl_tax, note_id, tenant_id),
        )
        self._replace_lines(tenant_id, note_id, prepared.value["lines"])
        record_audit(self._connection, tenant_id=tenant_id, actor_id=actor_id, action="purchase_credit_note.updated",
                     entity_type="purchase_credit_note", entity_id=note_id, payload={"amount": str(totals.incl_tax)})
        return self.get_credit_note(tenant_id=tenant_id, note_id=note_id)

    @atomic
    def validate(self, *, tenant_id: str, actor_id: str, note_id: str, correlation_id: str) -> Result[dict[str, Any]]:
        from modules.procurement.api.invoice_service import PurchaseInvoiceService

        current = self._lock(tenant_id, note_id)
        if isinstance(current, Err):
            return current
        if current["status"] != "draft":
            return Err("CREDIT_NOTE_NOT_DRAFT", "only a draft credit note can be validated", "seul un avoir brouillon peut être validé")
        invoices = PurchaseInvoiceService(self._connection)
        locked = invoices._lock(tenant_id, current["invoice_id"])  # serialises credit notes on one invoice
        if isinstance(locked, Err):
            return locked
        invoice = self._creditable_invoice(tenant_id, current["invoice_id"])
        if isinstance(invoice, Err):
            return invoice
        lines = self._lines(tenant_id, note_id)
        # Checked again: another credit note may have been validated on the same lines since this one was drafted.
        rechecked = self._prepare(tenant_id, invoice.value, current["reason"], lines, exclude_note_id=note_id)
        if isinstance(rechecked, Err):
            return rechecked
        applied = invoices.apply_credit(tenant_id=tenant_id, invoice_id=current["invoice_id"], credit=current["total_incl_tax"])
        if isinstance(applied, Err):
            return applied
        number = self._next_number(tenant_id, current["note_date"].year)
        self._connection.execute(
            "UPDATE procurement.purchase_credit_notes SET status = 'validated', number = %s, validated_at = NOW() WHERE id = %s",
            (number, note_id),
        )
        invoice_lines = {line["id"]: line for line in invoices.list_lines(tenant_id=tenant_id, invoice_id=current["invoice_id"])}
        publish_event(
            self._connection, event_type="procurement.purchase_credit_note.validated", producer="procurement",
            tenant_id=tenant_id, correlation_id=correlation_id,
            payload={
                "credit_note_id": note_id,
                "number": number,
                "invoice_id": current["invoice_id"],
                "partner_id": current["partner_id"],
                "amount": str(current["total_incl_tax"]),
                "total_excl_tax": str(current["total_excl_tax"]),
                "total_vat": str(current["total_vat"]),
                "lines": [{"product_id": invoice_lines[line["invoice_line_id"]]["product_id"], "net": str(line["total_excl_tax"])}
                          for line in lines],
                # 1.1 (additive): the VAT per tax code and rate; a line keeps its invoice line's code while it keeps its rate
                "vat_breakdown": breakdown_payload(vat_breakdown(
                    (_line_tax_code(line, invoice_lines[line["invoice_line_id"]]), line["vat_rate"], line["total_excl_tax"])
                    for line in lines)),
                "currency": "XOF",
            },
            event_version="1.1",
        )
        record_audit(self._connection, tenant_id=tenant_id, actor_id=actor_id, action="purchase_credit_note.validated",
                     entity_type="purchase_credit_note", entity_id=note_id,
                     payload={"number": number, "invoice_id": current["invoice_id"], "amount": str(current["total_incl_tax"]),
                              "invoice_status": applied.value["status"]})
        return self.get_credit_note(tenant_id=tenant_id, note_id=note_id)

    def cancel(self, *, tenant_id: str, actor_id: str, note_id: str) -> Result[dict[str, Any]]:
        current = self._lock(tenant_id, note_id)
        if isinstance(current, Err):
            return current
        if current["status"] != "draft":
            return Err("CREDIT_NOTE_NOT_DRAFT", "only a draft credit note can be cancelled; a validated one is final",
                       "seul un avoir brouillon peut être annulé ; un avoir validé est définitif")
        self._connection.execute("UPDATE procurement.purchase_credit_notes SET status = 'cancelled' WHERE id = %s", (note_id,))
        record_audit(self._connection, tenant_id=tenant_id, actor_id=actor_id, action="purchase_credit_note.cancelled",
                     entity_type="purchase_credit_note", entity_id=note_id, payload={"invoice_id": current["invoice_id"]})
        return self.get_credit_note(tenant_id=tenant_id, note_id=note_id)

    # ---- helpers -----------------------------------------------------------------------------

    def _creditable_invoice(self, tenant_id: str, invoice_id: str) -> Result[dict[str, Any]]:
        from modules.procurement.api.invoice_service import PurchaseInvoiceService

        invoice = PurchaseInvoiceService(self._connection).get_invoice(tenant_id=tenant_id, invoice_id=invoice_id)
        if isinstance(invoice, Err):
            return invoice
        if invoice.value["status"] not in CREDITABLE_STATUSES:
            return Err("INVOICE_NOT_VALIDATED", "a credit note applies to a validated purchase invoice",
                       "un avoir s'applique à une facture d'achat validée")
        return invoice

    def _prepare(self, tenant_id: str, invoice: dict[str, Any], reason: str, lines: list[dict],
                 *, exclude_note_id: str | None) -> Result[dict[str, Any]]:
        """Fills each line from the invoice line it corrects (description, price, discount, VAT unless given)
        and checks the caps against what validated credit notes already took off each line."""
        from modules.procurement.api.invoice_service import PurchaseInvoiceService

        if not (reason or "").strip():
            return Err("CREDIT_REASON_REQUIRED", "a credit note needs a reason", "un avoir doit avoir un motif")
        if not lines:
            return Err("LINES_REQUIRED", "a credit note needs at least one line", "un avoir doit avoir au moins une ligne")
        invoice_lines = {l["id"]: l for l in PurchaseInvoiceService(self._connection).list_lines(tenant_id=tenant_id, invoice_id=invoice["id"])}
        prepared = []
        for index, line in enumerate(lines, start=1):
            source = invoice_lines.get(line.get("invoice_line_id"))
            if source is None:
                return Err("CREDIT_LINE_NOT_ON_INVOICE", "a credit note line must refer to a line of its invoice",
                           "une ligne d'avoir doit se rapporter à une ligne de sa facture")

            def pick(key: str, _line: dict = line, _source: dict = source) -> Any:
                return _line.get(key) if _line.get(key) is not None else _source[key]

            values = {
                "line_no": index, "invoice_line_id": source["id"],
                "description": (line.get("description") or source["description"]).strip(),
                "quantity": Decimal(str(line["quantity"])), "unit_price": Decimal(str(pick("unit_price"))),
                "discount_rate": Decimal(str(pick("discount_rate"))), "vat_rate": Decimal(str(pick("vat_rate"))),
            }
            checked = check_line(description=values["description"], product_id=None, quantity=values["quantity"],
                                 unit_price=values["unit_price"], discount_rate=values["discount_rate"], vat_rate=values["vat_rate"])
            if isinstance(checked, Err):
                return checked
            prepared.append(values)
        credited = self._already_credited(tenant_id, invoice["id"], exclude_note_id)
        capped = check_credit_lines(
            {line_id: l["total_excl_tax"] for line_id, l in invoice_lines.items()}, credited,
            [(l["invoice_line_id"], Line(l["quantity"], l["unit_price"], l["discount_rate"], l["vat_rate"]).net) for l in prepared],
        )
        if isinstance(capped, Err):
            return capped
        totals = compute_totals(Line(l["quantity"], l["unit_price"], l["discount_rate"], l["vat_rate"]) for l in prepared)
        if totals.incl_tax <= 0:
            return Err("INVOICE_AMOUNT_ZERO", "a credit note's total must be greater than zero", "le total d'un avoir doit être supérieur à zéro")
        if invoice["credited_amount"] + totals.incl_tax > invoice["total_incl_tax"]:
            left = invoice["total_incl_tax"] - invoice["credited_amount"]
            return Err("CREDIT_EXCEEDS_INVOICE", f"credit notes can take at most {left} off this invoice",
                       f"les avoirs peuvent retirer au plus {left} de cette facture")
        return Ok({"lines": prepared, "totals": totals})

    def _already_credited(self, tenant_id: str, invoice_id: str, exclude_note_id: str | None) -> dict[str, Decimal]:
        rows = self._connection.execute(
            """
            SELECT l.invoice_line_id, l.quantity, l.unit_price, l.discount_rate, l.vat_rate
            FROM procurement.purchase_credit_note_lines l
            JOIN procurement.purchase_credit_notes c ON c.id = l.credit_note_id
            WHERE c.tenant_id = %s AND c.invoice_id = %s AND c.status = 'validated' AND (%s::text IS NULL OR c.id <> %s)
            """,
            (tenant_id, invoice_id, exclude_note_id, exclude_note_id),
        ).fetchall()
        credited: dict[str, Decimal] = {}
        for line_id, quantity, price, discount, vat in rows:
            credited[line_id] = credited.get(line_id, Decimal("0")) + Line(quantity, price, discount, vat).net
        return credited

    def _lines(self, tenant_id: str, note_id: str) -> list[dict[str, Any]]:
        rows = self._connection.execute(
            f"SELECT {LINE_COLUMNS} FROM procurement.purchase_credit_note_lines WHERE credit_note_id = %s AND tenant_id = %s "
            "ORDER BY line_no, id",
            (note_id, tenant_id),
        ).fetchall()
        return [_line_dict(r) for r in rows]

    def _replace_lines(self, tenant_id: str, note_id: str, lines: list[dict[str, Any]]) -> None:
        self._connection.execute("DELETE FROM procurement.purchase_credit_note_lines WHERE credit_note_id = %s", (note_id,))
        for line in lines:
            self._connection.execute(
                "INSERT INTO procurement.purchase_credit_note_lines (id, tenant_id, credit_note_id, invoice_line_id, line_no, "
                "description, quantity, unit_price, discount_rate, vat_rate) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (str(ULID()), tenant_id, note_id, line["invoice_line_id"], line["line_no"], line["description"], line["quantity"],
                 line["unit_price"], line["discount_rate"], line["vat_rate"]),
            )

    def _lock(self, tenant_id: str, note_id: str) -> Result[dict[str, Any]]:
        row = self._connection.execute(
            f"SELECT {COLUMNS} FROM procurement.purchase_credit_notes WHERE id = %s AND tenant_id = %s FOR UPDATE", (note_id, tenant_id)
        ).fetchone()
        if row is None:
            return _not_found(note_id)
        return _to_dict(row)  # type: ignore[return-value]

    def _next_number(self, tenant_id: str, year: int) -> str:
        row = self._connection.execute(
            """
            INSERT INTO procurement.credit_note_counters (tenant_id, year, last_number) VALUES (%s, %s, 1)
            ON CONFLICT (tenant_id, year) DO UPDATE SET last_number = procurement.credit_note_counters.last_number + 1
            RETURNING last_number
            """,
            (tenant_id, year),
        ).fetchone()
        return f"AV-{year}-{row[0]:06d}"
