"""Customer receivables: what each customer owes and how late, how much more credit it may take, and its
statement. Finance owns invoices, credit notes and the payments treasury reports against them; orders not yet
invoiced are read through sales' public api."""
from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any

import psycopg

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from core.payment_terms import PaymentTermService
from modules.finance.api.payment_schedule import installments_of
from modules.finance.domain.receivables import BUCKETS, bucket_for, credit_check, invoice_position, level_reached

OPEN_STATUSES = ("issued", "partially_paid")
OVERRIDE_PERMISSION = "finance.admin_credit_override"
# The company details are what every dunning letter prints in its header; an empty one is left off.
COMPANY_KEYS = ("company_name", "company_address", "company_phone", "company_email", "company_tax_id", "company_rccm",
                "signatory", "signatory_title")
_SETTINGS_KEYS = ("block_overdue_days", "warn_ratio", "chase_from", *COMPANY_KEYS)


def _today() -> datetime.date:
    return datetime.date.today()


def is_chased(invoice: dict[str, Any], chase_from: datetime.date | None) -> bool:
    """Whether an invoice's lateness counts for dunning and the credit hold. Installments that fell due before
    the tenant's chasing start date are left out: at go-live, invoices paid before treasury existed still look
    unpaid until someone records those payments, and must not put every customer on hold. They stay in the
    aged balance and the statement."""
    return bool(invoice["overdue"]) and (chase_from is None or (invoice["oldest_due"] is not None and invoice["oldest_due"] >= chase_from))


