"""Quotes (devis): priced from the customer's price list, sent, accepted or refused, expired when their
validity date passes, revised under the same number, and turned into an order at the quoted prices."""
from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any

import psycopg
from ulid import ULID

from core.atomic import atomic
from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from core.tax_codes import resolve_lines
from modules.sales.api.pricing_service import PricingService
from modules.sales.domain.entities import OrderLine
from modules.sales.domain.pricing import (
    OPEN_QUOTE_STATUSES,
    PricedLine,
    check_discount_limit,
    check_line,
    check_quote_transition,
    check_rate,
    compute_totals,
    conversion_rate,
    display_number,
)

QUOTE_PREFIX = "DV"
SYSTEM_ACTOR = "system:quote-expiry"
_QUOTE_COLUMNS = (
    "id, number, revision, previous_id, partner_id, opportunity_id, location_id, quote_date, valid_until, status, "
    "discount_rate, note, refusal_reason, order_id, created_by, created_at"
)
_QUOTE_KEYS = (
    "id", "number", "revision", "previous_id", "partner_id", "opportunity_id", "location_id", "quote_date", "valid_until",
    "status", "discount_rate", "note", "refusal_reason", "order_id", "created_by", "created_at",
)


def _next_number(connection: psycopg.Connection, tenant_id: str, year: int) -> str:
    row = connection.execute(
        """
        INSERT INTO sales.document_counters (tenant_id, kind, year, last_number) VALUES (%s, %s, %s, 1)
        ON CONFLICT (tenant_id, kind, year) DO UPDATE SET last_number = sales.document_counters.last_number + 1
        RETURNING last_number
        """,
        (tenant_id, QUOTE_PREFIX, year),
    ).fetchone()
    return f"{QUOTE_PREFIX}-{year}-{row[0]:06d}"


