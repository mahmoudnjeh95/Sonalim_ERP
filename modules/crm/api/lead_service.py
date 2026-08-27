from __future__ import annotations

import psycopg
from ulid import ULID

from core.api.service import CoreService
from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from core.events.outbox import publish_event
from modules.crm.api.opportunity_service import OpportunityService
from modules.crm.domain.entities import Lead, transition


class LeadService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def create_lead(self, *, tenant_id: str, actor_id: str, contact_name: str, email: str) -> Lead:
        lead_id = str(ULID())
        self._connection.execute(
            """
            INSERT INTO crm.leads (id, tenant_id, contact_name, email, status)
            VALUES (%s, %s, %s, %s, 'new')
            """,
            (lead_id, tenant_id, contact_name, email),
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="lead.created",
            entity_type="lead",
            entity_id=lead_id,
            payload={"contact_name": contact_name, "email": email},
        )
        return Lead(id=lead_id, contact_name=contact_name, email=email, status="new")

    def update_lead(
        self, *, tenant_id: str, actor_id: str, lead_id: str, contact_name: str | None = None, email: str | None = None
    ) -> Result[Lead]:
        row = self._connection.execute(
            "SELECT contact_name, email, status FROM crm.leads WHERE id = %s AND tenant_id = %s FOR UPDATE",
            (lead_id, tenant_id),
        ).fetchone()
        if row is None:
            return Err("NOT_FOUND", f"lead {lead_id} not found")

        current_contact_name, current_email, status = row
        updated = Lead(
            id=lead_id,
            contact_name=contact_name if contact_name is not None else current_contact_name,
            email=email if email is not None else current_email,
            status=status,
        )
        self._connection.execute(
            "UPDATE crm.leads SET contact_name = %s, email = %s WHERE id = %s AND tenant_id = %s",
            (updated.contact_name, updated.email, lead_id, tenant_id),
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="lead.updated",
            entity_type="lead",
            entity_id=lead_id,
            payload={"contact_name": updated.contact_name, "email": updated.email},
        )
        return Ok(updated)

    def list_leads(self, *, tenant_id: str) -> list[Lead]:
        rows = self._connection.execute(
            "SELECT id, contact_name, email, status FROM crm.leads WHERE tenant_id = %s ORDER BY created_at DESC",
            (tenant_id,),
        ).fetchall()
        return [
            Lead(id=row[0], contact_name=row[1], email=row[2], status=row[3])
            for row in rows
        ]

    def qualify_lead(self, *, tenant_id: str, actor_id: str, lead_id: str, correlation_id: str) -> Result[Lead]:
        row = self._connection.execute(
            "SELECT contact_name, email, status FROM crm.leads WHERE id = %s AND tenant_id = %s FOR UPDATE",
            (lead_id, tenant_id),
        ).fetchone()
        if row is None:
            return Err("NOT_FOUND", f"lead {lead_id} not found")

        contact_name, email, current_status = row
        current = Lead(id=lead_id, contact_name=contact_name, email=email, status=current_status)
        result = transition(current, "qualified")
        if isinstance(result, Err):
            return result

        self._connection.execute("UPDATE crm.leads SET status = 'qualified' WHERE id = %s", (lead_id,))
        publish_event(
            self._connection,
            event_type="crm.lead.qualified",
            producer="crm",
            tenant_id=tenant_id,
            correlation_id=correlation_id,
            payload={"lead_id": lead_id, "email": email},
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="lead.qualified",
            entity_type="lead",
            entity_id=lead_id,
            payload={"from_status": current_status, "to_status": "qualified"},
        )
        return result

    def convert_lead(self, *, tenant_id: str, actor_id: str, lead_id: str, correlation_id: str) -> Result[dict]:
        row = self._connection.execute(
            "SELECT contact_name, email, status FROM crm.leads WHERE id = %s AND tenant_id = %s FOR UPDATE",
            (lead_id, tenant_id),
        ).fetchone()
        if row is None:
            return Err("NOT_FOUND", f"lead {lead_id} not found")

        contact_name, email, current_status = row
        current = Lead(id=lead_id, contact_name=contact_name, email=email, status=current_status)
        result = transition(current, "converted")
        if isinstance(result, Err):
            return result

        partner_result = CoreService(self._connection).create_partner(
            tenant_id=tenant_id, actor_id=actor_id, name=contact_name, kind="customer"
        )
        assert isinstance(partner_result, Ok)  # validate_partner_name can't fail: contact_name is non-blank on a lead
        partner = partner_result.value

        name_parts = contact_name.strip().split(maxsplit=1)
        self._connection.execute(
            """
            INSERT INTO crm.contacts (id, tenant_id, partner_id, first_name, last_name, email, is_primary)
            VALUES (%s, %s, %s, %s, %s, %s, TRUE)
            """,
            (str(ULID()), tenant_id, partner.id, name_parts[0], name_parts[1] if len(name_parts) > 1 else "", email),
        )

        opportunity_result = OpportunityService(self._connection).create_opportunity(
            tenant_id=tenant_id, actor_id=actor_id, partner_id=partner.id, name=f"{contact_name} opportunity", amount=0
        )
        assert isinstance(opportunity_result, Ok)  # amount=0 always passes validate_amount
        opportunity = opportunity_result.value

        self._connection.execute(
            """
            UPDATE crm.leads SET status = 'converted', converted_partner_id = %s, converted_opportunity_id = %s
            WHERE id = %s
            """,
            (partner.id, opportunity.id, lead_id),
        )
        publish_event(
            self._connection,
            event_type="crm.lead.converted",
            producer="crm",
            tenant_id=tenant_id,
            correlation_id=correlation_id,
            payload={"lead_id": lead_id, "partner_id": partner.id, "opportunity_id": opportunity.id},
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="lead.converted",
            entity_type="lead",
            entity_id=lead_id,
            payload={"partner_id": partner.id, "opportunity_id": opportunity.id},
        )
        return Ok({"lead": result.value, "partner": partner, "opportunity": opportunity})
