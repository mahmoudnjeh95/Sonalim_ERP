from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any

import psycopg
from ulid import ULID

from core.atomic import atomic
from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from core.events.outbox import publish_event
from modules.treasury.api.service import AccountMovementService, AccountService, SettingsService
from modules.treasury.domain.instruments import (
    alert_due,
    check_collection_account,
    check_outcome,
    check_rejection_fee,
    split_reduction,
    unpaid_reverses_balance,
)

INSTRUMENT_COLUMNS = (
    "i.id, i.direction, i.method, i.number, i.bank_name, i.due_date, i.amount, i.currency, i.status, "
    "i.document_id, i.account_id, d.partner_id, d.number, i.rejection_fee, i.rejection_fee_account_id, "
    "i.issue_date, i.branch_name, i.deposit_date, i.slip_reference, a.name"
)
INSTRUMENT_KEYS = ["id", "direction", "method", "number", "bank_name", "due_date", "amount", "currency", "status",
                   "document_id", "account_id", "partner_id", "document_number", "rejection_fee", "rejection_fee_account_id",
                   "issue_date", "branch_name", "deposit_date", "slip_reference", "account_name"]
INSTRUMENT_FROM = (
    "treasury.instruments i JOIN treasury.documents d ON d.id = i.document_id "
    "LEFT JOIN treasury.accounts a ON a.id = i.account_id"
)


