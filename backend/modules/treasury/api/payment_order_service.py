from __future__ import annotations

import datetime
from typing import Any

import psycopg
from ulid import ULID

from core.audit import record_audit
from core.domain.result import Err, Ok, Result


class PaymentOrderService:
    """Transfer instructions for a disbursement, and the in-app notices that ask someone to act on
    them. Callers commit."""

    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def create_for_disbursement(self, *, tenant_id: str, actor_id: str, disbursement_id: str, note: str | None = None) -> Result[dict[str, Any]]:
        row = self._connection.execute(
            "SELECT status FROM treasury.documents WHERE id = %s AND tenant_id = %s AND direction = 'out' FOR UPDATE",
            (disbursement_id, tenant_id),
        ).fetchone()
        if row is None:
            return Err("NOT_FOUND", f"disbursement {disbursement_id} not found", f"décaissement {disbursement_id} introuvable")
        if row[0] != "posted":
            return Err("DOCUMENT_NOT_POSTED", "only a posted disbursement can have a payment order", "seul un décaissement comptabilisé peut avoir un ordre de virement")
        has_transfer = self._connection.execute(
            "SELECT 1 FROM treasury.document_payments WHERE document_id = %s AND method = 'transfer' LIMIT 1", (disbursement_id,)
        ).fetchone()
        if has_transfer is None:
            return Err("NO_TRANSFER", "this disbursement has no bank transfer to order", "ce décaissement n'a aucun virement à ordonner")
        if self._connection.execute("SELECT 1 FROM treasury.payment_orders WHERE disbursement_id = %s", (disbursement_id,)).fetchone():
            return Err("PAYMENT_ORDER_EXISTS", "this disbursement already has a payment order", "ce décaissement a déjà un ordre de virement")

        order_id = str(ULID())
        number = self._next_number(tenant_id, datetime.date.today().year)
        self._connection.execute(
            "INSERT INTO treasury.payment_orders (id, tenant_id, number, disbursement_id, note, created_by) VALUES (%s, %s, %s, %s, %s, %s)",
            (order_id, tenant_id, number, disbursement_id, note, actor_id),
        )
        record_audit(self._connection, tenant_id=tenant_id, actor_id=actor_id, action="treasury.payment_order.created",
                     entity_type="payment_order", entity_id=order_id, payload={"number": number, "disbursement_id": disbursement_id})
        return self.get(tenant_id=tenant_id, order_id=order_id)

    def get(self, *, tenant_id: str, order_id: str) -> Result[dict[str, Any]]:
        """Everything the printed order shows: who is paid, how much, from which account."""
        row = self._connection.execute(
            """
            SELECT o.id, o.number, o.created_at, o.note, d.id, d.number, d.partner_id, d.currency, d.doc_date
            FROM treasury.payment_orders o JOIN treasury.documents d ON d.id = o.disbursement_id
            WHERE o.id = %s AND o.tenant_id = %s
            """,
            (order_id, tenant_id),
        ).fetchone()
        if row is None:
            return Err("NOT_FOUND", f"payment order {order_id} not found", f"ordre de virement {order_id} introuvable")
        transfers = self._connection.execute(
            """
            SELECT p.id, p.amount, a.name, a.account_number, a.iban
            FROM treasury.document_payments p LEFT JOIN treasury.accounts a ON a.id = p.account_id
            WHERE p.document_id = %s AND p.method = 'transfer' ORDER BY p.id
            """,
            (row[4],),
        ).fetchall()
        keys = ["payment_id", "amount", "account_name", "account_number", "iban"]
        return Ok({
            "id": row[0], "number": row[1], "created_at": row[2], "note": row[3], "disbursement_id": row[4],
            "disbursement_number": row[5], "partner_id": row[6], "currency": row[7], "doc_date": row[8],
            "transfers": [dict(zip(keys, t, strict=True)) for t in transfers],
            "total": sum((t[1] for t in transfers), 0),
        })

    def list(self, *, tenant_id: str) -> list[dict[str, Any]]:
        rows = self._connection.execute(
            "SELECT o.id, o.number, o.created_at, d.number, d.partner_id, d.total, d.currency "
            "FROM treasury.payment_orders o JOIN treasury.documents d ON d.id = o.disbursement_id "
            "WHERE o.tenant_id = %s ORDER BY o.created_at DESC, o.id DESC",
            (tenant_id,),
        ).fetchall()
        keys = ["id", "number", "created_at", "disbursement_number", "partner_id", "total", "currency"]
        return [dict(zip(keys, r, strict=True)) for r in rows]

    def notify(self, *, tenant_id: str, actor_id: str, order_id: str, user_id: str) -> Result[dict[str, Any]]:
        order = self.get(tenant_id=tenant_id, order_id=order_id)
        if isinstance(order, Err):
            return order
        if self._connection.execute("SELECT 1 FROM core.users WHERE id = %s AND tenant_id = %s", (user_id, tenant_id)).fetchone() is None:
            return Err("NOT_FOUND", f"user {user_id} not found", f"utilisateur {user_id} introuvable")
        number = order.value["number"]
        notification_id = str(ULID())
        self._connection.execute(
            "INSERT INTO treasury.user_notifications (id, tenant_id, user_id, kind, ref_id, message_en, message_fr, created_by) "
            "VALUES (%s, %s, %s, 'payment_order', %s, %s, %s, %s)",
            (notification_id, tenant_id, user_id, order_id, f"Payment order {number} is waiting for you",
             f"L'ordre de virement {number} vous attend", actor_id),
        )
        record_audit(self._connection, tenant_id=tenant_id, actor_id=actor_id, action="treasury.payment_order.notified",
                     entity_type="payment_order", entity_id=order_id, payload={"user_id": user_id})
        return Ok({"id": notification_id})

    def notifications(self, *, tenant_id: str, user_id: str, include_read: bool = False) -> list[dict[str, Any]]:
        clause = "" if include_read else " AND read_at IS NULL"
        rows = self._connection.execute(
            f"SELECT id, kind, ref_id, message_en, message_fr, created_at, read_at FROM treasury.user_notifications "
            f"WHERE tenant_id = %s AND user_id = %s{clause} ORDER BY created_at DESC, id DESC",
            (tenant_id, user_id),
        ).fetchall()
        keys = ["id", "kind", "ref_id", "message_en", "message_fr", "created_at", "read_at"]
        return [dict(zip(keys, r, strict=True)) for r in rows]

    def mark_read(self, *, tenant_id: str, user_id: str, notification_id: str) -> Result[None]:
        updated = self._connection.execute(
            "UPDATE treasury.user_notifications SET read_at = COALESCE(read_at, NOW()) WHERE id = %s AND tenant_id = %s AND user_id = %s",
            (notification_id, tenant_id, user_id),
        ).rowcount
        if not updated:
            return Err("NOT_FOUND", f"notification {notification_id} not found", f"notification {notification_id} introuvable")
        return Ok(None)

    def notifiable_users(self, *, tenant_id: str) -> list[dict[str, Any]]:
        rows = self._connection.execute("SELECT id, email FROM core.users WHERE tenant_id = %s ORDER BY email", (tenant_id,)).fetchall()
        return [{"id": r[0], "email": r[1]} for r in rows]

    def _next_number(self, tenant_id: str, year: int) -> str:
        row = self._connection.execute(
            """
            INSERT INTO treasury.document_counters (tenant_id, direction, year, last_number) VALUES (%s, 'order', %s, 1)
            ON CONFLICT (tenant_id, direction, year)
            DO UPDATE SET last_number = treasury.document_counters.last_number + 1
            RETURNING last_number
            """,
            (tenant_id, year),
        ).fetchone()
        return f"OV-{year}-{row[0]:06d}"
