from __future__ import annotations

import dataclasses
import datetime

import psycopg
from ulid import ULID

from core.atomic import atomic
from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from core.events.outbox import publish_event
from modules.warehouse.api.service import StockService, count_start_lock_key
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
    "started_at, completed_at, created_by, created_at, number"
)
_LINE_COLUMNS = (
    "id, tenant_id, cycle_count_id, location_id, product_id, expected_quantity, counted_quantity, "
    "status, resolution, counted_by, counted_at, resolved_by, resolved_at, count_1, count_2, count_3"
)


def _count_from_row(row) -> CycleCount:
    return CycleCount(
        id=row[0], tenant_id=row[1], site_id=row[2], scope_location_id=row[3], count_type=row[4], status=row[5],
        scheduled_for=row[6], started_at=row[7], completed_at=row[8], created_by=row[9], created_at=row[10], number=row[11],
    )


def _line_from_row(row) -> CycleCountLine:
    raw_counts = (row[13], row[14], row[15])
    return CycleCountLine(
        id=row[0], tenant_id=row[1], cycle_count_id=row[2], location_id=row[3], product_id=row[4],
        expected_quantity=float(row[5]) if row[5] is not None else None,
        counted_quantity=float(row[6]) if row[6] is not None else None,
        status=row[7], resolution=row[8], counted_by=row[9], counted_at=row[10], resolved_by=row[11], resolved_at=row[12],
        count_1=float(row[13]) if row[13] is not None else None,
        count_2=float(row[14]) if row[14] is not None else None,
        count_3=float(row[15]) if row[15] is not None else None,
        counts_recorded=sum(count is not None for count in raw_counts),
    )