class ReceivablesService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    # ---- settings ------------------------------------------------------------------------------

    def settings(self, *, tenant_id: str) -> dict[str, Any]:
        row = self._connection.execute(
            f"SELECT {', '.join(_SETTINGS_KEYS)} FROM finance.receivables_settings WHERE tenant_id = %s", (tenant_id,)).fetchone()
        if row is None:
            return {"block_overdue_days": None, "warn_ratio": Decimal("0.90"), "chase_from": None, **{key: None for key in COMPANY_KEYS}}
        return dict(zip(_SETTINGS_KEYS, row))

    def update_settings(self, *, tenant_id: str, actor_id: str, changes: dict[str, Any]) -> Result[dict[str, Any]]:
        values = {**self.settings(tenant_id=tenant_id), **{k: v for k, v in changes.items() if k in _SETTINGS_KEYS}}
        for key in COMPANY_KEYS:
            values[key] = (values[key] or "").strip() or None
        days = values["block_overdue_days"]
        if days is not None and int(days) < 0:
            return Err("INVALID_SETTING", "the overdue delay is 0 days or more", "le délai de retard est de 0 jour ou plus")
        ratio = Decimal(str(values["warn_ratio"]))
        if not Decimal("0") < ratio <= Decimal("1"):
            return Err("INVALID_SETTING", "the warning share is above 0 and at most 1", "la part d'alerte est supérieure à 0 et au plus 1")
        values["warn_ratio"] = ratio
        self._connection.execute(
            f"""
            INSERT INTO finance.receivables_settings (tenant_id, {', '.join(_SETTINGS_KEYS)}, updated_by, updated_at)
            VALUES (%s, {', '.join(['%s'] * len(_SETTINGS_KEYS))}, %s, NOW())
            ON CONFLICT (tenant_id) DO UPDATE SET {', '.join(f'{k} = EXCLUDED.{k}' for k in _SETTINGS_KEYS)},
                updated_by = EXCLUDED.updated_by, updated_at = NOW()
            """,
            (tenant_id, *[values[k] for k in _SETTINGS_KEYS], actor_id),
        )
        record_audit(self._connection, tenant_id=tenant_id, actor_id=actor_id, action="receivables_settings.updated",
                     entity_type="receivables_settings", entity_id=tenant_id,
                     payload={k: str(v) if v is not None else None for k, v in values.items()})
        return Ok(self.settings(tenant_id=tenant_id))

    # ---- credit limit ----------------------------------------------------------------------------

    def credit_limit(self, *, tenant_id: str, partner_id: str) -> Decimal | None:
        row = self._connection.execute(
            "SELECT credit_limit FROM finance.customer_credit WHERE tenant_id = %s AND partner_id = %s", (tenant_id, partner_id)).fetchone()
        return row[0] if row else None

    def set_credit_limit(self, *, tenant_id: str, actor_id: str, partner_id: str, credit_limit: Decimal | None,
                         note: str | None = None) -> Result[dict[str, Any]]:
        if credit_limit is not None and Decimal(str(credit_limit)) < 0:
            return Err("INVALID_CREDIT_LIMIT", "a credit limit is 0 or more", "une limite de crédit est de 0 ou plus")
        if not self._connection.execute("SELECT 1 FROM core.partners WHERE tenant_id = %s AND id = %s", (tenant_id, partner_id)).fetchone():
            return Err("NOT_FOUND", f"partner {partner_id} not found", f"partenaire {partner_id} introuvable")
        before = self.credit_limit(tenant_id=tenant_id, partner_id=partner_id)
        self._connection.execute(
            """
            INSERT INTO finance.customer_credit (tenant_id, partner_id, credit_limit, note, updated_by, updated_at)
            VALUES (%s, %s, %s, %s, %s, NOW())
            ON CONFLICT (tenant_id, partner_id) DO UPDATE SET credit_limit = EXCLUDED.credit_limit, note = EXCLUDED.note,
                updated_by = EXCLUDED.updated_by, updated_at = NOW()
            """,
            (tenant_id, partner_id, credit_limit, note, actor_id),
        )
        record_audit(self._connection, tenant_id=tenant_id, actor_id=actor_id, action="customer.credit_limit_set", entity_type="partner",
                     entity_id=partner_id, payload={"from": str(before) if before is not None else None,
                                                    "to": str(credit_limit) if credit_limit is not None else None, "note": note})
        return Ok(self.position(tenant_id=tenant_id, partner_id=partner_id))

    # ---- positions ---------------------------------------------------------------------------------

    def _open_invoices(self, tenant_id: str, partner_id: str | None, today: datetime.date) -> list[dict[str, Any]]:
        clauses, params = ["tenant_id = %s", "status = ANY(%s)"], [tenant_id, list(OPEN_STATUSES)]
        if partner_id is not None:
            clauses.append("partner_id = %s")
            params.append(partner_id)
        rows = self._connection.execute(
            f"""
            SELECT id, partner_id, number, COALESCE(invoice_date, created_at::date), due_date, amount, amount_credited, amount_paid, status
            FROM finance.invoices WHERE {' AND '.join(clauses)} ORDER BY COALESCE(invoice_date, created_at::date), id
            """,
            params,
        ).fetchall()
        schedules = installments_of(self._connection, [r[0] for r in rows])
        invoices = []
        for invoice_id, partner, number, invoice_date, due_date, total, credited, paid, status in rows:
            installments = schedules.get(invoice_id) or [(due_date or invoice_date, Decimal(str(total)))]
            position = invoice_position(total=Decimal(str(total)), credited=Decimal(str(credited)), paid=Decimal(str(paid)),
                                        installments=installments, today=today)
            if position.remaining <= 0:
                continue
            invoices.append({
                "id": invoice_id, "partner_id": partner, "number": number, "invoice_date": invoice_date, "due_date": due_date,
                "total": Decimal(str(total)) - Decimal(str(credited)), "paid": Decimal(str(paid)), "remaining": position.remaining,
                "overdue": position.overdue, "oldest_due": position.oldest_due, "days_overdue": position.days_overdue,
                "next_due": position.next_due, "bucket": bucket_for(position.days_overdue) if position.overdue else "not_due",
                "status": status,
            })
        return invoices

    def _uninvoiced(self, tenant_id: str, partner_id: str) -> tuple[Decimal, Decimal]:
        """(delivered but not issued: draft invoices, confirmed orders not yet delivered)."""
        from modules.sales.api.service import SalesOrderService

        drafts = self._connection.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM finance.invoices WHERE tenant_id = %s AND partner_id = %s AND status = 'draft'",
            (tenant_id, partner_id),
        ).fetchone()[0]
        undelivered = Decimal("0")
        for order in SalesOrderService(self._connection).list_orders(tenant_id, status="confirmed"):
            if order.partner_id != partner_id:
                continue
            invoiced = self._connection.execute(
                "SELECT COALESCE(SUM(amount), 0) FROM finance.invoices WHERE tenant_id = %s AND source_order_id = %s",
                (tenant_id, order.id),
            ).fetchone()[0]
            undelivered += max(Decimal(str(order.total_amount)) - Decimal(str(invoiced)), Decimal("0"))
        return Decimal(str(drafts)), undelivered.quantize(Decimal("1"))

    def position(self, *, tenant_id: str, partner_id: str, today: datetime.date | None = None) -> dict[str, Any]:
        """Everything credit control needs about one customer."""
        from modules.finance.api.dunning_service import DunningService

        today = today or _today()
        invoices = self._open_invoices(tenant_id, partner_id, today)
        drafts, undelivered = self._uninvoiced(tenant_id, partner_id)
        open_amount = sum((i["remaining"] for i in invoices), Decimal("0"))
        overdue = sum((i["overdue"] for i in invoices), Decimal("0"))
        max_days = max((i["days_overdue"] for i in invoices if i["overdue"]), default=0)
        chase_from = self.settings(tenant_id=tenant_id)["chase_from"]
        chased_days = max((i["days_overdue"] for i in invoices if is_chased(i, chase_from)), default=0)
        limit = self.credit_limit(tenant_id=tenant_id, partner_id=partner_id)
        exposure = open_amount + drafts + undelivered
        levels = DunningService(self._connection).levels(tenant_id=tenant_id)
        reached = level_reached(levels, chased_days) if chased_days else None
        buckets = {key: Decimal("0") for key, _, _ in BUCKETS}
        for invoice in invoices:
            # The late part ages by its own lateness; the part not yet due sits in "not_due".
            if invoice["overdue"]:
                buckets[invoice["bucket"]] += invoice["overdue"]
            buckets["not_due"] += invoice["remaining"] - invoice["overdue"]
        terms = PaymentTermService(self._connection).partner_terms(tenant_id=tenant_id, partner_id=partner_id)
        return {
            "partner_id": partner_id, "credit_limit": limit, "open_invoices": open_amount, "uninvoiced_deliveries": drafts,
            "undelivered_orders": undelivered, "exposure": exposure,
            "available": (limit - exposure) if limit is not None else None,
            "overdue": overdue, "max_days_overdue": max_days, "chased_days_overdue": chased_days, "buckets": buckets,
            "dunning_level": reached, "blocked": bool(reached and reached["blocks_orders"]),
            "customer_term": terms["customer"], "supplier_term": terms["supplier"],
            "invoices": invoices,
        }

    def aging(self, *, tenant_id: str, today: datetime.date | None = None) -> list[dict[str, Any]]:
        """The aged balance by customer, by lateness of each installment rather than by invoice date."""
        today = today or _today()
        rows: dict[str, dict[str, Any]] = {}
        for invoice in self._open_invoices(tenant_id, None, today):
            row = rows.setdefault(invoice["partner_id"], {
                "partner_id": invoice["partner_id"], "remaining": Decimal("0"), "overdue": Decimal("0"), "max_days_overdue": 0,
                "invoices": 0, **{f"bucket_{key}": Decimal("0") for key, _, _ in BUCKETS}})
            row["remaining"] += invoice["remaining"]
            row["overdue"] += invoice["overdue"]
            row["invoices"] += 1
            row["max_days_overdue"] = max(row["max_days_overdue"], invoice["days_overdue"])
            if invoice["overdue"]:
                row[f"bucket_{invoice['bucket']}"] += invoice["overdue"]
            row["bucket_not_due"] += invoice["remaining"] - invoice["overdue"]
        names = self._partner_names(tenant_id, list(rows))
        limits = dict(self._connection.execute(
            "SELECT partner_id, credit_limit FROM finance.customer_credit WHERE tenant_id = %s", (tenant_id,)).fetchall())
        result = []
        for partner_id, row in rows.items():
            result.append({**row, "partner_name": names.get(partner_id), "credit_limit": limits.get(partner_id)})
        return sorted(result, key=lambda r: (-r["overdue"], -r["remaining"]))

    def _partner_names(self, tenant_id: str, partner_ids: list[str]) -> dict[str, str]:
        if not partner_ids:
            return {}
        return dict(self._connection.execute(
            "SELECT id, name FROM core.partners WHERE tenant_id = %s AND id = ANY(%s)", (tenant_id, partner_ids)).fetchall())

    # ---- credit control at order confirmation ------------------------------------------------------

    def credit_preview(self, *, tenant_id: str, partner_id: str, order_amount: Decimal,
                       today: datetime.date | None = None) -> dict[str, Any]:
        """What confirming an order of `order_amount` would meet, without confirming anything."""
        position = self.position(tenant_id=tenant_id, partner_id=partner_id, today=today)
        settings = self.settings(tenant_id=tenant_id)
        check = credit_check(
            credit_limit=position["credit_limit"], exposure=position["exposure"], order_amount=Decimal(str(order_amount)),
            max_days_overdue=position["chased_days_overdue"], block_overdue_days=settings["block_overdue_days"],
            blocking_level=position["dunning_level"] if position["blocked"] else None, warn_ratio=Decimal(str(settings["warn_ratio"])),
        )
        return {
            "exposure": position["exposure"], "credit_limit": position["credit_limit"], "available": position["available"],
            "overdue": position["overdue"], "max_days_overdue": position["max_days_overdue"],
            "dunning_level": position["dunning_level"], "order_amount": Decimal(str(order_amount)),
            "warnings": [{"code": c, "message": en, "message_fr": fr} for c, en, fr in check.warnings],
            "blocking": [{"code": c, "message": en, "message_fr": fr} for c, en, fr in check.blocking],
            "overridden": False,
        }

    def check_order_credit(self, *, tenant_id: str, actor_id: str, partner_id: str, order_id: str, order_amount: Decimal,
                           override: bool = False, today: datetime.date | None = None) -> Result[dict[str, Any]]:
        """Called by sales when an order is confirmed: the answer is needed before it can go on, so it is a
        synchronous call, like the stock check. Refused when the order would take the customer over its limit,
        when an invoice is later than the tenant allows, or when dunning put the account on hold; a user holding
        finance.admin_credit_override who asks to override goes through, and that is audited."""
        answer = self.credit_preview(tenant_id=tenant_id, partner_id=partner_id, order_amount=order_amount, today=today)
        if answer["blocking"]:
            if not override:
                return Err("CREDIT_BLOCKED", "; ".join(b["message"] for b in answer["blocking"]),
                           "; ".join(b["message_fr"] for b in answer["blocking"]))
            answer["overridden"] = True
            record_audit(self._connection, tenant_id=tenant_id, actor_id=actor_id, action="customer.credit_override_used",
                         entity_type="partner", entity_id=partner_id,
                         payload={"order_id": order_id, "order_amount": str(order_amount), "reasons": [b["code"] for b in answer["blocking"]]})
        return Ok(answer)

    # ---- statement -----------------------------------------------------------------------------------

    def statement(self, *, tenant_id: str, partner_id: str, date_from: datetime.date | None = None,
                  date_to: datetime.date | None = None, today: datetime.date | None = None) -> dict[str, Any]:
        """The customer's account: issued invoices (debit), credit notes and payments (credit), oldest first,
        with a running balance from the opening balance at `date_from`."""
        today = today or _today()
        entries: list[dict[str, Any]] = []
        for invoice_id, number, day, due, total in self._connection.execute(
            """
            SELECT id, number, COALESCE(invoice_date, created_at::date), due_date, amount FROM finance.invoices
            WHERE tenant_id = %s AND partner_id = %s AND status <> 'draft'
            """,
            (tenant_id, partner_id),
        ).fetchall():
            entries.append({"date": day, "kind": "invoice", "reference": number or invoice_id, "due_date": due,
                            "debit": Decimal(str(total)), "credit": Decimal("0"), "invoice_id": invoice_id})
        for number, day, amount, invoice_number in self._connection.execute(
            """
            SELECT c.number, c.credit_date, c.amount, i.number FROM finance.credit_notes c JOIN finance.invoices i ON i.id = c.invoice_id
            WHERE c.tenant_id = %s AND c.partner_id = %s
            """,
            (tenant_id, partner_id),
        ).fetchall():
            entries.append({"date": day, "kind": "credit_note", "reference": number, "due_date": None, "debit": Decimal("0"),
                            "credit": Decimal(str(amount)), "against": invoice_number})
        documents: dict[str, dict[str, Any] | None] = {}
        for document_id, amount, applied_at, invoice_number in self._connection.execute(
            """
            SELECT d.document_id, d.amount, d.applied_at, i.number FROM finance.invoice_payment_deltas d
            JOIN finance.invoices i ON i.id = d.invoice_id WHERE i.tenant_id = %s AND i.partner_id = %s
            """,
            (tenant_id, partner_id),
        ).fetchall():
            if document_id not in documents:
                documents[document_id] = self._treasury_document(tenant_id, document_id)
            document = documents[document_id]
            amount = Decimal(str(amount))
            entries.append({
                "date": (document or {}).get("date") or applied_at.date(),
                "kind": "payment" if amount > 0 else "payment_reversed",
                "reference": (document or {}).get("number") or document_id, "due_date": None, "against": invoice_number,
                "debit": -amount if amount < 0 else Decimal("0"), "credit": amount if amount > 0 else Decimal("0"),
            })
        order = {"invoice": 0, "credit_note": 1, "payment": 2, "payment_reversed": 3}
        entries.sort(key=lambda e: (e["date"], order[e["kind"]], str(e["reference"])))
        opening = Decimal("0")
        lines = []
        balance = Decimal("0")
        for entry in entries:
            if date_from and entry["date"] < date_from:
                opening += entry["debit"] - entry["credit"]
                continue
            if date_to and entry["date"] > date_to:
                continue
            if not lines:
                balance = opening
            balance += entry["debit"] - entry["credit"]
            lines.append({**entry, "balance": balance})
        position = self.position(tenant_id=tenant_id, partner_id=partner_id, today=today)
        from modules.finance.api.dunning_service import DunningService

        return {
            "partner_id": partner_id, "partner_name": self._partner_names(tenant_id, [partner_id]).get(partner_id),
            "date_from": date_from, "date_to": date_to, "opening_balance": opening,
            "closing_balance": lines[-1]["balance"] if lines else opening, "lines": lines,
            "position": {k: v for k, v in position.items() if k != "invoices"}, "open_invoices": position["invoices"],
            "dunning_history": DunningService(self._connection).history(tenant_id=tenant_id, partner_id=partner_id),
        }

    def _treasury_document(self, tenant_id: str, document_id: str) -> dict[str, Any] | None:
        try:
            from modules.treasury.api.posting_service import TreasuryPostingService
        except ImportError:  # treasury is an optional dependency
            return None
        found = TreasuryPostingService(self._connection).document_lines(tenant_id=tenant_id, document_id=document_id)
        return None if isinstance(found, Err) else {"number": found.value["number"], "date": found.value["date"]}
