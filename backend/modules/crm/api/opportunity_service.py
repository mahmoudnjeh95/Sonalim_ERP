from __future__ import annotations

import datetime

import psycopg
from ulid import ULID

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from core.events.outbox import publish_event
from modules.crm.domain.opportunity import (
    DEFAULT_PROBABILITY_BY_STAGE,
    Opportunity,
    WonLine,
    transition_opportunity,
    validate_amount,
    validate_lost_reason,
    validate_won_lines,
)
from modules.sales.api.service import SalesOrderService
from modules.sales.domain.entities import OrderLine

_OPPORTUNITY_COLUMNS = (
    "id, partner_id, name, stage, amount, expected_close_date, probability, owner_id, priority, lost_reason, created_at, sales_order_id"
)


def _opportunity_from_row(row) -> Opportunity:
    return Opportunity(
        id=row[0],
        partner_id=row[1],
        name=row[2],
        stage=row[3],
        amount=float(row[4]),
        expected_close_date=row[5].isoformat() if row[5] else None,
        probability=row[6],
        owner_id=row[7],
        priority=row[8],
        lost_reason=row[9],
        created_at=row[10].isoformat() if row[10] else None,
        sales_order_id=row[11],
    )


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
        probability: int | None = None,
        owner_id: str | None = None,
        priority: str = "medium",
    ) -> Result[Opportunity]:
        validation = validate_amount(amount)
        if isinstance(validation, Err):
            return validation

        resolved_probability = probability if probability is not None else DEFAULT_PROBABILITY_BY_STAGE["prospecting"]
        opportunity_id = str(ULID())
        inserted = self._connection.execute(
            """
            INSERT INTO crm.opportunities (id, tenant_id, partner_id, name, stage, amount, expected_close_date, probability, owner_id, priority)
            VALUES (%s, %s, %s, %s, 'prospecting', %s, %s, %s, %s, %s)
            RETURNING created_at
            """,
            (opportunity_id, tenant_id, partner_id, name, amount, expected_close_date, resolved_probability, owner_id, priority),
        ).fetchone()
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="opportunity.created",
            entity_type="opportunity",
            entity_id=opportunity_id,
            payload={"partner_id": partner_id, "name": name, "amount": amount, "owner_id": owner_id},
        )
        return Ok(
            Opportunity(
                id=opportunity_id,
                partner_id=partner_id,
                name=name,
                stage="prospecting",
                amount=amount,
                expected_close_date=expected_close_date.isoformat() if expected_close_date else None,
                probability=resolved_probability,
                owner_id=owner_id,
                priority=priority,
                created_at=inserted[0].isoformat() if inserted else None,
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
        probability: int | None = None,
        owner_id: str | None = None,
        priority: str | None = None,
    ) -> Result[Opportunity]:
        row = self._connection.execute(
            f"SELECT {_OPPORTUNITY_COLUMNS} FROM crm.opportunities WHERE id = %s AND tenant_id = %s FOR UPDATE",
            (opportunity_id, tenant_id),
        ).fetchone()
        if row is None:
            return Err("NOT_FOUND", f"opportunity {opportunity_id} not found")

        current = _opportunity_from_row(row)
        updated = Opportunity(
            id=current.id,
            partner_id=partner_id if partner_id is not None else current.partner_id,
            name=name if name is not None else current.name,
            stage=current.stage,
            amount=amount if amount is not None else current.amount,
            expected_close_date=expected_close_date.isoformat() if expected_close_date is not None else current.expected_close_date,
            probability=probability if probability is not None else current.probability,
            owner_id=owner_id if owner_id is not None else current.owner_id,
            priority=priority if priority is not None else current.priority,
            lost_reason=current.lost_reason,
            created_at=current.created_at,
            sales_order_id=current.sales_order_id,
        )
        validation = validate_amount(updated.amount)
        if isinstance(validation, Err):
            return validation

        self._connection.execute(
            """
            UPDATE crm.opportunities SET partner_id = %s, name = %s, amount = %s, expected_close_date = %s,
                   probability = %s, owner_id = %s, priority = %s
            WHERE id = %s AND tenant_id = %s
            """,
            (updated.partner_id, updated.name, updated.amount, updated.expected_close_date, updated.probability, updated.owner_id, updated.priority, opportunity_id, tenant_id),
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="opportunity.updated",
            entity_type="opportunity",
            entity_id=opportunity_id,
            payload={"partner_id": updated.partner_id, "name": updated.name, "amount": updated.amount, "owner_id": updated.owner_id},
        )
        return Ok(updated)

    def list_opportunities(self, *, tenant_id: str, partner_id: str | None = None) -> list[Opportunity]:
        if partner_id is not None:
            rows = self._connection.execute(
                f"""
                SELECT {_OPPORTUNITY_COLUMNS} FROM crm.opportunities
                WHERE tenant_id = %s AND partner_id = %s ORDER BY created_at DESC
                """,
                (tenant_id, partner_id),
            ).fetchall()
        else:
            rows = self._connection.execute(
                f"""
                SELECT {_OPPORTUNITY_COLUMNS} FROM crm.opportunities
                WHERE tenant_id = %s ORDER BY created_at DESC
                """,
                (tenant_id,),
            ).fetchall()
        return [_opportunity_from_row(row) for row in rows]

    def transition_stage(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        opportunity_id: str,
        new_stage: str,
        lost_reason: str | None = None,
        won_lines: list[WonLine] | None = None,
        won_location_id: str | None = None,
        requested_ship_date: datetime.date | None = None,
        correlation_id: str | None = None,
    ) -> Result[Opportunity]:
        row = self._connection.execute(
            f"SELECT {_OPPORTUNITY_COLUMNS} FROM crm.opportunities WHERE id = %s AND tenant_id = %s FOR UPDATE",
            (opportunity_id, tenant_id),
        ).fetchone()
        if row is None:
            return Err("NOT_FOUND", f"opportunity {opportunity_id} not found")

        opportunity = _opportunity_from_row(row)
        if new_stage == "lost":
            reason_validation = validate_lost_reason(lost_reason)
            if isinstance(reason_validation, Err):
                return reason_validation
        if new_stage == "won":
            lines_validation = validate_won_lines(won_lines)
            if isinstance(lines_validation, Err):
                return lines_validation
            if not won_location_id:
                return Err("MISSING_LOCATION", "a location is required to mark an opportunity won")

        result = transition_opportunity(opportunity, new_stage)
        if isinstance(result, Err):
            return result

        resolved_lost_reason = lost_reason if new_stage == "lost" else opportunity.lost_reason

        resolved_sales_order_id = opportunity.sales_order_id
        if new_stage == "won":
            # Direct in-process call (same transaction), not an event: the opportunity
            # can't be marked won without the order that represents what was actually
            # sold, so this needs the immediate result, exactly like SalesOrderService
            # calling StockService synchronously on confirm.
            sales_order = SalesOrderService(self._connection).create_order(
                tenant_id=tenant_id,
                actor_id=actor_id,
                partner_id=opportunity.partner_id,
                location_id=won_location_id,
                lines=[OrderLine(product_id=line.product_id, quantity=line.quantity, unit_price=0.0) for line in won_lines],
                requested_ship_date=requested_ship_date,
                opportunity_id=opportunity_id,
            )
            resolved_sales_order_id = sales_order.id

        result = Ok(
            Opportunity(
                id=result.value.id, partner_id=result.value.partner_id, name=result.value.name, stage=result.value.stage,
                amount=result.value.amount, expected_close_date=result.value.expected_close_date,
                probability=result.value.probability, owner_id=result.value.owner_id, priority=result.value.priority,
                lost_reason=resolved_lost_reason, created_at=result.value.created_at,
                sales_order_id=resolved_sales_order_id,
            )
        )

        self._connection.execute(
            "UPDATE crm.opportunities SET stage = %s, probability = %s, lost_reason = %s, sales_order_id = %s WHERE id = %s",
            (new_stage, result.value.probability, resolved_lost_reason, resolved_sales_order_id, opportunity_id),
        )
        if new_stage in ("won", "lost") and correlation_id is not None:
            payload = {"opportunity_id": opportunity_id, "partner_id": opportunity.partner_id, "name": opportunity.name, "amount": opportunity.amount}
            if new_stage == "won":
                payload["sales_order_id"] = resolved_sales_order_id
            publish_event(
                self._connection,
                event_type=f"crm.opportunity.{new_stage}",
                producer="crm",
                tenant_id=tenant_id,
                correlation_id=correlation_id,
                payload=payload,
            )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="opportunity.stage_changed",
            entity_type="opportunity",
            entity_id=opportunity_id,
            payload={
                "from_stage": opportunity.stage,
                "to_stage": new_stage,
                "lost_reason": resolved_lost_reason,
                "sales_order_id": resolved_sales_order_id,
            },
        )
        return result
