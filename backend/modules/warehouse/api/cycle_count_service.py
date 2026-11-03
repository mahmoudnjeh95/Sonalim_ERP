from __future__ import annotations

import datetime

import psycopg
from ulid import ULID

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from core.events.outbox import publish_event
from modules.warehouse.api.service import StockService
from modules.warehouse.domain.cycle_count import (
    CycleCount,
    CycleCountLine,
    resolve_count,
    settle_counts,
    transition_cycle_count,
    validate_counted_quantity,
)

_COUNT_COLUMNS = (
    "id, tenant_id, site_id, scope_location_id, count_type, status, scheduled_for, "
    "started_at, completed_at, created_by, created_at"
)
_LINE_COLUMNS = (
    "id, tenant_id, cycle_count_id, location_id, product_id, expected_quantity, counted_quantity, "
    "status, resolution, counted_by, counted_at, resolved_by, resolved_at, count_1, count_2, count_3"
)


def _count_from_row(row) -> CycleCount:
    return CycleCount(
        id=row[0], tenant_id=row[1], site_id=row[2], scope_location_id=row[3], count_type=row[4], status=row[5],
        scheduled_for=row[6], started_at=row[7], completed_at=row[8], created_by=row[9], created_at=row[10],
    )


def _line_from_row(row) -> CycleCountLine:
    return CycleCountLine(
        id=row[0], tenant_id=row[1], cycle_count_id=row[2], location_id=row[3], product_id=row[4],
        expected_quantity=float(row[5]) if row[5] is not None else None,
        counted_quantity=float(row[6]) if row[6] is not None else None,
        status=row[7], resolution=row[8], counted_by=row[9], counted_at=row[10], resolved_by=row[11], resolved_at=row[12],
        count_1=float(row[13]) if row[13] is not None else None,
        count_2=float(row[14]) if row[14] is not None else None,
        count_3=float(row[15]) if row[15] is not None else None,
    )


