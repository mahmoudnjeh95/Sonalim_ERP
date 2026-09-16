from __future__ import annotations

import psycopg
from ulid import ULID

from core.audit import record_audit
from core.domain.result import Err, Ok, Result


class ContactService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def list_contacts(self, *, tenant_id: str, partner_id: str | None = None) -> list[dict]:
        if partner_id is None:
            rows = self._connection.execute(
                """
                SELECT id, partner_id, first_name, last_name, job_title, email, phone, is_primary
                FROM crm.contacts WHERE tenant_id = %s ORDER BY is_primary DESC, last_name, first_name
                """,
                (tenant_id,),
            ).fetchall()
        else:
            rows = self._connection.execute(
                """
                SELECT id, partner_id, first_name, last_name, job_title, email, phone, is_primary
                FROM crm.contacts WHERE tenant_id = %s AND partner_id = %s
                ORDER BY is_primary DESC, last_name, first_name
                """,
                (tenant_id, partner_id),
            ).fetchall()
        return [self._response(row) for row in rows]

    def create_contact(self, *, tenant_id: str, actor_id: str, partner_id: str, first_name: str, last_name: str,
                       job_title: str | None, email: str | None, phone: str | None, is_primary: bool) -> Result[dict]:
        partner = self._connection.execute(
            "SELECT 1 FROM core.partners WHERE id = %s AND tenant_id = %s", (partner_id, tenant_id)
        ).fetchone()
        if partner is None:
            return Err("NOT_FOUND", f"partner {partner_id} not found")
        contact_id = str(ULID())
        try:
            self._connection.execute(
                """
                INSERT INTO crm.contacts (id, tenant_id, partner_id, first_name, last_name, job_title, email, phone, is_primary)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (contact_id, tenant_id, partner_id, first_name, last_name, job_title, email, phone, is_primary),
            )
        except psycopg.errors.UniqueViolation:
            return Err("PRIMARY_CONTACT_EXISTS", "this account already has a primary contact")
        record_audit(self._connection, tenant_id=tenant_id, actor_id=actor_id, action="contact.created",
                     entity_type="contact", entity_id=contact_id, payload={"partner_id": partner_id})
        row = (contact_id, partner_id, first_name, last_name, job_title, email, phone, is_primary)
        return Ok(self._response(row))

    def update_contact(
        self, *, tenant_id: str, actor_id: str, contact_id: str, first_name: str | None = None,
        last_name: str | None = None, job_title: str | None = None, email: str | None = None,
        phone: str | None = None, is_primary: bool | None = None,
    ) -> Result[dict]:
        row = self._connection.execute(
            """
            SELECT id, partner_id, first_name, last_name, job_title, email, phone, is_primary
            FROM crm.contacts WHERE id = %s AND tenant_id = %s FOR UPDATE
            """,
            (contact_id, tenant_id),
        ).fetchone()
        if row is None:
            return Err("NOT_FOUND", f"contact {contact_id} not found")

        current = self._response(row)
        updated = {
            "first_name": first_name if first_name is not None else current["first_name"],
            "last_name": last_name if last_name is not None else current["last_name"],
            "job_title": job_title if job_title is not None else current["job_title"],
            "email": email if email is not None else current["email"],
            "phone": phone if phone is not None else current["phone"],
            "is_primary": is_primary if is_primary is not None else current["is_primary"],
        }
        try:
            self._connection.execute(
                """
                UPDATE crm.contacts SET first_name = %s, last_name = %s, job_title = %s, email = %s, phone = %s, is_primary = %s
                WHERE id = %s AND tenant_id = %s
                """,
                (updated["first_name"], updated["last_name"], updated["job_title"], updated["email"],
                 updated["phone"], updated["is_primary"], contact_id, tenant_id),
            )
        except psycopg.errors.UniqueViolation:
            return Err("PRIMARY_CONTACT_EXISTS", "this account already has a primary contact")
        record_audit(self._connection, tenant_id=tenant_id, actor_id=actor_id, action="contact.updated",
                     entity_type="contact", entity_id=contact_id, payload=updated)
        return Ok(self._response((contact_id, current["partner_id"], updated["first_name"], updated["last_name"],
                                   updated["job_title"], updated["email"], updated["phone"], updated["is_primary"])))

    @staticmethod
    def _response(row) -> dict:
        return {
            "id": row[0], "partner_id": row[1], "first_name": row[2], "last_name": row[3],
            "job_title": row[4], "email": row[5], "phone": row[6], "is_primary": row[7],
        }
