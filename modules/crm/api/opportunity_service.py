from __future__ import annotations

import datetime

import psycopg
from ulid import ULID

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from modules.crm.domain.opportunity import Opportunity, transition_opportunity, validate_amount


class OpportunityService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def create_opportunity(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        partner_id: str,
        name: str,
        amount: float,
        expected_close_date: datetime.date | None = None,
    ) -> Result[Opportunity]:
        validation = validate_amount(amount)
        if isinstance(validation, Err):
            return validation

        opportunity_id = str(ULID())
        self._connection.execute(
            """
            INSERT INTO crm.opportunities (id, tenant_id, partner_id, name, stage, amount, expected_close_date)
            VALUES (%s, %s, %s, %s, 'prospecting', %s, %s)
            """,
            (opportunity_id, tenant_id, partner_id, name, amount, expected_close_date),
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="opportunity.created",
            entity_type="opportunity",
            entity_id=opportunity_id,
            payload={"partner_id": partner_id, "name": name, "amount": amount},
        )
        return Ok(
            Opportunity(
                id=opportunity_id,
                partner_id=partner_id,
                name=name,
                stage="prospecting",
                amount=amount,
                expected_close_date=expected_close_date.isoformat() if expected_close_date else None,
            )
        )

    def update_opportunity(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        opportunity_id: str,
        partner_id: str | None = None,
        name: str | None = None,
        amount: float | None = None,
        expected_close_date: datetime.date | None = None,
    ) -> Result[Opportunity]:
        row = self._connection.execute(
            """
            SELECT id, partner_id, name, stage, amount, expected_close_date FROM crm.opportunities
            WHERE id = %s AND tenant_id = %s FOR UPDATE
            """,
            (opportunity_id, tenant_id),
        ).fetchone()
        if row is None:
            return Err("NOT_FOUND", f"opportunity {opportunity_id} not found")

        current = Opportunity(
            id=row[0],
            partner_id=row[1],
            name=row[2],
            stage=row[3],
            amount=float(row[4]),
            expected_close_date=row[5].isoformat() if row[5] else None,
        )
        updated = Opportunity(
            id=current.id,
            partner_id=partner_id if partner_id is not None else current.partner_id,
            name=name if name is not None else current.name,
            stage=current.stage,
            amount=amount if amount is not None else current.amount,
            expected_close_date=expected_close_date.isoformat() if expected_close_date is not None else current.expected_close_date,
        )
        validation = validate_amount(updated.amount)
        if isinstance(validation, Err):
            return validation

        self._connection.execute(
            """
            UPDATE crm.opportunities SET partner_id = %s, name = %s, amount = %s, expected_close_date = %s
            WHERE id = %s AND tenant_id = %s
            """,
            (updated.partner_id, updated.name, updated.amount, updated.expected_close_date, opportunity_id, tenant_id),
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="opportunity.updated",
            entity_type="opportunity",
            entity_id=opportunity_id,
            payload={"partner_id": updated.partner_id, "name": updated.name, "amount": updated.amount},
        )
        return Ok(updated)

    def list_opportunities(self, *, tenant_id: str, partner_id: str | None = None) -> list[Opportunity]:
        if partner_id is not None:
            rows = self._connection.execute(
                """
                SELECT id, partner_id, name, stage, amount, expected_close_date FROM crm.opportunities
                WHERE tenant_id = %s AND partner_id = %s ORDER BY created_at DESC
                """,
                (tenant_id, partner_id),
            ).fetchall()
        else:
            rows = self._connection.execute(
                """
                SELECT id, partner_id, name, stage, amount, expected_close_date FROM crm.opportunities
                WHERE tenant_id = %s ORDER BY created_at DESC
                """,
                (tenant_id,),
            ).fetchall()
        return [
            Opportunity(
                id=r[0],
                partner_id=r[1],
                name=r[2],
                stage=r[3],
                amount=float(r[4]),
                expected_close_date=r[5].isoformat() if r[5] else None,
            )
            for r in rows
        ]

    def transition_stage(self, *, tenant_id: str, actor_id: str, opportunity_id: str, new_stage: str) -> Result[Opportunity]:
        row = self._connection.execute(
            """
            SELECT id, partner_id, name, stage, amount, expected_close_date FROM crm.opportunities
            WHERE id = %s AND tenant_id = %s FOR UPDATE
            """,
            (opportunity_id, tenant_id),
        ).fetchone()
        if row is None:
            return Err("NOT_FOUND", f"opportunity {opportunity_id} not found")

        opportunity = Opportunity(
            id=row[0],
            partner_id=row[1],
            name=row[2],
            stage=row[3],
            amount=float(row[4]),
            expected_close_date=row[5].isoformat() if row[5] else None,
        )
        result = transition_opportunity(opportunity, new_stage)
        if isinstance(result, Err):
            return result

        self._connection.execute("UPDATE crm.opportunities SET stage = %s WHERE id = %s", (new_stage, opportunity_id))
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="opportunity.stage_changed",
            entity_type="opportunity",
            entity_id=opportunity_id,
            payload={"from_stage": opportunity.stage, "to_stage": new_stage},
        )
        return result