class QuoteService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection
        self._pricing = PricingService(connection)

    # ---- reads --------------------------------------------------------------------------------

    def expire_due(self, *, tenant_id: str, today: datetime.date | None = None) -> int:
        """Quotes still open after their validity date become expired. Run on every read, so nobody
        sees an out-of-date offer as open; idempotent."""
        today = today or datetime.date.today()
        rows = self._connection.execute(
            "UPDATE sales.quotes SET status = 'expired' WHERE tenant_id = %s AND status = ANY(%s) AND valid_until < %s RETURNING id",
            (tenant_id, list(OPEN_QUOTE_STATUSES), today),
        ).fetchall()
        for (quote_id,) in rows:
            record_audit(self._connection, tenant_id=tenant_id, actor_id=SYSTEM_ACTOR, action="quote.status_changed",
                         entity_type="quote", entity_id=quote_id, payload={"to_status": "expired", "reason": "validity date passed"})
        return len(rows)

    def get_quote(self, *, tenant_id: str, quote_id: str) -> Result[dict[str, Any]]:
        self.expire_due(tenant_id=tenant_id)
        row = self._connection.execute(
            f"SELECT {_QUOTE_COLUMNS} FROM sales.quotes WHERE tenant_id = %s AND id = %s", (tenant_id, quote_id)
        ).fetchone()
        if row is None:
            return Err("NOT_FOUND", f"quote {quote_id} not found", f"devis {quote_id} introuvable")
        return Ok(self._with_lines(dict(zip(_QUOTE_KEYS, row))))

    def _with_lines(self, quote: dict[str, Any]) -> dict[str, Any]:
        rows = self._connection.execute(
            """
            SELECT l.id, l.line_no, l.product_id, p.sku, p.name, l.quantity, l.unit_price, l.discount_rate, l.vat_rate, l.price_list_id,
                   l.tax_code
            FROM sales.quote_lines l JOIN core.products p ON p.id = l.product_id
            WHERE l.quote_id = %s ORDER BY l.line_no
            """,
            (quote["id"],),
        ).fetchall()
        document_discount = Decimal(str(quote["discount_rate"]))
        lines = []
        for r in rows:
            priced = PricedLine(Decimal(str(r[5])), Decimal(str(r[6])), Decimal(str(r[7])), Decimal(str(r[8])))
            lines.append({"id": r[0], "line_no": r[1], "product_id": r[2], "sku": r[3], "product_name": r[4], "quantity": r[5],
                          "unit_price": r[6], "discount_rate": r[7], "vat_rate": r[8], "price_list_id": r[9], "tax_code": r[10],
                          # after the line discount only: the document discount shows once, in the totals
                          "net_amount": priced.net().quantize(Decimal("0.01"))})
        totals = compute_totals((PricedLine(Decimal(str(l["quantity"])), Decimal(str(l["unit_price"])),
                                            Decimal(str(l["discount_rate"])), Decimal(str(l["vat_rate"]))) for l in lines),
                                document_discount)
        partner = self._connection.execute("SELECT name FROM core.partners WHERE id = %s", (quote["partner_id"],)).fetchone()
        return {**quote, "display_number": display_number(quote["number"], quote["revision"]),
                "partner_name": partner[0] if partner else None, "lines": lines, "totals": totals.as_dict()}

    def list_quotes(self, *, tenant_id: str, status: str | None = None, partner_id: str | None = None,
                    date_from: datetime.date | None = None, date_to: datetime.date | None = None) -> list[dict[str, Any]]:
        self.expire_due(tenant_id=tenant_id)
        query = f"SELECT {_QUOTE_COLUMNS} FROM sales.quotes WHERE tenant_id = %s"
        params: list[Any] = [tenant_id]
        for column, op, value in (("status", "=", status), ("partner_id", "=", partner_id),
                                  ("quote_date", ">=", date_from), ("quote_date", "<=", date_to)):
            if value is not None:
                query += f" AND {column} {op} %s"
                params.append(value)
        rows = self._connection.execute(query + " ORDER BY quote_date DESC, number DESC, revision DESC", params).fetchall()
        return [self._with_lines(dict(zip(_QUOTE_KEYS, row))) for row in rows]

    def stats(self, *, tenant_id: str, date_from: datetime.date | None = None, date_to: datetime.date | None = None) -> dict[str, Any]:
        quotes = self.list_quotes(tenant_id=tenant_id, date_from=date_from, date_to=date_to)
        counts: dict[str, int] = {}
        for quote in quotes:
            counts[quote["status"]] = counts.get(quote["status"], 0) + 1
        accepted_value = sum((Decimal(str(q["totals"]["incl_tax"])) for q in quotes if q["status"] == "accepted"), Decimal("0"))
        open_value = sum((Decimal(str(q["totals"]["incl_tax"])) for q in quotes if q["status"] in OPEN_QUOTE_STATUSES), Decimal("0"))
        return {"counts": counts, "conversion_rate": conversion_rate(q["status"] for q in quotes),
                "accepted_value": accepted_value, "open_value": open_value}

    # ---- writes -------------------------------------------------------------------------------

    def _price_lines(self, *, tenant_id: str, partner_id: str, lines: list[dict[str, Any]], on: datetime.date) -> Result[list[dict[str, Any]]]:
        """Fills what the user left out: the price from the customer's list, the default VAT rate."""
        if not lines:
            return Err("NO_LINES", "a quote needs at least one line", "un devis doit avoir au moins une ligne")
        settings = self._pricing.get_settings(tenant_id=tenant_id)
        resolved = self._pricing.resolve_prices(
            tenant_id=tenant_id, partner_id=partner_id,
            items=[(str(line["product_id"]), Decimal(str(line["quantity"]))) for line in lines], on=on,
        )
        if isinstance(resolved, Err):
            return resolved
        taxes = resolve_lines(self._connection, tenant_id=tenant_id, side="sales", partner_id=partner_id,
                              default_rate=Decimal(str(settings["default_vat_rate"])), lines=lines)
        if isinstance(taxes, Err):
            return taxes
        priced = []
        for line, price, tax in zip(lines, resolved.value, taxes.value):
            unit_price = line.get("unit_price")
            item = {
                "product_id": str(line["product_id"]),
                "quantity": Decimal(str(line["quantity"])),
                "unit_price": Decimal(str(unit_price)) if unit_price is not None else Decimal(str(price["unit_price"])),
                "discount_rate": Decimal(str(line.get("discount_rate") or 0)),
                "vat_rate": tax.rate,
                "tax_code": tax.tax_code,
                "price_list_id": price["price_list_id"] if unit_price is None else line.get("price_list_id"),
            }
            checked = check_line(quantity=item["quantity"], unit_price=item["unit_price"], discount_rate=item["discount_rate"],
                                 vat_rate=item["vat_rate"])
            if isinstance(checked, Err):
                return checked
            priced.append(item)
        return Ok(priced)

    def _check_discounts(self, *, tenant_id: str, lines: list[dict[str, Any]], discount_rate: Decimal, may_exceed: bool) -> Result[None]:
        checked = check_rate(discount_rate, what="discount")
        if isinstance(checked, Err):
            return checked
        limit = Decimal(str(self._pricing.get_settings(tenant_id=tenant_id)["max_discount_rate"]))
        return check_discount_limit((line["discount_rate"] for line in lines), discount_rate, limit=limit, may_exceed=may_exceed)

    def _write_lines(self, tenant_id: str, quote_id: str, lines: list[dict[str, Any]]) -> None:
        self._connection.execute("DELETE FROM sales.quote_lines WHERE quote_id = %s", (quote_id,))
        for number, line in enumerate(lines, start=1):
            self._connection.execute(
                """
                INSERT INTO sales.quote_lines (id, tenant_id, quote_id, line_no, product_id, quantity, unit_price, discount_rate,
                                               vat_rate, price_list_id, tax_code)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (str(ULID()), tenant_id, quote_id, number, line["product_id"], line["quantity"], line["unit_price"],
                 line["discount_rate"], line["vat_rate"], line.get("price_list_id"), line.get("tax_code")),
            )

    @atomic
    def create_quote(self, *, tenant_id: str, actor_id: str, partner_id: str, lines: list[dict[str, Any]],
                     quote_date: datetime.date | None = None, valid_until: datetime.date | None = None,
                     discount_rate: Decimal | None = None, opportunity_id: str | None = None, location_id: str | None = None,
                     note: str | None = None, may_exceed_discount: bool = False) -> Result[dict[str, Any]]:
        quote_date = quote_date or datetime.date.today()
        if not self._connection.execute("SELECT 1 FROM core.partners WHERE tenant_id = %s AND id = %s", (tenant_id, partner_id)).fetchone():
            return Err("NOT_FOUND", "customer not found", "client introuvable")
        settings = self._pricing.get_settings(tenant_id=tenant_id)
        valid_until = valid_until or quote_date + datetime.timedelta(days=int(settings["quote_validity_days"]))
        if valid_until < quote_date:
            return Err("INVALID_VALIDITY", "a quote can't expire before its date", "un devis ne peut pas expirer avant sa date")
        if discount_rate is None:
            discount_rate = Decimal(str(self._pricing.get_customer_pricing(tenant_id=tenant_id, partner_id=partner_id)["discount_rate"]))
        priced = self._price_lines(tenant_id=tenant_id, partner_id=partner_id, lines=lines, on=quote_date)
        if isinstance(priced, Err):
            return priced
        checked = self._check_discounts(tenant_id=tenant_id, lines=priced.value, discount_rate=discount_rate, may_exceed=may_exceed_discount)
        if isinstance(checked, Err):
            return checked
        quote_id = str(ULID())
        number = _next_number(self._connection, tenant_id, quote_date.year)
        self._connection.execute(
            """
            INSERT INTO sales.quotes (id, tenant_id, number, revision, partner_id, opportunity_id, location_id, quote_date,
                                      valid_until, status, discount_rate, note, created_by)
            VALUES (%s, %s, %s, 1, %s, %s, %s, %s, %s, 'draft', %s, %s, %s)
            """,
            (quote_id, tenant_id, number, partner_id, opportunity_id, location_id, quote_date, valid_until, discount_rate, note, actor_id),
        )
        self._write_lines(tenant_id, quote_id, priced.value)
        record_audit(self._connection, tenant_id=tenant_id, actor_id=actor_id, action="quote.created", entity_type="quote",
                     entity_id=quote_id, payload={"number": number, "partner_id": partner_id, "line_count": len(priced.value),
                                                  "discount_rate": str(discount_rate), "opportunity_id": opportunity_id})
        return self.get_quote(tenant_id=tenant_id, quote_id=quote_id)

    @atomic
    def update_quote(self, *, tenant_id: str, actor_id: str, quote_id: str, lines: list[dict[str, Any]] | None = None,
                     quote_date: datetime.date | None = None, valid_until: datetime.date | None = None,
                     discount_rate: Decimal | None = None, opportunity_id: str | None = None, location_id: str | None = None,
                     note: str | None = None, may_exceed_discount: bool = False) -> Result[dict[str, Any]]:
        """Only a draft changes in place; a sent quote is revised instead, so what the customer saw stays on record."""
        current = self._lock(tenant_id, quote_id)
        if isinstance(current, Err):
            return current
        quote = current.value
        if quote["status"] != "draft":
            return Err("QUOTE_NOT_DRAFT", "only a draft quote can be edited; revise it instead",
                       "seul un devis brouillon se modifie ; faites-en une révision")
        new = {
            "quote_date": quote_date or quote["quote_date"], "valid_until": valid_until or quote["valid_until"],
            "discount_rate": discount_rate if discount_rate is not None else Decimal(str(quote["discount_rate"])),
            "opportunity_id": opportunity_id if opportunity_id is not None else quote["opportunity_id"],
            "location_id": location_id if location_id is not None else quote["location_id"],
            "note": note if note is not None else quote["note"],
        }
        if new["valid_until"] < new["quote_date"]:
            return Err("INVALID_VALIDITY", "a quote can't expire before its date", "un devis ne peut pas expirer avant sa date")
        if lines is not None:
            priced = self._price_lines(tenant_id=tenant_id, partner_id=quote["partner_id"], lines=lines, on=new["quote_date"])
            if isinstance(priced, Err):
                return priced
            new_lines = priced.value
        else:
            new_lines = [{"product_id": l["product_id"], "quantity": Decimal(str(l["quantity"])), "unit_price": Decimal(str(l["unit_price"])),
                          "discount_rate": Decimal(str(l["discount_rate"])), "vat_rate": Decimal(str(l["vat_rate"])),
                          "price_list_id": l["price_list_id"], "tax_code": l["tax_code"]} for l in self.get_quote(tenant_id=tenant_id, quote_id=quote_id).value["lines"]]
        checked = self._check_discounts(tenant_id=tenant_id, lines=new_lines, discount_rate=new["discount_rate"], may_exceed=may_exceed_discount)
        if isinstance(checked, Err):
            return checked
        self._connection.execute(
            """
            UPDATE sales.quotes SET quote_date = %s, valid_until = %s, discount_rate = %s, opportunity_id = %s, location_id = %s, note = %s
            WHERE id = %s
            """,
            (new["quote_date"], new["valid_until"], new["discount_rate"], new["opportunity_id"], new["location_id"], new["note"], quote_id),
        )
        if lines is not None:
            self._write_lines(tenant_id, quote_id, new_lines)
        record_audit(self._connection, tenant_id=tenant_id, actor_id=actor_id, action="quote.updated", entity_type="quote",
                     entity_id=quote_id, payload={k: str(v) for k, v in new.items()} | {"lines_replaced": lines is not None})
        return self.get_quote(tenant_id=tenant_id, quote_id=quote_id)

    def _lock(self, tenant_id: str, quote_id: str) -> Result[dict[str, Any]]:
        self.expire_due(tenant_id=tenant_id)
        row = self._connection.execute(
            f"SELECT {_QUOTE_COLUMNS} FROM sales.quotes WHERE tenant_id = %s AND id = %s FOR UPDATE", (tenant_id, quote_id)
        ).fetchone()
        if row is None:
            return Err("NOT_FOUND", f"quote {quote_id} not found", f"devis {quote_id} introuvable")
        return Ok(dict(zip(_QUOTE_KEYS, row)))

    def _transition(self, tenant_id: str, actor_id: str, quote_id: str, target: str, *, reason: str | None = None) -> Result[dict[str, Any]]:
        current = self._lock(tenant_id, quote_id)
        if isinstance(current, Err):
            return current
        checked = check_quote_transition(current.value["status"], target)
        if isinstance(checked, Err):
            if current.value["status"] == "expired":
                return Err("QUOTE_EXPIRED", "this quote has expired; revise it to send a new offer",
                           "ce devis a expiré ; faites-en une révision pour envoyer une nouvelle offre")
            return checked
        self._connection.execute(
            "UPDATE sales.quotes SET status = %s, refusal_reason = COALESCE(%s, refusal_reason) WHERE id = %s", (target, reason, quote_id)
        )
        record_audit(self._connection, tenant_id=tenant_id, actor_id=actor_id, action="quote.status_changed", entity_type="quote",
                     entity_id=quote_id, payload={"from_status": current.value["status"], "to_status": target, "reason": reason})
        return self.get_quote(tenant_id=tenant_id, quote_id=quote_id)

    def send(self, *, tenant_id: str, actor_id: str, quote_id: str) -> Result[dict[str, Any]]:
        return self._transition(tenant_id, actor_id, quote_id, "sent")

    def accept(self, *, tenant_id: str, actor_id: str, quote_id: str) -> Result[dict[str, Any]]:
        return self._transition(tenant_id, actor_id, quote_id, "accepted")

    def refuse(self, *, tenant_id: str, actor_id: str, quote_id: str, reason: str | None = None) -> Result[dict[str, Any]]:
        return self._transition(tenant_id, actor_id, quote_id, "refused", reason=(reason or "").strip() or None)

    @atomic
    def revise(self, *, tenant_id: str, actor_id: str, quote_id: str) -> Result[dict[str, Any]]:
        """A new draft under the same number (DV-…-2, -3), lines copied. An open revision is superseded by it;
        a refused or expired one stays as it was. An accepted quote is final."""
        current = self._lock(tenant_id, quote_id)
        if isinstance(current, Err):
            return current
        quote = current.value
        if quote["status"] in ("accepted", "superseded"):
            return Err("QUOTE_NOT_REVISABLE", "an accepted or replaced quote can't be revised",
                       "un devis accepté ou remplacé ne peut pas être révisé")
        latest = self._connection.execute(
            "SELECT MAX(revision) FROM sales.quotes WHERE tenant_id = %s AND number = %s", (tenant_id, quote["number"])
        ).fetchone()[0]
        if quote["revision"] != latest:
            return Err("QUOTE_NOT_REVISABLE", "revise the latest revision of this quote", "révisez la dernière révision de ce devis")
        if quote["status"] in OPEN_QUOTE_STATUSES:
            self._connection.execute("UPDATE sales.quotes SET status = 'superseded' WHERE id = %s", (quote_id,))
        today = datetime.date.today()
        validity = int(self._pricing.get_settings(tenant_id=tenant_id)["quote_validity_days"])
        new_id = str(ULID())
        self._connection.execute(
            """
            INSERT INTO sales.quotes (id, tenant_id, number, revision, previous_id, partner_id, opportunity_id, location_id, quote_date,
                                      valid_until, status, discount_rate, note, created_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'draft', %s, %s, %s)
            """,
            (new_id, tenant_id, quote["number"], latest + 1, quote_id, quote["partner_id"], quote["opportunity_id"], quote["location_id"],
             today, today + datetime.timedelta(days=validity), quote["discount_rate"], quote["note"], actor_id),
        )
        copied = self._connection.execute(
            "SELECT product_id, quantity, unit_price, discount_rate, vat_rate, price_list_id, tax_code FROM sales.quote_lines "
            "WHERE quote_id = %s ORDER BY line_no",
            (quote_id,),
        ).fetchall()
        self._write_lines(tenant_id, new_id, [
            {"product_id": r[0], "quantity": r[1], "unit_price": r[2], "discount_rate": r[3], "vat_rate": r[4], "price_list_id": r[5],
             "tax_code": r[6]}
            for r in copied
        ])
        record_audit(self._connection, tenant_id=tenant_id, actor_id=actor_id, action="quote.revised", entity_type="quote", entity_id=new_id,
                     payload={"number": quote["number"], "revision": latest + 1, "previous_id": quote_id,
                              "previous_status": quote["status"]})
        return self.get_quote(tenant_id=tenant_id, quote_id=new_id)

    @atomic
    def convert_to_order(self, *, tenant_id: str, actor_id: str, quote_id: str, location_id: str | None = None,
                         requested_ship_date: datetime.date | None = None) -> Result[dict[str, Any]]:
        """The order of an accepted quote, at the quoted prices and discounts. Once only."""
        from modules.sales.api.service import SalesOrderService

        current = self._lock(tenant_id, quote_id)
        if isinstance(current, Err):
            return current
        quote = current.value
        if quote["order_id"]:
            return Err("QUOTE_ALREADY_ORDERED", "this quote already has its order", "ce devis a déjà sa commande")
        if quote["status"] != "accepted":
            return Err("QUOTE_NOT_ACCEPTED", "only an accepted quote becomes an order", "seul un devis accepté devient une commande")
        location_id = location_id or quote["location_id"]
        if not location_id:
            return Err("LOCATION_REQUIRED", "choose the warehouse the order ships from", "choisissez l'entrepôt d'expédition de la commande")
        detail = self.get_quote(tenant_id=tenant_id, quote_id=quote_id).value
        lines = [OrderLine(product_id=l["product_id"], quantity=l["quantity"], unit_price=l["unit_price"],
                           discount_rate=l["discount_rate"], vat_rate=l["vat_rate"], price_list_id=l["price_list_id"],
                           tax_code=l["tax_code"])
                 for l in detail["lines"]]
        order = SalesOrderService(self._connection).create_order(
            tenant_id=tenant_id, actor_id=actor_id, partner_id=quote["partner_id"], location_id=location_id, lines=lines,
            requested_ship_date=requested_ship_date, opportunity_id=quote["opportunity_id"],
            discount_rate=quote["discount_rate"], quote_id=quote_id,
        )
        self._connection.execute("UPDATE sales.quotes SET order_id = %s WHERE id = %s", (order.id, quote_id))
        record_audit(self._connection, tenant_id=tenant_id, actor_id=actor_id, action="quote.converted", entity_type="quote",
                     entity_id=quote_id, payload={"order_id": order.id})
        return Ok({"quote": self.get_quote(tenant_id=tenant_id, quote_id=quote_id).value, "order_id": order.id})
