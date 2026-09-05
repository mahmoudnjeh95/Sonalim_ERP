from __future__ import annotations

import psycopg
from ulid import ULID

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from core.domain.sequences import next_sequence_value
from core.events.outbox import publish_event
from modules.warehouse.api.service import StockService
from modules.qc.domain.non_conformity import (
    DispositionLine,
    NonConformity,
    transition_non_conformity,
    validate_disposition_lines,
    validate_non_conformity,
)

_NC_COLUMNS = """
    id, reference, of_id, product_id, quantity, source_location_id, defect_type, severity, status,
    quality_report_id, quarantine_location_id, description, corrective_action,
    raised_by, raised_at, closed_by, closed_at
"""


def _row_to_nc(row: tuple) -> NonConformity:
    return NonConformity(
        id=row[0],
        reference=row[1],
        of_id=row[2],
        product_id=row[3],
        quantity=float(row[4]),
        source_location_id=row[5],
        defect_type=row[6],
        severity=row[7],
        status=row[8],
        quality_report_id=row[9],
        quarantine_location_id=row[10],
        description=row[11],
        corrective_action=row[12],
        raised_by=row[13],
        raised_at=row[14],
        closed_by=row[15],
        closed_at=row[16],
    )


class NonConformityService:
    """Quality reaching back into finished stock.

    Raised against an OF whether or not it is still open — a closed OF must still
    accept a non-conformity, because the follow-up window outlives production and
    a defect is usually found after the run has finished.

    Raising a ticket segregates the product into a blocked location in the same
    transaction, so it stops being sellable the moment it is pulled rather than
    whenever someone gets round to a second step. Disposition takes it back out
    again — never a straight write-off, and never a second deduction of the
    packaging that already left stock at conditionnement.
    """

    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    # ---- reads -----------------------------------------------------------

    def _load(self, *, tenant_id: str, non_conformity_id: str, for_update: bool = False) -> NonConformity | None:
        row = self._connection.execute(
            f"""
            SELECT {_NC_COLUMNS} FROM qc.non_conformities
            WHERE id = %s AND tenant_id = %s
            {'FOR UPDATE' if for_update else ''}
            """,
            (non_conformity_id, tenant_id),
        ).fetchone()
        return _row_to_nc(row) if row is not None else None

    def get_non_conformity(self, *, tenant_id: str, non_conformity_id: str) -> dict | None:
        non_conformity = self._load(tenant_id=tenant_id, non_conformity_id=non_conformity_id)
        if non_conformity is None:
            return None
        return {
            "non_conformity": non_conformity,
            "dispositions": self.list_dispositions(tenant_id=tenant_id, non_conformity_id=non_conformity_id),
        }

    def list_non_conformities(
        self, *, tenant_id: str, of_id: str | None = None, status: str | None = None
    ) -> list[NonConformity]:
        clauses = ["tenant_id = %s"]
        params: list[object] = [tenant_id]
        if of_id is not None:
            clauses.append("of_id = %s")
            params.append(of_id)
        if status is not None:
            clauses.append("status = %s")
            params.append(status)
        rows = self._connection.execute(
            f"SELECT {_NC_COLUMNS} FROM qc.non_conformities WHERE {' AND '.join(clauses)} ORDER BY raised_at DESC",
            params,
        ).fetchall()
        return [_row_to_nc(row) for row in rows]

    def count_open_for_of(self, *, tenant_id: str, of_id: str) -> int:
        """Tickets not yet closed for an OF.

        Reported when an OF is checked for closure, but never a bar to it: a
        non-conformity is usually found after the run has finished, and must keep
        working against a closed order.
        """
        return int(
            self._connection.execute(
                "SELECT count(*) FROM qc.non_conformities WHERE tenant_id = %s AND of_id = %s AND status <> 'closed'",
                (tenant_id, of_id),
            ).fetchone()[0]
        )

    def get_rejected_quantity_for_of(self, *, tenant_id: str, of_id: str, product_id: str) -> dict:
        """How much of an OF's finished product quality has taken off the market.

        Phase 9, decision 21. Production calls this to compute the ecart net; it
        must never join into qc's tables, so the rule about what counts lives here
        with the tables it reads.

        The rule is **what is out of sellable stock, less what came back** — not
        "dispositioned only", which would have understated every case still sitting
        in quarantine. Through that window the product genuinely is not sellable,
        so it subtracts:

        * `raised` and `quarantined` — out of stock, fate undecided. The whole
          ticket quantity subtracts, and is also reported as `undecided` so a
          screen can say "of which 200 awaiting a decision" rather than letting an
          open case read as a permanent loss.
        * `dispositioned` and `closed` — only the product lines sent to regrind or
          declared dechet. `return_to_stock` and `rework` come back and must not
          subtract.

        Only `component = 'product'` counts: film and carton lines are packaging
        already deducted at conditionnement (locked decision 8), and adding them
        to a packet count would be adding two different things.
        """
        undecided = float(
            self._connection.execute(
                """
                SELECT COALESCE(SUM(quantity), 0) FROM qc.non_conformities
                WHERE tenant_id = %s AND of_id = %s AND product_id = %s
                  AND status IN ('raised', 'quarantined')
                """,
                (tenant_id, of_id, product_id),
            ).fetchone()[0]
        )

        settled = float(
            self._connection.execute(
                """
                SELECT COALESCE(SUM(d.quantity), 0)
                FROM qc.nc_dispositions d
                JOIN qc.non_conformities n ON n.id = d.non_conformity_id AND n.tenant_id = d.tenant_id
                WHERE d.tenant_id = %s AND n.of_id = %s AND n.product_id = %s
                  AND n.status IN ('dispositioned', 'closed')
                  AND d.component = 'product'
                  AND d.disposition IN ('regrind', 'dechet')
                """,
                (tenant_id, of_id, product_id),
            ).fetchone()[0]
        )

        return {
            "subtractable": undecided + settled,
            "undecided": undecided,
            "settled": settled,
        }

    def list_dispositions(self, *, tenant_id: str, non_conformity_id: str) -> list[DispositionLine]:
        rows = self._connection.execute(
            """
            SELECT component, disposition, quantity, note FROM qc.nc_dispositions
            WHERE tenant_id = %s AND non_conformity_id = %s ORDER BY created_at
            """,
            (tenant_id, non_conformity_id),
        ).fetchall()
        return [
            DispositionLine(component=r[0], disposition=r[1], quantity=float(r[2]), note=r[3])
            for r in rows
        ]

    def disposition_summary(
        self, *, tenant_id: str, date_from: str | None = None, date_to: str | None = None
    ) -> list[dict]:
        """Where rejected product actually ended up — recovered or scrapped.

        Restricted to the `product` component: film, carton and tape lines are
        counted in their own units (metres, pieces), and product in whatever
        the finished good is stocked in, so summing quantity across components
        would repeat the exact cross-unit mistake the waste ratio elsewhere in
        this codebase was built to avoid. Product-only keeps every summed row
        in one comparable unit, which is what makes a percentage of it honest.
        """
        clauses = ["d.tenant_id = %s", "d.component = 'product'"]
        params: list[object] = [tenant_id]
        if date_from is not None:
            clauses.append("nc.raised_at >= %s")
            params.append(date_from)
        if date_to is not None:
            clauses.append("nc.raised_at <= %s")
            params.append(date_to)

        rows = self._connection.execute(
            f"""
            SELECT d.disposition, COALESCE(SUM(d.quantity), 0), count(*)
            FROM qc.nc_dispositions d
            JOIN qc.non_conformities nc ON nc.id = d.non_conformity_id AND nc.tenant_id = d.tenant_id
            WHERE {' AND '.join(clauses)}
            GROUP BY d.disposition
            """,
            params,
        ).fetchall()
        return [{"disposition": disposition, "quantity": float(quantity), "count": int(count)} for disposition, quantity, count in rows]

    # ---- writes ----------------------------------------------------------

    def raise_non_conformity(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        of_id: str,
        product_id: str,
        quantity: float,
        source_location_id: str,
        defect_type: str,
        correlation_id: str,
        # Where the pulled product is held. Required: decision 9 puts
        # non-conforming product into a blocked location the moment it is pulled,
        # so there is never a window where it is rejected on paper but still
        # sellable in the system.
        quarantine_location_id: str,
        severity: str = "minor",
        quality_report_id: str | None = None,
        description: str | None = None,
    ) -> Result[NonConformity]:
        validation = validate_non_conformity(
            product_id=product_id,
            quantity=quantity,
            source_location_id=source_location_id,
            defect_type=defect_type,
            severity=severity,
        )
        if isinstance(validation, Err):
            return validation
        if not of_id.strip():
            return Err("MISSING_OF", "a non-conformity must name the work order the product came from")
        if not quarantine_location_id.strip():
            return Err("MISSING_LOCATION", "a non-conformity must name the blocked location the product is held in")

        non_conformity_id = str(ULID())
        reference = next_sequence_value(self._connection, tenant_id=tenant_id, name="qc.non_conformities", prefix="NC-")
        self._connection.execute(
            """
            INSERT INTO qc.non_conformities
                (id, tenant_id, reference, of_id, quality_report_id, product_id, quantity, source_location_id,
                 quarantine_location_id, defect_type, severity, status, description, raised_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'quarantined', %s, %s)
            """,
            (
                non_conformity_id,
                tenant_id,
                reference,
                of_id,
                quality_report_id,
                product_id,
                quantity,
                source_location_id,
                quarantine_location_id,
                defect_type,
                severity,
                description,
                actor_id,
            ),
        )

        # The stock movement that makes the segregation real rather than a label.
        segregated = StockService(self._connection).transfer_to_quarantine(
            tenant_id=tenant_id,
            product_id=product_id,
            from_location_id=source_location_id,
            quarantine_location_id=quarantine_location_id,
            quantity=quantity,
            correlation_id=correlation_id,
            reference=f"non_conformity:{non_conformity_id}",
            actor_id=actor_id,
            source_type="qc.non_conformity",
            source_id=non_conformity_id,
            of_id=of_id,
        )
        if isinstance(segregated, Err):
            return segregated
        publish_event(
            self._connection,
            event_type="qc.non_conformity.raised",
            producer="qc",
            tenant_id=tenant_id,
            correlation_id=correlation_id,
            payload={
                "non_conformity_id": non_conformity_id,
                "of_id": of_id,
                "product_id": product_id,
                "quantity": quantity,
                "location_id": source_location_id,
            },
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="non_conformity.raised",
            entity_type="non_conformity",
            entity_id=non_conformity_id,
            payload={
                "of_id": of_id,
                "product_id": product_id,
                "quantity": quantity,
                "defect_type": defect_type,
                "severity": severity,
            },
        )
        return Ok(self._load(tenant_id=tenant_id, non_conformity_id=non_conformity_id))  # type: ignore[arg-type]

    def disposition(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        non_conformity_id: str,
        lines: tuple[DispositionLine, ...],
        correlation_id: str,
    ) -> Result[dict]:
        """Decide where each component of the rejected product goes.

        The published event is what production consumes (Phase 5) to write the
        rebroyat scrap record — qc never writes into production's schema.
        """
        validation = validate_disposition_lines(lines)
        if isinstance(validation, Err):
            return validation

        current = self._load(tenant_id=tenant_id, non_conformity_id=non_conformity_id, for_update=True)
        if current is None:
            return Err("NOT_FOUND", f"non-conformity {non_conformity_id} not found")

        moved = transition_non_conformity(current, "dispositioned")
        if isinstance(moved, Err):
            return moved

        for line in lines:
            self._connection.execute(
                """
                INSERT INTO qc.nc_dispositions (id, tenant_id, non_conformity_id, component, disposition, quantity, note)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    str(ULID()),
                    tenant_id,
                    non_conformity_id,
                    line.component,
                    line.disposition,
                    line.quantity,
                    line.note,
                ),
            )
        self._connection.execute(
            "UPDATE qc.non_conformities SET status = 'dispositioned', updated_at = NOW() WHERE id = %s",
            (non_conformity_id,),
        )

        # The finished product leaves quarantine. Nothing else moves: the film,
        # carton and tape inside it left stock when the conditionnement report was
        # validated, and are recorded as déchet rather than deducted again.
        if current.quarantine_location_id:
            released = StockService(self._connection).release_from_quarantine(
                tenant_id=tenant_id,
                product_id=current.product_id,
                quarantine_location_id=current.quarantine_location_id,
                quantity=current.quantity,
                correlation_id=correlation_id,
                reference=f"non_conformity:{non_conformity_id}",
                actor_id=actor_id,
                source_type="qc.non_conformity_disposition",
                source_id=non_conformity_id,
                of_id=current.of_id,
            )
            if isinstance(released, Err):
                return released

        publish_event(
            self._connection,
            event_type="qc.non_conformity.dispositioned",
            producer="qc",
            tenant_id=tenant_id,
            correlation_id=correlation_id,
            payload={
                "non_conformity_id": non_conformity_id,
                "of_id": current.of_id,
                "product_id": current.product_id,
                "lines": [
                    {
                        "component": line.component,
                        "disposition": line.disposition,
                        "quantity": line.quantity,
                    }
                    for line in lines
                ],
            },
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="non_conformity.dispositioned",
            entity_type="non_conformity",
            entity_id=non_conformity_id,
            payload={
                "lines": [
                    {"component": line.component, "disposition": line.disposition, "quantity": line.quantity}
                    for line in lines
                ]
            },
        )
        return Ok(
            {
                "non_conformity": self._load(tenant_id=tenant_id, non_conformity_id=non_conformity_id),
                "dispositions": self.list_dispositions(tenant_id=tenant_id, non_conformity_id=non_conformity_id),
            }
        )

    def close(
        self, *, tenant_id: str, actor_id: str, non_conformity_id: str, corrective_action: str
    ) -> Result[NonConformity]:
        if not corrective_action.strip():
            return Err("MISSING_CORRECTIVE_ACTION", "closing a non-conformity requires its corrective action")

        current = self._load(tenant_id=tenant_id, non_conformity_id=non_conformity_id, for_update=True)
        if current is None:
            return Err("NOT_FOUND", f"non-conformity {non_conformity_id} not found")

        moved = transition_non_conformity(current, "closed")
        if isinstance(moved, Err):
            return moved

        self._connection.execute(
            """
            UPDATE qc.non_conformities
            SET status = 'closed', corrective_action = %s, closed_by = %s, closed_at = NOW(), updated_at = NOW()
            WHERE id = %s
            """,
            (corrective_action, actor_id, non_conformity_id),
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="non_conformity.closed",
            entity_type="non_conformity",
            entity_id=non_conformity_id,
            payload={"corrective_action": corrective_action},
        )
        return Ok(self._load(tenant_id=tenant_id, non_conformity_id=non_conformity_id))  # type: ignore[arg-type]

    def admin_update_non_conformity(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        non_conformity_id: str,
        quantity: float | None = None,
        defect_type: str | None = None,
        severity: str | None = None,
        description: str | None = None,
        corrective_action: str | None = None,
    ) -> Result[NonConformity]:
        """Edit-in-place, gated by qc.admin_non_conformities.

        Allowed at any status: the elevated permission is what limits the blast
        radius, not a state check.
        """
        current = self._load(tenant_id=tenant_id, non_conformity_id=non_conformity_id, for_update=True)
        if current is None:
            return Err("NOT_FOUND", f"non-conformity {non_conformity_id} not found")

        updated_quantity = quantity if quantity is not None else current.quantity
        updated_defect = defect_type if defect_type is not None else current.defect_type
        updated_severity = severity if severity is not None else current.severity

        validation = validate_non_conformity(
            product_id=current.product_id,
            quantity=updated_quantity,
            source_location_id=current.source_location_id,
            defect_type=updated_defect,
            severity=updated_severity,
        )
        if isinstance(validation, Err):
            return validation

        self._connection.execute(
            """
            UPDATE qc.non_conformities
            SET quantity = %s, defect_type = %s, severity = %s, description = %s, corrective_action = %s, updated_at = NOW()
            WHERE id = %s
            """,
            (
                updated_quantity,
                updated_defect,
                updated_severity,
                description if description is not None else current.description,
                corrective_action if corrective_action is not None else current.corrective_action,
                non_conformity_id,
            ),
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="non_conformity.updated",
            entity_type="non_conformity",
            entity_id=non_conformity_id,
            payload={
                "quantity": updated_quantity,
                "defect_type": updated_defect,
                "severity": updated_severity,
            },
        )
        return Ok(self._load(tenant_id=tenant_id, non_conformity_id=non_conformity_id))  # type: ignore[arg-type]