def _as_shown(line: CycleCountLine, count_type: str) -> CycleCountLine:
    """What a reader may see of a line. Until it settles, a count already entered stays hidden from
    whoever enters the next one, and a blind count hides the books as well."""
    if line.status != "pending":
        return line
    masked = dataclasses.replace(line, count_1=None, count_2=None, count_3=None)
    return dataclasses.replace(masked, expected_quantity=None) if count_type == "blind" else masked


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

        location_ids = self._location_ids_in_scope(tenant_id=tenant_id, site_id=site_id, scope_location_id=scope_location_id)
        if not location_ids:
            return Err("EMPTY_SCOPE", "no locations found in that scope", "aucun emplacement trouvé dans cette portée")

        has_stock = self._connection.execute(
            "SELECT 1 FROM warehouse.stock_items WHERE tenant_id = %s AND location_id = ANY(%s) AND quantity_on_hand != 0 LIMIT 1",
            (tenant_id, location_ids),
        ).fetchone()
        if has_stock is None:
            return Err("EMPTY_SCOPE", "no stock found in that scope to count", "aucun stock trouvé dans cette portée à compter")

        cycle_count_id = str(ULID())
        number = self._next_number(tenant_id)
        self._connection.execute(
            """
            INSERT INTO warehouse.cycle_counts (id, tenant_id, site_id, scope_location_id, count_type, scheduled_for, created_by, number)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (cycle_count_id, tenant_id, site_id, scope_location_id, count_type, scheduled_for, actor_id, number),
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="cycle_count.created",
            entity_type="cycle_count",
            entity_id=cycle_count_id,
            payload={"number": number, "site_id": site_id, "scope_location_id": scope_location_id, "count_type": count_type},
        )
        return self.get_count(tenant_id=tenant_id, cycle_count_id=cycle_count_id)

    def _next_number(self, tenant_id: str) -> str:
        year = datetime.datetime.now(datetime.timezone.utc).year
        row = self._connection.execute(
            """
            INSERT INTO warehouse.voucher_counters (tenant_id, voucher_type, year, last_number) VALUES (%s, 'cycle_count', %s, 1)
            ON CONFLICT (tenant_id, voucher_type, year)
            DO UPDATE SET last_number = warehouse.voucher_counters.last_number + 1
            RETURNING last_number
            """,
            (tenant_id, year),
        ).fetchone()
        return f"INV-{year}-{row[0]:06d}"

    def _location_ids_in_scope(self, *, tenant_id: str, site_id: str, scope_location_id: str | None) -> list[str]:
        """Every location at or under scope_location_id, or every location in the site if it is None.
        Not only bins: StockService accepts stock on a zone or a rack, and that stock is real, so it is
        counted. This is exactly the set StockService._assert_not_frozen freezes, so nothing in a
        count's scope is both held still and left uncounted."""
        rows = self._connection.execute(
            "SELECT id, parent_location_id FROM warehouse.locations WHERE tenant_id = %s AND site_id = %s",
            (tenant_id, site_id),
        ).fetchall()
        if scope_location_id is None:
            return [location_id for location_id, _ in rows]

        children_by_parent: dict[str, list[str]] = {}
        for location_id, parent_id in rows:
            if parent_id is not None:
                children_by_parent.setdefault(parent_id, []).append(location_id)

        if scope_location_id not in {location_id for location_id, _ in rows}:
            return []

        found: list[str] = []

        def collect(location_id: str) -> None:
            found.append(location_id)
            for child_id in children_by_parent.get(location_id, []):
                collect(child_id)

        collect(scope_location_id)
        return found

    def get_count(self, *, tenant_id: str, cycle_count_id: str, lock: str = "") -> Result[CycleCount]:
        row = self._connection.execute(
            f"SELECT {_COUNT_COLUMNS} FROM warehouse.cycle_counts WHERE id = %s AND tenant_id = %s{lock}",
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
        return Ok([_as_shown(_line_from_row(row), count_result.value.count_type) for row in rows])

    def frozen_scopes(self, *, tenant_id: str) -> list[dict]:
        """What the counts in progress hold still, named for the people whose stock moves are refused."""
        rows = self._connection.execute(
            """
            SELECT cc.id, COALESCE(cc.number, cc.id), COALESCE(l.name, s.name)
            FROM warehouse.cycle_counts cc
            JOIN warehouse.sites s ON s.id = cc.site_id AND s.tenant_id = cc.tenant_id
            LEFT JOIN warehouse.locations l ON l.id = cc.scope_location_id AND l.tenant_id = cc.tenant_id
            WHERE cc.tenant_id = %s AND cc.status = 'in_progress'
            ORDER BY cc.started_at, cc.id
            """,
            (tenant_id,),
        ).fetchall()
        return [{"cycle_count_id": row[0], "number": row[1], "name": row[2]} for row in rows]

    def _get_line(self, *, tenant_id: str, cycle_count_id: str, line_id: str, lock: str = "") -> Result[CycleCountLine]:
        row = self._connection.execute(
            f"SELECT {_LINE_COLUMNS} FROM warehouse.cycle_count_lines WHERE id = %s AND tenant_id = %s AND cycle_count_id = %s{lock}",
            (line_id, tenant_id, cycle_count_id),
        ).fetchone()
        if row is None:
            return Err("NOT_FOUND", f"cycle count line {line_id} not found", f"ligne d'inventaire {line_id} introuvable")
        return Ok(_line_from_row(row))

    def _transition(self, *, tenant_id: str, cycle_count_id: str, new_status: str) -> Result[CycleCount]:
        # FOR UPDATE: a status change waits for any count or decision under way (they hold FOR SHARE).
        count_result = self.get_count(tenant_id=tenant_id, cycle_count_id=cycle_count_id, lock=" FOR UPDATE")
        if isinstance(count_result, Err):
            return count_result
        validation = transition_cycle_count(count_result.value.status, new_status)
        if isinstance(validation, Err):
            return validation
        return count_result

    @atomic
    def start_count(self, *, tenant_id: str, actor_id: str, cycle_count_id: str) -> Result[CycleCount]:
        """Freezes the scope and only then reads the books, so the expected quantities are the ones
        that hold while counting. Lines left by an older draft are replaced for the same reason."""
        transition_result = self._transition(tenant_id=tenant_id, cycle_count_id=cycle_count_id, new_status="in_progress")
        if isinstance(transition_result, Err):
            return transition_result
        count = transition_result.value

        # Exclusive against every stock writer on the site (they hold it shared, see StockService), and
        # against another start: once granted, nothing is half-written and nothing new gets past the freeze.
        self._connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (count_start_lock_key(tenant_id, count.site_id),))
        location_ids = self._location_ids_in_scope(tenant_id=tenant_id, site_id=count.site_id, scope_location_id=count.scope_location_id)
        overlap = self._overlapping_count(tenant_id, count, set(location_ids))
        if overlap is not None:
            return Err(
                "COUNT_SCOPE_OVERLAP",
                f"cycle count {overlap} is in progress on part of this scope; complete or cancel it first",
                f"l'inventaire {overlap} est en cours sur une partie de cette portée ; terminez-le ou annulez-le d'abord",
            )

        self._connection.execute(
            "UPDATE warehouse.cycle_counts SET status = 'in_progress', started_at = NOW() WHERE id = %s AND tenant_id = %s",
            (cycle_count_id, tenant_id),
        )
        stock_rows = self._connection.execute(
            """
            SELECT location_id, product_id, quantity_on_hand FROM warehouse.stock_items
            WHERE tenant_id = %s AND location_id = ANY(%s) AND quantity_on_hand != 0
            """,
            (tenant_id, location_ids),
        ).fetchall()
        if not stock_rows:
            return Err("EMPTY_SCOPE", "no stock found in that scope to count", "aucun stock trouvé dans cette portée à compter")

        self._connection.execute(
            "DELETE FROM warehouse.cycle_count_lines WHERE tenant_id = %s AND cycle_count_id = %s", (tenant_id, cycle_count_id)
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
            self._connection, tenant_id=tenant_id, actor_id=actor_id, action="cycle_count.started",
            entity_type="cycle_count", entity_id=cycle_count_id, payload={"line_count": len(stock_rows)},
        )
        return self.get_count(tenant_id=tenant_id, cycle_count_id=cycle_count_id)

    def _overlapping_count(self, tenant_id: str, count: CycleCount, location_ids: set[str]) -> str | None:
        """Two counts over the same shelf would each adjust it for the same variance."""
        others = self._connection.execute(
            """
            SELECT COALESCE(number, id), scope_location_id FROM warehouse.cycle_counts
            WHERE tenant_id = %s AND site_id = %s AND status = 'in_progress' AND id <> %s
            """,
            (tenant_id, count.site_id, count.id),
        ).fetchall()
        for reference, scope_location_id in others:
            theirs = self._location_ids_in_scope(tenant_id=tenant_id, site_id=count.site_id, scope_location_id=scope_location_id)
            if location_ids.intersection(theirs):
                return reference
        return None

    def add_found_line(
        self, *, tenant_id: str, actor_id: str, cycle_count_id: str, location_id: str, product_id: str
    ) -> Result[CycleCountLine]:
        """A product found on a shelf the books say nothing about. The lines are read from stock rows, so
        it has none: this adds one at an expected 0, and it goes through the same counts and the same
        decision as any other. Approving it creates the stock through the count's own adjustment."""
        count_result = self.get_count(tenant_id=tenant_id, cycle_count_id=cycle_count_id, lock=" FOR SHARE")
        if isinstance(count_result, Err):
            return count_result
        count = count_result.value
        if count.status != "in_progress":
            return Err("INVALID_STATE", "the count must be in progress to add a line", "l'inventaire doit être en cours pour ajouter une ligne")
        in_scope = self._location_ids_in_scope(tenant_id=tenant_id, site_id=count.site_id, scope_location_id=count.scope_location_id)
        if location_id not in in_scope:
            return Err("LOCATION_OUT_OF_SCOPE", "this count does not cover that location", "cet inventaire ne couvre pas cet emplacement")
        product = self._connection.execute(
            "SELECT 1 FROM core.products WHERE id = %s AND tenant_id = %s", (product_id, tenant_id)
        ).fetchone()
        if product is None:
            return Err("NOT_FOUND", f"product {product_id} not found", f"produit {product_id} introuvable")

        line_id = str(ULID())
        inserted = self._connection.execute(
            """
            INSERT INTO warehouse.cycle_count_lines (id, tenant_id, cycle_count_id, location_id, product_id, expected_quantity)
            VALUES (%s, %s, %s, %s, %s, 0)
            ON CONFLICT (tenant_id, cycle_count_id, location_id, product_id) DO NOTHING
            RETURNING id
            """,
            (line_id, tenant_id, cycle_count_id, location_id, product_id),
        ).fetchone()
        if inserted is None:
            return Err(
                "LINE_ALREADY_EXISTS",
                "this product already has a line at that location in this count",
                "ce produit a déjà une ligne à cet emplacement dans cet inventaire",
            )
        record_audit(
            self._connection, tenant_id=tenant_id, actor_id=actor_id, action="cycle_count_line.added",
            entity_type="cycle_count_line", entity_id=line_id, payload={"location_id": location_id, "product_id": product_id},
        )
        added = self._get_line(tenant_id=tenant_id, cycle_count_id=cycle_count_id, line_id=line_id)
        if isinstance(added, Err):
            return added
        return Ok(_as_shown(added.value, count.count_type))

    def submit_line_count(
        self, *, tenant_id: str, actor_id: str, cycle_count_id: str, line_id: str, counted_quantity: float
    ) -> Result[CycleCountLine]:
        count_result = self.get_count(tenant_id=tenant_id, cycle_count_id=cycle_count_id, lock=" FOR SHARE")
        if isinstance(count_result, Err):
            return count_result
        if count_result.value.status != "in_progress":
            return Err(
                "INVALID_STATE", "the count must be in progress to record a line", "l'inventaire doit être en cours pour saisir une ligne"
            )
        validation = validate_counted_quantity(counted_quantity)
        if isinstance(validation, Err):
            return validation

        # FOR UPDATE: two counters on one line must not both take the same slot.
        line_result = self._get_line(tenant_id=tenant_id, cycle_count_id=cycle_count_id, line_id=line_id, lock=" FOR UPDATE")
        if isinstance(line_result, Err):
            return line_result
        line = line_result.value

        if line.status == "counted":
            return Err("INVALID_STATE", "this line is already counted", "cette ligne est déjà comptée")

        # Counts go into the next free slot; settle_counts decides when they are enough.
        counts = [line.count_1, line.count_2, line.count_3]
        slot = counts.index(None)
        counts[slot] = counted_quantity
        settled = settle_counts(*counts)
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
        updated = self._get_line(tenant_id=tenant_id, cycle_count_id=cycle_count_id, line_id=line_id)
        if isinstance(updated, Err):
            return updated
        return Ok(_as_shown(updated.value, count_result.value.count_type))

    def resolve_line_variance(
        self, *, tenant_id: str, actor_id: str, cycle_count_id: str, line_id: str, decision: str
    ) -> Result[CycleCountLine]:
        if decision not in ("approve", "reject"):
            return Err("INVALID_DECISION", "decision must be 'approve' or 'reject'", "la décision doit être 'approve' ou 'reject'")

        count_result = self.get_count(tenant_id=tenant_id, cycle_count_id=cycle_count_id, lock=" FOR SHARE")
        if isinstance(count_result, Err):
            return count_result
        if count_result.value.status != "in_progress":
            return Err(
                "INVALID_STATE",
                "the count must be in progress to resolve a variance",
                "l'inventaire doit être en cours pour résoudre un écart",
            )

        # FOR UPDATE: the second of two simultaneous approvals waits, then finds the line resolved.
        line_result = self._get_line(tenant_id=tenant_id, cycle_count_id=cycle_count_id, line_id=line_id, lock=" FOR UPDATE")
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
                    _for_cycle_count=cycle_count_id,  # the one write this count's own freeze lets through
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
        count_result = self.get_count(tenant_id=tenant_id, cycle_count_id=cycle_count_id, lock=" FOR UPDATE")
        if isinstance(count_result, Err):
            return count_result
        current = count_result.value

        updated_type = count_type if count_type is not None else current.count_type
        if updated_type not in ("scheduled", "blind"):
            return Err("INVALID_COUNT_TYPE", "count_type must be 'scheduled' or 'blind'", "count_type doit être 'scheduled' ou 'blind'")
        # Turning a blind count scheduled mid-way would show the books to whoever is still counting.
        if updated_type != current.count_type and current.status != "draft":
            return Err(
                "INVALID_STATE",
                "the count type can only be changed before the count starts",
                "le type d'inventaire ne peut être modifié qu'avant le démarrage",
            )
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
