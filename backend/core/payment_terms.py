"""Payment terms, a shared-kernel catalog, and which term each partner buys or sells on.

Finance and procurement both read a partner's terms to date their invoices, so the service lives here.
The screens that manage them belong to receivables and are served by finance's router."""
from __future__ import annotations

import datetime
import json
from decimal import Decimal
from typing import Any

import psycopg
from ulid import ULID

from core.audit import record_audit
from core.domain.payment_terms import DEFAULT_TERMS, Installment, parse_installments, schedule
from core.domain.result import Err, Ok, Result

SIDES = ("customer", "supplier")
_COLUMNS = "id, code, name_fr, name_en, installments, active"


def _row(row) -> dict[str, Any]:
    return {"id": row[0], "code": row[1], "name_fr": row[2], "name_en": row[3], "installments": row[4], "active": row[5]}


def _installments(term: dict[str, Any]) -> tuple[Installment, ...]:
    return parse_installments(term["installments"]).value


class PaymentTermService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def _ensure_defaults(self, tenant_id: str) -> None:
        if self._connection.execute("SELECT 1 FROM core.payment_terms WHERE tenant_id = %s LIMIT 1", (tenant_id,)).fetchone():
            return
        for code, name_fr, name_en, installments in DEFAULT_TERMS:
            self._connection.execute(
                "INSERT INTO core.payment_terms (id, tenant_id, code, name_fr, name_en, installments) VALUES (%s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (tenant_id, code) DO NOTHING",
                (str(ULID()), tenant_id, code, name_fr, name_en, json.dumps([i.as_dict() for i in installments])),
            )

    def list_terms(self, *, tenant_id: str, include_inactive: bool = False) -> list[dict[str, Any]]:
        self._ensure_defaults(tenant_id)
        rows = self._connection.execute(
            f"SELECT {_COLUMNS} FROM core.payment_terms WHERE tenant_id = %s {'' if include_inactive else 'AND active'} ORDER BY created_at, code",
            (tenant_id,),
        ).fetchall()
        return [_row(row) for row in rows]

    def get_term(self, *, tenant_id: str, term_id: str) -> dict[str, Any] | None:
        row = self._connection.execute(f"SELECT {_COLUMNS} FROM core.payment_terms WHERE tenant_id = %s AND id = %s",
                                       (tenant_id, term_id)).fetchone()
        return _row(row) if row else None

    def create_term(self, *, tenant_id: str, actor_id: str, code: str, name_fr: str, name_en: str,
                    installments: list[dict[str, Any]]) -> Result[dict[str, Any]]:
        code, name_fr, name_en = code.strip().upper(), name_fr.strip(), (name_en or name_fr).strip()
        if not code or not name_fr:
            return Err("INVALID_PAYMENT_TERM", "a payment term needs a code and a name", "une condition de paiement a un code et un nom")
        parsed = parse_installments(installments)
        if isinstance(parsed, Err):
            return parsed
        self._ensure_defaults(tenant_id)
        if self._connection.execute("SELECT 1 FROM core.payment_terms WHERE tenant_id = %s AND code = %s", (tenant_id, code)).fetchone():
            return Err("PAYMENT_TERM_EXISTS", f"a payment term {code} already exists", f"une condition de paiement {code} existe déjà")
        term_id = str(ULID())
        self._connection.execute(
            "INSERT INTO core.payment_terms (id, tenant_id, code, name_fr, name_en, installments) VALUES (%s, %s, %s, %s, %s, %s)",
            (term_id, tenant_id, code, name_fr, name_en, json.dumps([i.as_dict() for i in parsed.value])),
        )
        record_audit(self._connection, tenant_id=tenant_id, actor_id=actor_id, action="payment_term.created", entity_type="payment_term",
                     entity_id=term_id, payload={"code": code, "installments": [i.as_dict() for i in parsed.value]})
        return Ok(self.get_term(tenant_id=tenant_id, term_id=term_id))

    def update_term(self, *, tenant_id: str, actor_id: str, term_id: str, name_fr: str | None = None, name_en: str | None = None,
                    installments: list[dict[str, Any]] | None = None, active: bool | None = None) -> Result[dict[str, Any]]:
        """Changing a term never redates invoices already issued: they keep the schedule they were given."""
        current = self.get_term(tenant_id=tenant_id, term_id=term_id)
        if current is None:
            return Err("NOT_FOUND", f"payment term {term_id} not found", f"condition de paiement {term_id} introuvable")
        values = {
            "name_fr": (name_fr or current["name_fr"]).strip(),
            "name_en": (name_en or current["name_en"]).strip(),
            "installments": current["installments"],
            "active": current["active"] if active is None else active,
        }
        if installments is not None:
            parsed = parse_installments(installments)
            if isinstance(parsed, Err):
                return parsed
            values["installments"] = [i.as_dict() for i in parsed.value]
        self._connection.execute(
            "UPDATE core.payment_terms SET name_fr = %s, name_en = %s, installments = %s, active = %s WHERE tenant_id = %s AND id = %s",
            (values["name_fr"], values["name_en"], json.dumps(values["installments"]), values["active"], tenant_id, term_id),
        )
        record_audit(self._connection, tenant_id=tenant_id, actor_id=actor_id, action="payment_term.updated", entity_type="payment_term",
                     entity_id=term_id, payload={k: v for k, v in values.items()})
        return Ok(self.get_term(tenant_id=tenant_id, term_id=term_id))

    def partner_terms(self, *, tenant_id: str, partner_id: str) -> dict[str, Any]:
        row = self._connection.execute(
            "SELECT customer_payment_term_id, supplier_payment_term_id FROM core.partners WHERE tenant_id = %s AND id = %s",
            (tenant_id, partner_id),
        ).fetchone()
        customer_id, supplier_id = row if row else (None, None)
        return {
            "customer": self.get_term(tenant_id=tenant_id, term_id=customer_id) if customer_id else None,
            "supplier": self.get_term(tenant_id=tenant_id, term_id=supplier_id) if supplier_id else None,
        }

    def set_partner_term(self, *, tenant_id: str, actor_id: str, partner_id: str, side: str, term_id: str | None) -> Result[dict[str, Any]]:
        if side not in SIDES:
            return Err("INVALID_SIDE", "side is customer or supplier", "le côté est client ou fournisseur")
        if not self._connection.execute("SELECT 1 FROM core.partners WHERE tenant_id = %s AND id = %s", (tenant_id, partner_id)).fetchone():
            return Err("NOT_FOUND", f"partner {partner_id} not found", f"partenaire {partner_id} introuvable")
        if term_id is not None:
            term = self.get_term(tenant_id=tenant_id, term_id=term_id)
            if term is None or not term["active"]:
                return Err("NOT_FOUND", f"payment term {term_id} not found", f"condition de paiement {term_id} introuvable")
        self._connection.execute(
            f"UPDATE core.partners SET {side}_payment_term_id = %s WHERE tenant_id = %s AND id = %s", (term_id, tenant_id, partner_id))
        record_audit(self._connection, tenant_id=tenant_id, actor_id=actor_id, action="partner.payment_term_set", entity_type="partner",
                     entity_id=partner_id, payload={"side": side, "payment_term_id": term_id})
        return Ok(self.partner_terms(tenant_id=tenant_id, partner_id=partner_id))

    def schedule_for(self, *, tenant_id: str, partner_id: str, side: str, invoice_date: datetime.date,
                     amount: Decimal) -> dict[str, Any]:
        """The partner's term and the installments it gives an invoice. A partner with no term pays on the
        invoice date, so a missing term never leaves an invoice without a due date."""
        term = self.partner_terms(tenant_id=tenant_id, partner_id=partner_id)[side]
        installments = _installments(term) if term else (Installment(Decimal("100"), 0),)
        rows = schedule(invoice_date, Decimal(str(amount)), installments)
        return {
            "term": {"id": term["id"], "code": term["code"], "name_fr": term["name_fr"], "name_en": term["name_en"]} if term else None,
            "installments": [{"due_date": due, "amount": share} for due, share in rows],
            "due_date": rows[-1][0],
            # What the invoice keeps, so redating it later (a new amount or date) never reads today's catalog.
            "rule": [i.as_dict() for i in installments],
        }
