from __future__ import annotations

import psycopg
from ulid import ULID

from core.api.service import CoreService
from core.audit import record_audit
from core.domain.partner import Partner
from core.domain.result import Err, Ok, Result
from core.events.outbox import publish_event
from modules.crm.api.opportunity_service import OpportunityService
from modules.crm.domain.entities import Lead, transition, validate_disqualify_reason

_LEAD_COLUMNS = "id, contact_name, email, status, source, owner_id, priority, disqualify_reason"


def _lead_from_row(row) -> Lead:
    return Lead(
        id=row[0],
        contact_name=row[1],
        email=row[2],
        status=row[3],
        source=row[4],
        owner_id=row[5],
        priority=row[6],
        disqualify_reason=row[7],
    )


class LeadService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def create_lead(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        contact_name: str,
        email: str,
        source: str | None = None,
        owner_id: str | None = None,
        priority: str = "medium",
    ) -> Lead:
        lead_id = str(ULID())
        self._connection.execute(
            """
            INSERT INTO crm.leads (id, tenant_id, contact_name, email, status, source, owner_id, priority)
            VALUES (%s, %s, %s, %s, 'new', %s, %s, %s)
            """,
            (lead_id, tenant_id, contact_name, email, source, owner_id, priority),
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="lead.created",
            entity_type="lead",
            entity_id=lead_id,
            payload={"contact_name": contact_name, "email": email, "source": source, "owner_id": owner_id},
        )
        return Lead(id=lead_id, contact_name=contact_name, email=email, status="new", source=source, owner_id=owner_id, priority=priority)

    def update_lead(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        lead_id: str,
        contact_name: str | None = None,
        email: str | None = None,
        source: str | None = None,
        owner_id: str | None = None,
        priority: str | None = None,
    ) -> Result[Lead]:
        row = self._connection.execute(
            f"SELECT {_LEAD_COLUMNS} FROM crm.leads WHERE id = %s AND tenant_id = %s FOR UPDATE",
            (lead_id, tenant_id),
        ).fetchone()
        if row is None:
            return Err("NOT_FOUND", f"lead {lead_id} not found", f"prospect {lead_id} introuvable")

        current = _lead_from_row(row)
        updated = Lead(
            id=lead_id,
            contact_name=contact_name if contact_name is not None else current.contact_name,
            email=email if email is not None else current.email,
            status=current.status,
            source=source if source is not None else current.source,
            owner_id=owner_id if owner_id is not None else current.owner_id,
            priority=priority if priority is not None else current.priority,
            disqualify_reason=current.disqualify_reason,
        )
        self._connection.execute(
            "UPDATE crm.leads SET contact_name = %s, email = %s, source = %s, owner_id = %s, priority = %s WHERE id = %s AND tenant_id = %s",
            (updated.contact_name, updated.email, updated.source, updated.owner_id, updated.priority, lead_id, tenant_id),
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="lead.updated",
            entity_type="lead",
            entity_id=lead_id,
            payload={"contact_name": updated.contact_name, "email": updated.email, "source": updated.source, "owner_id": updated.owner_id, "priority": updated.priority},
        )
        return Ok(updated)

    def list_leads(self, *, tenant_id: str) -> list[Lead]:
        rows = self._connection.execute(
            f"SELECT {_LEAD_COLUMNS} FROM crm.leads WHERE tenant_id = %s ORDER BY created_at DESC",
            (tenant_id,),
        ).fetchall()
        return [_lead_from_row(row) for row in rows]

    def disqualify_lead(
        self, *, tenant_id: str, actor_id: str, lead_id: str, reason: str, correlation_id: str
    ) -> Result[Lead]:
        validation = validate_disqualify_reason(reason)
        if isinstance(validation, Err):
            return validation

        row = self._connection.execute(
            f"SELECT {_LEAD_COLUMNS} FROM crm.leads WHERE id = %s AND tenant_id = %s FOR UPDATE",
            (lead_id, tenant_id),
        ).fetchone()
        if row is None:
            return Err("NOT_FOUND", f"lead {lead_id} not found", f"prospect {lead_id} introuvable")

        current = _lead_from_row(row)
        result = transition(current, "disqualified")
        if isinstance(result, Err):
            return result

        self._connection.execute(
            "UPDATE crm.leads SET status = 'disqualified', disqualify_reason = %s WHERE id = %s",
            (reason, lead_id),
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="lead.disqualified",
            entity_type="lead",
            entity_id=lead_id,
            payload={"from_status": current.status, "reason": reason},
        )
        final = Lead(
            id=current.id,
            contact_name=current.contact_name,
            email=current.email,
            status="disqualified",
            source=current.source,
            owner_id=current.owner_id,
            priority=current.priority,
            disqualify_reason=reason,
        )
        return Ok(final)

    def qualify_lead(self, *, tenant_id: str, actor_id: str, lead_id: str, correlation_id: str) -> Result[Lead]:
        row = self._connection.execute(
            f"SELECT {_LEAD_COLUMNS} FROM crm.leads WHERE id = %s AND tenant_id = %s FOR UPDATE",
            (lead_id, tenant_id),
        ).fetchone()
        if row is None:
            return Err("NOT_FOUND", f"lead {lead_id} not found", f"prospect {lead_id} introuvable")

        current = _lead_from_row(row)
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
            payload={"lead_id": lead_id, "email": current.email},
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="lead.qualified",
            entity_type="lead",
            entity_id=lead_id,
            payload={"from_status": current.status, "to_status": "qualified"},
        )
        return result

    def convert_lead(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        lead_id: str,
        correlation_id: str,
        existing_partner_id: str | None = None,
    ) -> Result[dict]:
        row = self._connection.execute(
            f"SELECT {_LEAD_COLUMNS} FROM crm.leads WHERE id = %s AND tenant_id = %s FOR UPDATE",
            (lead_id, tenant_id),
        ).fetchone()
        if row is None:
            return Err("NOT_FOUND", f"lead {lead_id} not found", f"prospect {lead_id} introuvable")

        current = _lead_from_row(row)
        contact_name, email = current.contact_name, current.email
        result = transition(current, "converted")
        if isinstance(result, Err):
            return result

        if existing_partner_id is not None:
            partner_row = self._connection.execute(
                "SELECT id, tenant_id, name, kind, industry, website, phone, email, status FROM core.partners WHERE id = %s AND tenant_id = %s",
                (existing_partner_id, tenant_id),
            ).fetchone()
            if partner_row is None:
                return Err("NOT_FOUND", f"partner {existing_partner_id} not found", f"partenaire {existing_partner_id} introuvable")
            if partner_row[3] not in ("customer", "both"):
                return Err(
                    "INVALID_PARTNER_KIND",
                    "can only link a lead to a customer partner",
                    "un prospect ne peut être lié qu'à un partenaire client",
                )
            partner = Partner(
                id=partner_row[0], tenant_id=partner_row[1], name=partner_row[2], kind=partner_row[3],
                industry=partner_row[4], website=partner_row[5], phone=partner_row[6], email=partner_row[7], status=partner_row[8],
            )
        else:
            partner_result = CoreService(self._connection).create_partner(
                tenant_id=tenant_id, actor_id=actor_id, name=contact_name, kind="customer"
            )
            assert isinstance(partner_result, Ok)  # validate_partner_name can't fail: contact_name is non-blank on a lead
            partner = partner_result.value

        name_parts = contact_name.strip().split(maxsplit=1)
        has_primary_contact = self._connection.execute(
            "SELECT 1 FROM crm.contacts WHERE tenant_id = %s AND partner_id = %s AND is_primary",
            (tenant_id, partner.id),
        ).fetchone() is not None
        self._connection.execute(
            """
            INSERT INTO crm.contacts (id, tenant_id, partner_id, first_name, last_name, email, is_primary)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (str(ULID()), tenant_id, partner.id, name_parts[0], name_parts[1] if len(name_parts) > 1 else "", email, not has_primary_contact),
        )

        opportunity_result = OpportunityService(self._connection).create_opportunity(
            tenant_id=tenant_id, actor_id=actor_id, partner_id=partner.id, name=f"{contact_name} opportunity", amount=0, owner_id=current.owner_id
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