class CycleCountService:
    """Structured count -> variance -> approval workflow, scoped to a site's
    bins (optionally to just one subtree of them). Reconciles warehouse.
    stock_items the way a physical inventory actually happens, replacing an
    ad hoc single-delta adjust_stock or a privileged full overwrite as the
    only way to correct the books."""

    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection
        self._stock = StockService(connection)

    def create_count(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        site_id: str,
        scope_location_id: str | None = None,
        count_type: str = "scheduled",
        scheduled_for: datetime.date | None = None,
    ) -> Result[CycleCount]:
        if count_type not in ("scheduled", "blind"):
            return Err("INVALID_COUNT_TYPE", "count_type must be 'scheduled' or 'blind'", "count_type doit être 'scheduled' ou 'blind'")

        if scope_location_id is not None:
            scope_row = self._connection.execute(
                "SELECT site_id FROM warehouse.locations WHERE id = %s AND tenant_id = %s",
                (scope_location_id, tenant_id),
            ).fetchone()
            if scope_row is None:
                return Err(
                    "NOT_FOUND", f"location {scope_location_id} not found", f"emplacement {scope_location_id} introuvable"
                )
            if scope_row[0] != site_id:
                return Err(
                    "CROSS_SITE_SCOPE",
                    "the scope location must belong to the given site",
                    "l'emplacement de portée doit appartenir au site indiqué",
                )

        bin_ids = self._bin_ids_in_scope(tenant_id=tenant_id, site_id=site_id, scope_location_id=scope_location_id)
        if not bin_ids:
            return Err("EMPTY_SCOPE", "no bins found in that scope", "aucun casier trouvé dans cette portée")

        stock_rows = self._connection.execute(
            """
            SELECT location_id, product_id, quantity_on_hand FROM warehouse.stock_items
            WHERE tenant_id = %s AND location_id = ANY(%s) AND quantity_on_hand != 0
            """,
            (tenant_id, bin_ids),
        ).fetchall()
        if not stock_rows:
            return Err("EMPTY_SCOPE", "no stock found in that scope to count", "aucun stock trouvé dans cette portée à compter")

        cycle_count_id = str(ULID())
        self._connection.execute(
            """
            INSERT INTO warehouse.cycle_counts (id, tenant_id, site_id, scope_location_id, count_type, scheduled_for, created_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (cycle_count_id, tenant_id, site_id, scope_location_id, count_type, scheduled_for, actor_id),
        )
        for location_id, product_id, on_hand in stock_rows:
            self._connection.execute(
                """
                INSERT INTO warehouse.cycle_count_lines (id, tenant_id, cycle_count_id, location_id, product_id, expected_quantity)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (str(ULID()), tenant_id, cycle_count_id, location_id, product_id, float(on_hand)),
            )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="cycle_count.created",
            entity_type="cycle_count",
            entity_id=cycle_count_id,
            payload={"site_id": site_id, "scope_location_id": scope_location_id, "count_type": count_type, "line_count": len(stock_rows)},
        )
        return self.get_count(tenant_id=tenant_id, cycle_count_id=cycle_count_id)

    def _bin_ids_in_scope(self, *, tenant_id: str, site_id: str, scope_location_id: str | None) -> list[str]:
        """Every bin at or under scope_location_id, or every bin in the site if
        scope_location_id is None. Same depth-first-over-a-parent-map shape as
        LocationService.get_location_tree, walked downward instead of listed."""
        rows = self._connection.execute(
            "SELECT id, location_type, parent_location_id FROM warehouse.locations WHERE tenant_id = %s AND site_id = %s",
            (tenant_id, site_id),
        ).fetchall()
        if scope_location_id is None:
            return [location_id for location_id, location_type, _ in rows if location_type == "bin"]

        by_id = {location_id: (location_type, parent_id) for location_id, location_type, parent_id in rows}
        children_by_parent: dict[str, list[str]] = {}
        for location_id, _, parent_id in rows:
            if parent_id is not None:
                children_by_parent.setdefault(parent_id, []).append(location_id)

        if scope_location_id not in by_id:
            return []

        bins: list[str] = []

        def collect(location_id: str) -> None:
            location_type, _ = by_id[location_id]
            if location_type == "bin":
                bins.append(location_id)
            for child_id in children_by_parent.get(location_id, []):
                collect(child_id)

        collect(scope_location_id)
        return bins

    def get_count(self, *, tenant_id: str, cycle_count_id: str) -> Result[CycleCount]:
        row = self._connection.execute(
            f"SELECT {_COUNT_COLUMNS} FROM warehouse.cycle_counts WHERE id = %s AND tenant_id = %s",
            (cycle_count_id, tenant_id),
        ).fetchone()
        if row is None:
            return Err("NOT_FOUND", f"cycle count {cycle_count_id} not found", f"inventaire {cycle_count_id} introuvable")
        return Ok(_count_from_row(row))

    def list_counts(self, *, tenant_id: str, site_id: str | None = None, status: str | None = None) -> list[CycleCount]:
        clauses = ["tenant_id = %s"]
        params: list[object] = [tenant_id]
        if site_id is not None:
            clauses.append("site_id = %s")
            params.append(site_id)
        if status is not None:
            clauses.append("status = %s")
            params.append(status)
        rows = self._connection.execute(
            f"SELECT {_COUNT_COLUMNS} FROM warehouse.cycle_counts WHERE {' AND '.join(clauses)} ORDER BY created_at DESC",
            params,
        ).fetchall()
        return [_count_from_row(row) for row in rows]

    def list_lines(self, *, tenant_id: str, cycle_count_id: str) -> Result[list[CycleCountLine]]:
        count_result = self.get_count(tenant_id=tenant_id, cycle_count_id=cycle_count_id)
        if isinstance(count_result, Err):
            return count_result
        rows = self._connection.execute(
            f"""
            SELECT {_LINE_COLUMNS} FROM warehouse.cycle_count_lines
            WHERE tenant_id = %s AND cycle_count_id = %s ORDER BY location_id, product_id
            """,
            (tenant_id, cycle_count_id),
        ).fetchall()
        lines = [_line_from_row(row) for row in rows]
        if count_result.value.count_type == "blind":
            lines = [
                line if line.status != "pending" else CycleCountLine(**{**line.__dict__, "expected_quantity": None})
                for line in lines
            ]
        return Ok(lines)

    def _get_line(self, *, tenant_id: str, cycle_count_id: str, line_id: str) -> Result[CycleCountLine]:
        row = self._connection.execute(
            f"SELECT {_LINE_COLUMNS} FROM warehouse.cycle_count_lines WHERE id = %s AND tenant_id = %s AND cycle_count_id = %s",
            (line_id, tenant_id, cycle_count_id),
        ).fetchone()
        if row is None:
            return Err("NOT_FOUND", f"cycle count line {line_id} not found", f"ligne d'inventaire {line_id} introuvable")
        return Ok(_line_from_row(row))

    def _transition(self, *, tenant_id: str, cycle_count_id: str, new_status: str) -> Result[CycleCount]:
        count_result = self.get_count(tenant_id=tenant_id, cycle_count_id=cycle_count_id)
        if isinstance(count_result, Err):
            return count_result
        validation = transition_cycle_count(count_result.value.status, new_status)
        if isinstance(validation, Err):
            return validation
        return count_result

    def start_count(self, *, tenant_id: str, actor_id: str, cycle_count_id: str) -> Result[CycleCount]:
        transition_result = self._transition(tenant_id=tenant_id, cycle_count_id=cycle_count_id, new_status="in_progress")
        if isinstance(transition_result, Err):
            return transition_result
        self._connection.execute(
            "UPDATE warehouse.cycle_counts SET status = 'in_progress', started_at = NOW() WHERE id = %s AND tenant_id = %s",
            (cycle_count_id, tenant_id),
        )
        record_audit(
            self._connection, tenant_id=tenant_id, actor_id=actor_id, action="cycle_count.started",
            entity_type="cycle_count", entity_id=cycle_count_id, payload={},
        )
        return self.get_count(tenant_id=tenant_id, cycle_count_id=cycle_count_id)

    def submit_line_count(
        self, *, tenant_id: str, actor_id: str, cycle_count_id: str, line_id: str, counted_quantity: float
    ) -> Result[CycleCountLine]:
        count_result = self.get_count(tenant_id=tenant_id, cycle_count_id=cycle_count_id)
        if isinstance(count_result, Err):
            return count_result
        if count_result.value.status != "in_progress":
            return Err(
                "INVALID_STATE", "the count must be in progress to record a line", "l'inventaire doit être en cours pour saisir une ligne"
            )
        validation = validate_counted_quantity(counted_quantity)
        if isinstance(validation, Err):
            return validation

        line_result = self._get_line(tenant_id=tenant_id, cycle_count_id=cycle_count_id, line_id=line_id)
        if isinstance(line_result, Err):
            return line_result
        line = line_result.value

        if line.status == "counted":
            return Err("INVALID_STATE", "this line is already counted", "cette ligne est déjà comptée")

        # Counts go into the next free slot: a first count that differs from the books must be
        # confirmed by a second, and two different ones by a third (see settle_counts).
        counts = [line.count_1, line.count_2, line.count_3]
        slot = counts.index(None)
        counts[slot] = counted_quantity
        settled, _ = settle_counts(line.expected_quantity, *counts)
        now = datetime.datetime.now(datetime.timezone.utc)
        if settled is None:
            self._connection.execute(
                f"UPDATE warehouse.cycle_count_lines SET count_{slot + 1} = %s, counted_by = %s, counted_at = %s "
                "WHERE id = %s AND tenant_id = %s",
                (counted_quantity, actor_id, now, line_id, tenant_id),
            )
            resolution = None
        else:
            resolution = resolve_count(expected_quantity=line.expected_quantity, counted_quantity=settled)
            self._connection.execute(
                f"""
                UPDATE warehouse.cycle_count_lines
                SET count_{slot + 1} = %s, counted_quantity = %s, status = 'counted', resolution = %s, counted_by = %s,
                    counted_at = %s, resolved_by = %s, resolved_at = %s
                WHERE id = %s AND tenant_id = %s
                """,
                (counted_quantity, settled, resolution, actor_id, now, actor_id if resolution else None,
                 now if resolution else None, line_id, tenant_id),
            )
        record_audit(
            self._connection, tenant_id=tenant_id, actor_id=actor_id, action="cycle_count_line.counted",
            entity_type="cycle_count_line", entity_id=line_id,
            payload={"expected_quantity": line.expected_quantity, "counted_quantity": counted_quantity,
                     "round": slot + 1, "settled_quantity": settled, "resolution": resolution},
        )
        return self._get_line(tenant_id=tenant_id, cycle_count_id=cycle_count_id, line_id=line_id)

    def resolve_line_variance(
        self, *, tenant_id: str, actor_id: str, cycle_count_id: str, line_id: str, decision: str
    ) -> Result[CycleCountLine]:
        if decision not in ("approve", "reject"):
            return Err("INVALID_DECISION", "decision must be 'approve' or 'reject'", "la décision doit être 'approve' ou 'reject'")

        count_result = self.get_count(tenant_id=tenant_id, cycle_count_id=cycle_count_id)
        if isinstance(count_result, Err):
            return count_result
        if count_result.value.status != "in_progress":
            return Err(
                "INVALID_STATE",
                "the count must be in progress to resolve a variance",
                "l'inventaire doit être en cours pour résoudre un écart",
            )

        line_result = self._get_line(tenant_id=tenant_id, cycle_count_id=cycle_count_id, line_id=line_id)
        if isinstance(line_result, Err):
            return line_result
        line = line_result.value
        if line.status != "counted" or line.resolution is not None:
            return Err(
                "INVALID_STATE",
                "only a counted line with an unresolved variance can be resolved",
                "seule une ligne comptée avec un écart non résolu peut être résolue",
            )

        if decision == "approve":
            delta = line.counted_quantity - line.expected_quantity
            if delta != 0:
                adjust_result = self._stock.adjust_stock(
                    tenant_id=tenant_id,
                    product_id=line.product_id,
                    location_id=line.location_id,
                    delta=delta,
                    reason=f"cycle_count:{cycle_count_id}",
                    actor_id=actor_id,
                    reference=f"cycle_count:{cycle_count_id}",
                    _from_inventory=True,  # the count's own adjustment is the one write its freeze lets through
                )
                if isinstance(adjust_result, Err):
                    return adjust_result

        resolution = "approved" if decision == "approve" else "rejected"
        now = datetime.datetime.now(datetime.timezone.utc)
        self._connection.execute(
            "UPDATE warehouse.cycle_count_lines SET resolution = %s, resolved_by = %s, resolved_at = %s WHERE id = %s AND tenant_id = %s",
            (resolution, actor_id, now, line_id, tenant_id),
        )
        record_audit(
            self._connection, tenant_id=tenant_id, actor_id=actor_id, action="cycle_count_line.resolved",
            entity_type="cycle_count_line", entity_id=line_id,
            payload={"decision": decision, "expected_quantity": line.expected_quantity, "counted_quantity": line.counted_quantity},
        )
        return self._get_line(tenant_id=tenant_id, cycle_count_id=cycle_count_id, line_id=line_id)

    def complete_count(self, *, tenant_id: str, actor_id: str, cycle_count_id: str, correlation_id: str) -> Result[CycleCount]:
        transition_result = self._transition(tenant_id=tenant_id, cycle_count_id=cycle_count_id, new_status="completed")
        if isinstance(transition_result, Err):
            return transition_result

        unresolved = self._connection.execute(
            "SELECT count(*) FROM warehouse.cycle_count_lines WHERE tenant_id = %s AND cycle_count_id = %s AND resolution IS NULL",
            (tenant_id, cycle_count_id),
        ).fetchone()[0]
        if unresolved > 0:
            return Err(
                "LINES_UNRESOLVED",
                f"{unresolved} line(s) still need a decision",
                f"{unresolved} ligne(s) attendent encore une décision",
            )

        self._connection.execute(
            "UPDATE warehouse.cycle_counts SET status = 'completed', completed_at = NOW() WHERE id = %s AND tenant_id = %s",
            (cycle_count_id, tenant_id),
        )
        line_count, variance_count = self._connection.execute(
            """
            SELECT count(*), count(*) FILTER (WHERE resolution != 'matched')
            FROM warehouse.cycle_count_lines WHERE tenant_id = %s AND cycle_count_id = %s
            """,
            (tenant_id, cycle_count_id),
        ).fetchone()

        record_audit(
            self._connection, tenant_id=tenant_id, actor_id=actor_id, action="cycle_count.completed",
            entity_type="cycle_count", entity_id=cycle_count_id,
            payload={"line_count": line_count, "variance_count": variance_count},
        )
        publish_event(
            self._connection,
            event_type="warehouse.cycle_count.completed",
            producer="warehouse",
            tenant_id=tenant_id,
            correlation_id=correlation_id,
            payload={
                "cycle_count_id": cycle_count_id,
                "site_id": transition_result.value.site_id,
                "line_count": line_count,
                "variance_count": variance_count,
            },
        )
        return self.get_count(tenant_id=tenant_id, cycle_count_id=cycle_count_id)

    def cancel_count(self, *, tenant_id: str, actor_id: str, cycle_count_id: str) -> Result[CycleCount]:
        transition_result = self._transition(tenant_id=tenant_id, cycle_count_id=cycle_count_id, new_status="cancelled")
        if isinstance(transition_result, Err):
            return transition_result
        self._connection.execute(
            "UPDATE warehouse.cycle_counts SET status = 'cancelled' WHERE id = %s AND tenant_id = %s",
            (cycle_count_id, tenant_id),
        )
        record_audit(
            self._connection, tenant_id=tenant_id, actor_id=actor_id, action="cycle_count.cancelled",
            entity_type="cycle_count", entity_id=cycle_count_id, payload={},
        )
        return self.get_count(tenant_id=tenant_id, cycle_count_id=cycle_count_id)

    def admin_update_count(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        cycle_count_id: str,
        scheduled_for: datetime.date | None = None,
        count_type: str | None = None,
    ) -> Result[CycleCount]:
        count_result = self.get_count(tenant_id=tenant_id, cycle_count_id=cycle_count_id)
        if isinstance(count_result, Err):
            return count_result
        current = count_result.value

        updated_type = count_type if count_type is not None else current.count_type
        if updated_type not in ("scheduled", "blind"):
            return Err("INVALID_COUNT_TYPE", "count_type must be 'scheduled' or 'blind'", "count_type doit être 'scheduled' ou 'blind'")
        updated_scheduled_for = scheduled_for if scheduled_for is not None else current.scheduled_for

        self._connection.execute(
            "UPDATE warehouse.cycle_counts SET scheduled_for = %s, count_type = %s WHERE id = %s AND tenant_id = %s",
            (updated_scheduled_for, updated_type, cycle_count_id, tenant_id),
        )
        record_audit(
            self._connection, tenant_id=tenant_id, actor_id=actor_id, action="cycle_count.updated",
            entity_type="cycle_count", entity_id=cycle_count_id,
            payload={"scheduled_for": str(updated_scheduled_for) if updated_scheduled_for else None, "count_type": updated_type},
        )
        return self.get_count(tenant_id=tenant_id, cycle_count_id=cycle_count_id)