class InstrumentService:
    """Cheques and drafts after they are recorded: collecting them on a deposit slip, bouncing a
    cheque, and the alerts that tell someone a due date has come. Callers commit."""

    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    # ---- reads ------------------------------------------------------------------------------

    def list_instruments(self, *, tenant_id: str, direction: str | None = None, status: str | None = None,
                         due_to: datetime.date | None = None) -> list[dict[str, Any]]:
        clauses, params = ["i.tenant_id = %s"], [tenant_id]
        for column, value, op in (("i.direction", direction, "="), ("i.status", status, "="), ("i.due_date", due_to, "<=")):
            if value:
                clauses.append(f"{column} {op} %s")
                params.append(value)
        rows = self._connection.execute(
            f"SELECT {INSTRUMENT_COLUMNS} FROM {INSTRUMENT_FROM} "
            f"WHERE {' AND '.join(clauses)} ORDER BY i.due_date, i.id",
            params,
        ).fetchall()
        return [dict(zip(INSTRUMENT_KEYS, r, strict=True)) for r in rows]

    def alerts(self, *, tenant_id: str, today: datetime.date | None = None) -> list[dict[str, Any]]:
        """Pending instruments whose alert window has opened. Computed on demand: the repo has no
        notification channel, so the SPA asks when it loads."""
        today = today or datetime.date.today()
        offsets = {
            (r["direction"], r["method"]): r["offset_days"]
            for r in SettingsService(self._connection).list_alert_rules(tenant_id=tenant_id)
        }
        alerts = []
        for instrument in self.list_instruments(tenant_id=tenant_id, status="pending"):
            offset = offsets.get((instrument["direction"], instrument["method"]))
            if offset is not None and alert_due(instrument["due_date"], offset, today):
                alerts.append({**instrument, "days_overdue": (today - instrument["due_date"]).days})
        return alerts

    def cash_journal(self, *, tenant_id: str, account_id: str, date_from: datetime.date | None = None,
                     date_to: datetime.date | None = None) -> Result[dict[str, Any]]:
        account = AccountService(self._connection).get_account(tenant_id=tenant_id, account_id=account_id)
        if isinstance(account, Err):
            return account
        opening = account.value["opening_balance"]
        if date_from:
            before = self._connection.execute(
                "SELECT COALESCE(SUM(amount), 0) FROM treasury.account_movements WHERE account_id = %s AND occurred_on < %s",
                (account_id, date_from),
            ).fetchone()[0]
            opening = opening + before
        movements = AccountService(self._connection).list_movements(
            tenant_id=tenant_id, account_id=account_id, date_from=date_from, date_to=date_to)
        running = opening
        rows = []
        for m in movements:
            running += m["amount"]
            rows.append({
                "date": m["occurred_on"], "label": m["note"] or m["source_type"], "source_type": m["source_type"],
                "money_in": m["amount"] if m["amount"] > 0 else Decimal("0"),
                "money_out": -m["amount"] if m["amount"] < 0 else Decimal("0"),
                "balance": running,
            })
        return Ok({"account": account.value, "opening_balance": opening, "closing_balance": running, "rows": rows})

    def cash_journal_for_year(self, *, tenant_id: str, year: int, account_id: str | None = None) -> dict[str, Any]:
        """The manual's journal des caisses: one year across every cash register (or one), opening on what
        all of them held on 1 January, each row saying which register moved, its balance and the third party."""
        first_day = datetime.date(year, 1, 1)
        account_clause = " AND a.id = %s" if account_id else ""
        account_params = (account_id,) if account_id else ()
        opening = self._connection.execute(
            f"""
            SELECT COALESCE(SUM(a.opening_balance), 0) + COALESCE((
                SELECT SUM(m.amount) FROM treasury.account_movements m JOIN treasury.accounts a ON a.id = m.account_id
                WHERE m.tenant_id = %s AND a.kind = 'cash' AND m.occurred_on < %s{account_clause}
            ), 0)
            FROM treasury.accounts a WHERE a.tenant_id = %s AND a.kind = 'cash'{account_clause}
            """,
            (tenant_id, first_day, *account_params, tenant_id, *account_params),
        ).fetchone()[0]
        rows = self._connection.execute(
            f"""
            SELECT m.occurred_on, a.id, a.name, m.amount, m.balance_after, m.source_type, m.note,
                   COALESCE(d.number, instrument_doc.number), COALESCE(d.direction, instrument_doc.direction),
                   COALESCE(d.partner_id, instrument_doc.partner_id), p.name
            FROM treasury.account_movements m
            JOIN treasury.accounts a ON a.id = m.account_id
            LEFT JOIN treasury.documents d ON d.id = m.source_id
            LEFT JOIN treasury.instruments i ON i.id = m.source_id
            LEFT JOIN treasury.documents instrument_doc ON instrument_doc.id = i.document_id
            LEFT JOIN core.partners p ON p.id = COALESCE(d.partner_id, instrument_doc.partner_id)
            WHERE m.tenant_id = %s AND a.kind = 'cash' AND m.occurred_on >= %s AND m.occurred_on < %s{account_clause}
            ORDER BY m.occurred_on, m.created_at, m.id
            """,
            (tenant_id, first_day, datetime.date(year + 1, 1, 1), *account_params),
        ).fetchall()
        journal_rows = [
            {
                "date": r[0], "account_id": r[1], "account_name": r[2],
                "money_in": r[3] if r[3] > 0 else Decimal("0"), "money_out": -r[3] if r[3] < 0 else Decimal("0"),
                "balance": r[4], "source_type": r[5], "label": r[7] or r[6] or r[5], "document_number": r[7],
                "direction": r[8], "partner_id": r[9], "partner_name": r[10],
            }
            for r in rows
        ]
        moved = sum((r["money_in"] - r["money_out"] for r in journal_rows), Decimal("0"))
        return {"year": year, "opening_balance": opening, "closing_balance": opening + moved, "rows": journal_rows}

    # ---- writes -----------------------------------------------------------------------------

    @atomic
    def post_slip(self, *, tenant_id: str, actor_id: str, account_id: str | None, slip_date: datetime.date,
                  items: list[dict[str, Any]], correlation_id: str, note: str | None = None) -> Result[dict[str, Any]]:
        """With an account, every item goes on one slip for it. Without one, each payment goes to the
        account named when it was recorded, one slip per account."""
        if not items:
            return Err("NO_ITEMS", "a deposit slip needs at least one instrument", "un bordereau doit comporter au moins un effet")
        if account_id:
            return self._post_one_slip(tenant_id, actor_id, account_id, slip_date, items, correlation_id, note)
        by_account: dict[str, list[dict[str, Any]]] = {}
        for item in items:
            instrument = self._lock(tenant_id, item["instrument_id"])
            if isinstance(instrument, Err):
                return instrument
            if not instrument.value["account_id"]:
                return Err("SLIP_ACCOUNT_REQUIRED", f"{instrument.value['number']} names no account; choose the one it goes to",
                           f"{instrument.value['number']} n'indique aucun compte ; choisissez celui qui le reçoit")
            by_account.setdefault(instrument.value["account_id"], []).append(item)
        slips = []
        for target, grouped in by_account.items():
            slip = self._post_one_slip(tenant_id, actor_id, target, slip_date, grouped, correlation_id, note)
            if isinstance(slip, Err):
                return slip
            slips.append(slip.value)
        return Ok({"slips": slips})

    def _post_one_slip(self, tenant_id: str, actor_id: str, account_id: str, slip_date: datetime.date,
                       items: list[dict[str, Any]], correlation_id: str, note: str | None) -> Result[dict[str, Any]]:
        account = AccountService(self._connection).get_account(tenant_id=tenant_id, account_id=account_id)
        if isinstance(account, Err):
            return account

        slip_id = str(ULID())
        number = self._next_slip_number(tenant_id, slip_date.year)
        self._connection.execute(
            "INSERT INTO treasury.deposit_slips (id, tenant_id, number, account_id, slip_date, note, created_by) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (slip_id, tenant_id, number, account_id, slip_date, note, actor_id),
        )
        seen: set[str] = set()
        for item in items:
            if item["instrument_id"] in seen:
                return Err("DUPLICATE_ITEM", "an instrument can appear only once on a slip", "un effet ne peut figurer qu'une fois sur un bordereau")
            seen.add(item["instrument_id"])
            instrument = self._lock(tenant_id, item["instrument_id"])
            if isinstance(instrument, Err):
                return instrument
            outcome = item["outcome"]
            checked = check_outcome(instrument.value["method"], instrument.value["status"], outcome)
            if isinstance(checked, Err):
                return checked
            if outcome == "collected":
                eligible = check_collection_account(instrument.value["method"], account.value["kind"], account.value["is_active"])
                if isinstance(eligible, Err):
                    return eligible
                if instrument.value["currency"] != account.value["currency"]:
                    return Err("CURRENCY_MISMATCH", "the slip account is in another currency than the instrument",
                               "le compte du bordereau est dans une autre devise que l'effet")
            self._connection.execute(
                "INSERT INTO treasury.deposit_slip_items (slip_id, instrument_id, outcome) VALUES (%s, %s, %s)",
                (slip_id, item["instrument_id"], outcome),
            )
            if outcome == "unpaid":
                applied = self._reject(tenant_id, actor_id, instrument.value, item.get("rejection_fee"),
                                       item.get("rejection_fee_account_id"), slip_date, correlation_id)
            else:
                applied = self._apply(tenant_id, actor_id, instrument.value, outcome, account_id, slip_date, correlation_id)
            if isinstance(applied, Err):
                return applied
            self._connection.execute(
                "UPDATE treasury.instruments SET deposit_date = %s, slip_reference = %s WHERE id = %s",
                (slip_date, number, item["instrument_id"]),
            )
        record_audit(self._connection, tenant_id=tenant_id, actor_id=actor_id, action="treasury.deposit_slip.posted",
                     entity_type="deposit_slip", entity_id=slip_id, payload={"number": number, "items": len(items)})
        return Ok({"id": slip_id, "number": number, "account_id": account_id, "slip_date": slip_date, "items": items})

    @atomic
    def mark_unpaid(self, *, tenant_id: str, actor_id: str, instrument_id: str, correlation_id: str,
                    rejection_fee: Decimal | None = None, rejection_fee_account_id: str | None = None) -> Result[dict[str, Any]]:
        """Bounce a cheque outside a slip, whether or not the bank had already credited it, with what
        the bank charged for the rejection when the user enters it."""
        instrument = self._lock(tenant_id, instrument_id)
        if isinstance(instrument, Err):
            return instrument
        checked = check_outcome(instrument.value["method"], instrument.value["status"], "unpaid")
        if isinstance(checked, Err):
            return checked
        applied = self._reject(tenant_id, actor_id, instrument.value, rejection_fee, rejection_fee_account_id,
                               datetime.date.today(), correlation_id)
        if isinstance(applied, Err):
            return applied
        return self._lock(tenant_id, instrument_id)

    # ---- helpers ----------------------------------------------------------------------------

    def _reject(self, tenant_id: str, actor_id: str, instrument: dict[str, Any], rejection_fee: Decimal | None,
                rejection_fee_account_id: str | None, on: datetime.date, correlation_id: str) -> Result[None]:
        """Mark a cheque unpaid, on a slip or on its own, with what the bank charged when the user enters it."""
        fee = check_rejection_fee(rejection_fee, rejection_fee_account_id, currency=instrument["currency"])
        if isinstance(fee, Err):
            return fee
        if fee.value is not None:
            account = AccountService(self._connection).get_account(tenant_id=tenant_id, account_id=rejection_fee_account_id)
            if isinstance(account, Err):
                return account
            if account.value["kind"] == "mobile_money" or not account.value["is_active"]:
                return Err("ACCOUNT_NOT_ELIGIBLE", "a rejection fee needs an active bank or cash account",
                           "des frais de rejet exigent un compte bancaire ou de caisse actif")
            if account.value["currency"] != instrument["currency"]:
                return Err("CURRENCY_MISMATCH", "the fee account is in another currency than the cheque",
                           "le compte des frais est dans une autre devise que le chèque")
        applied = self._apply(tenant_id, actor_id, instrument, "unpaid", None, on, correlation_id, rejection_fee=fee.value)
        if isinstance(applied, Err):
            return applied
        if fee.value is not None:
            moved = AccountMovementService(self._connection).post(
                tenant_id=tenant_id, actor_id=actor_id, account_id=rejection_fee_account_id, signed_amount=-fee.value,
                source_type="instrument_rejection_fee", source_id=instrument["id"], occurred_on=on,
                note=f"Frais de rejet {instrument['number']}",
            )
            if isinstance(moved, Err):
                return moved
            self._connection.execute(
                "UPDATE treasury.instruments SET rejection_fee = %s, rejection_fee_account_id = %s WHERE id = %s",
                (fee.value, rejection_fee_account_id, instrument["id"]),
            )
        return Ok(None)

    def _lock(self, tenant_id: str, instrument_id: str) -> Result[dict[str, Any]]:
        row = self._connection.execute(
            f"SELECT {INSTRUMENT_COLUMNS} FROM {INSTRUMENT_FROM} "
            "WHERE i.id = %s AND i.tenant_id = %s FOR UPDATE OF i",
            (instrument_id, tenant_id),
        ).fetchone()
        if row is None:
            return Err("NOT_FOUND", f"instrument {instrument_id} not found", f"effet {instrument_id} introuvable")
        return Ok(dict(zip(INSTRUMENT_KEYS, row, strict=True)))

    def _apply(self, tenant_id: str, actor_id: str, instrument: dict[str, Any], outcome: str,
               slip_account_id: str | None, on: datetime.date, correlation_id: str,
               rejection_fee: Decimal | None = None) -> Result[None]:
        movements = AccountMovementService(self._connection)
        sign = Decimal("1") if instrument["direction"] == "in" else Decimal("-1")
        amount: Decimal = instrument["amount"]

        if outcome == "collected":
            moved = movements.post(tenant_id=tenant_id, actor_id=actor_id, account_id=slip_account_id, signed_amount=sign * amount,
                                   source_type="instrument_collected", source_id=instrument["id"], occurred_on=on,
                                   note=instrument["number"])
            if isinstance(moved, Err):
                return moved
            self._connection.execute(
                "UPDATE treasury.instruments SET status = 'collected', account_id = %s, collected_at = NOW() WHERE id = %s",
                (slip_account_id, instrument["id"]),
            )
            publish_event(self._connection, event_type="treasury.instrument.collected", producer="treasury",
                          tenant_id=tenant_id, correlation_id=correlation_id,
                          payload={"instrument_id": instrument["id"], "direction": instrument["direction"],
                                   "method": instrument["method"], "amount": str(amount), "currency": instrument["currency"],
                                   "account_id": slip_account_id})
            return Ok(None)

        # unpaid
        if unpaid_reverses_balance(instrument["status"]):
            moved = movements.post(tenant_id=tenant_id, actor_id=actor_id, account_id=instrument["account_id"],
                                   signed_amount=-sign * amount, source_type="instrument_unpaid", source_id=instrument["id"],
                                   occurred_on=on, note=instrument["number"])
            if isinstance(moved, Err):
                return moved
        allocations = [
            (r[0], r[1], r[2])
            for r in self._connection.execute(
                "SELECT invoice_id, amount, reversed FROM treasury.document_allocations WHERE document_id = %s ORDER BY invoice_id",
                (instrument["document_id"],),
            ).fetchall()
        ]
        reductions = split_reduction(allocations, amount)
        for invoice_id, taken in reductions:
            self._connection.execute(
                "UPDATE treasury.document_allocations SET reversed = reversed + %s WHERE document_id = %s AND invoice_id = %s",
                (taken, instrument["document_id"], invoice_id),
            )
        self._connection.execute("UPDATE treasury.instruments SET status = 'unpaid' WHERE id = %s", (instrument["id"],))
        publish_event(self._connection, event_type="treasury.instrument.unpaid", producer="treasury",
                      tenant_id=tenant_id, correlation_id=correlation_id,
                      payload={"instrument_id": instrument["id"], "direction": instrument["direction"], "amount": str(amount),
                               "currency": instrument["currency"],
                               "rejection_fee": str(rejection_fee) if rejection_fee is not None else None,
                               "allocations": [{"invoice_id": i, "amount": str(a)} for i, a in reductions]})
        record_audit(self._connection, tenant_id=tenant_id, actor_id=actor_id, action="treasury.instrument.unpaid",
                     entity_type="instrument", entity_id=instrument["id"],
                     payload={"number": instrument["number"], "rejection_fee": str(rejection_fee) if rejection_fee is not None else None})
        return Ok(None)

    def _next_slip_number(self, tenant_id: str, year: int) -> str:
        row = self._connection.execute(
            """
            INSERT INTO treasury.document_counters (tenant_id, direction, year, last_number) VALUES (%s, 'slip', %s, 1)
            ON CONFLICT (tenant_id, direction, year)
            DO UPDATE SET last_number = treasury.document_counters.last_number + 1
            RETURNING last_number
            """,
            (tenant_id, year),
        ).fetchone()
        return f"BV-{year}-{row[0]:06d}"
