from __future__ import annotations

import psycopg
from ulid import ULID

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from modules.warehouse.domain.entities import Location
from modules.warehouse.domain.site import validate_reparent


def _location_from_row(row) -> Location:
    return Location(
        id=row[0],
        code=row[1],
        name=row[2],
        site_id=row[3],
        location_type=row[4],
        parent_location_id=row[5],
        sequence=row[6],
        is_blocked=row[7],
        blocked_reason=row[8],
    )


_LOCATION_COLUMNS = "id, code, name, site_id, location_type, parent_location_id, sequence, is_blocked, blocked_reason"


class LocationService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def create_location(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        code: str,
        name: str,
        site_id: str | None = None,
        location_type: str = "bin",
        parent_location_id: str | None = None,
        sequence: int | None = None,
        is_blocked: bool = False,
        blocked_reason: str | None = None,
    ) -> Result[Location]:
        """Create a location, optionally a blocked one.

        Quarantine is the reason the is_blocked flag exists: non-conforming product
        has to go somewhere it stays on the books but cannot be sold, and without a
        way to mark a location blocked there is nowhere for it to go.

        `site_id` is optional so callers written before sites existed (the Stock
        tab's own location dialog, today) keep working unchanged -- an omitted
        site_id is filled in by the same DB trigger and formula the 0012
        migration's backfill used, computed here too so the effective site is
        known upfront for the parent-site check below, and so the
        returned/audited value is accurate without a round trip.

        A parent must belong to that same effective site -- get_location_tree's
        depth-first walk only ever descends from that site's own roots, so a
        cross-site parent would silently make this location unreachable from
        any tree view rather than raising anywhere.
        """
        effective_site_id = site_id if site_id is not None else f"default-site-{tenant_id}"
        if parent_location_id is not None:
            parent_row = self._connection.execute(
                "SELECT site_id FROM warehouse.locations WHERE id = %s AND tenant_id = %s",
                (parent_location_id, tenant_id),
            ).fetchone()
            if parent_row is None:
                return Err(
                    "NOT_FOUND", f"parent location {parent_location_id} not found", f"emplacement parent {parent_location_id} introuvable"
                )
            if parent_row[0] != effective_site_id:
                return Err(
                    "CROSS_SITE_PARENT",
                    "a location can only be created under a parent in the same site",
                    "un emplacement ne peut être créé que sous un parent du même site",
                )

        location_id = str(ULID())
        if site_id is not None:
            self._connection.execute(
                """
                INSERT INTO warehouse.locations
                    (id, tenant_id, code, name, site_id, location_type, parent_location_id, sequence, is_blocked, blocked_reason)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (location_id, tenant_id, code, name, site_id, location_type, parent_location_id, sequence, is_blocked, blocked_reason),
            )
        else:
            self._connection.execute(
                """
                INSERT INTO warehouse.locations
                    (id, tenant_id, code, name, location_type, parent_location_id, sequence, is_blocked, blocked_reason)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (location_id, tenant_id, code, name, location_type, parent_location_id, sequence, is_blocked, blocked_reason),
            )
            site_id = f"default-site-{tenant_id}"
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="location.created",
            entity_type="location",
            entity_id=location_id,
            payload={"code": code, "name": name, "site_id": site_id, "location_type": location_type, "is_blocked": is_blocked},
        )
        return Ok(
            Location(
                id=location_id,
                code=code,
                name=name,
                site_id=site_id,
                location_type=location_type,
                parent_location_id=parent_location_id,
                sequence=sequence,
                is_blocked=is_blocked,
                blocked_reason=blocked_reason,
            )
        )

    def list_locations(
        self,
        *,
        tenant_id: str,
        site_id: str | None = None,
        location_type: str | None = None,
        parent_location_id: str | None = None,
    ) -> list[Location]:
        clauses = ["tenant_id = %s"]
        params: list[object] = [tenant_id]
        if site_id is not None:
            clauses.append("site_id = %s")
            params.append(site_id)
        if location_type is not None:
            clauses.append("location_type = %s")
            params.append(location_type)
        if parent_location_id is not None:
            clauses.append("parent_location_id = %s")
            params.append(parent_location_id)
        rows = self._connection.execute(
            f"""
            SELECT {_LOCATION_COLUMNS} FROM warehouse.locations
            WHERE {' AND '.join(clauses)}
            ORDER BY created_at
            """,
            params,
        ).fetchall()
        return [_location_from_row(row) for row in rows]

    def get_location_tree(self, *, tenant_id: str, site_id: str) -> list[Location]:
        """Every location for a site, parents before children within each branch --
        the shape the frontend tree view wants, without re-nesting it here.

        Sorting by parent_location_id itself (as an earlier version of this did)
        does not produce that order: a parent's id has no reliable relationship
        to its children's ids -- ULIDs only sort by creation time, and a parent
        row created a millisecond after another branch's child can still land
        anywhere relative to it. A real depth-first walk from the roots is what
        actually guarantees parents precede their children.
        """
        rows = self._connection.execute(
            f"SELECT {_LOCATION_COLUMNS} FROM warehouse.locations WHERE tenant_id = %s AND site_id = %s",
            (tenant_id, site_id),
        ).fetchall()
        locations = [_location_from_row(row) for row in rows]

        children_by_parent: dict[str | None, list[Location]] = {}
        for location in locations:
            children_by_parent.setdefault(location.parent_location_id, []).append(location)
        for siblings in children_by_parent.values():
            siblings.sort(key=lambda loc: (loc.sequence is None, loc.sequence or 0, loc.name))

        ordered: list[Location] = []

        def visit(parent_id: str | None) -> None:
            for location in children_by_parent.get(parent_id, []):
                ordered.append(location)
                visit(location.id)

        visit(None)
        return ordered

    def update_location(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        location_id: str,
        code: str | None = None,
        name: str | None = None,
        is_blocked: bool | None = None,
        blocked_reason: str | None = None,
    ) -> Result[Location]:
        row = self._connection.execute(
            f"SELECT {_LOCATION_COLUMNS} FROM warehouse.locations WHERE id = %s AND tenant_id = %s",
            (location_id, tenant_id),
        ).fetchone()
        if row is None:
            return Err("NOT_FOUND", f"location {location_id} not found", f"emplacement {location_id} introuvable")
        current = _location_from_row(row)

        updated_code = code if code is not None else current.code
        updated_name = name if name is not None else current.name
        if not updated_code.strip():
            return Err("INVALID_CODE", "code is required", "le code est obligatoire")
        if not updated_name.strip():
            return Err("INVALID_NAME", "name is required", "le nom est obligatoire")

        updated_blocked = is_blocked if is_blocked is not None else current.is_blocked
        updated_reason = blocked_reason if blocked_reason is not None else current.blocked_reason
        self._connection.execute(
            """
            UPDATE warehouse.locations SET code = %s, name = %s, is_blocked = %s, blocked_reason = %s
            WHERE id = %s AND tenant_id = %s
            """,
            (updated_code, updated_name, updated_blocked, updated_reason, location_id, tenant_id),
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="location.updated",
            entity_type="location",
            entity_id=location_id,
            payload={"code": updated_code, "name": updated_name},
        )
        return Ok(
            Location(
                id=location_id,
                code=updated_code,
                name=updated_name,
                site_id=current.site_id,
                location_type=current.location_type,
                parent_location_id=current.parent_location_id,
                sequence=current.sequence,
                is_blocked=updated_blocked,
                blocked_reason=updated_reason,
            )
        )

    def reparent_location(
        self, *, tenant_id: str, actor_id: str, location_id: str, parent_location_id: str | None
    ) -> Result[Location]:
        """Moves a location under a new parent within the same site.

        Same-site only, and only while the location holds no stock -- reparenting
        a bin that already has stock_items rows would silently change what site
        that stock reports under, which is a much bigger decision than a shelf
        move and belongs to a future transfer workflow, not this endpoint.
        """
        row = self._connection.execute(
            f"SELECT {_LOCATION_COLUMNS} FROM warehouse.locations WHERE id = %s AND tenant_id = %s",
            (location_id, tenant_id),
        ).fetchone()
        if row is None:
            return Err("NOT_FOUND", f"location {location_id} not found", f"emplacement {location_id} introuvable")
        current = _location_from_row(row)

        if parent_location_id is not None:
            parent_row = self._connection.execute(
                "SELECT site_id FROM warehouse.locations WHERE id = %s AND tenant_id = %s",
                (parent_location_id, tenant_id),
            ).fetchone()
            if parent_row is None:
                return Err(
                    "NOT_FOUND", f"parent location {parent_location_id} not found", f"emplacement parent {parent_location_id} introuvable"
                )
            if parent_row[0] != current.site_id:
                return Err(
                    "CROSS_SITE_PARENT",
                    "a location can only be reparented within its own site",
                    "un emplacement ne peut être déplacé qu'au sein de son propre site",
                )

        has_stock = self._connection.execute(
            """
            SELECT 1 FROM warehouse.stock_items
            WHERE tenant_id = %s AND location_id = %s
                AND (quantity_on_hand != 0 OR quantity_reserved != 0 OR quantity_in_production != 0)
            LIMIT 1
            """,
            (tenant_id, location_id),
        ).fetchone()
        if has_stock is not None:
            return Err(
                "LOCATION_NOT_EMPTY",
                "cannot reparent a location that still holds stock",
                "impossible de déplacer un emplacement qui contient encore du stock",
            )

        siblings = self._connection.execute(
            "SELECT id, parent_location_id FROM warehouse.locations WHERE tenant_id = %s AND site_id = %s",
            (tenant_id, current.site_id),
        ).fetchall()
        parents_by_id = {sibling_id: parent_id for sibling_id, parent_id in siblings}
        validation = validate_reparent(location_id, parent_location_id, parents_by_id)
        if isinstance(validation, Err):
            return validation

        self._connection.execute(
            "UPDATE warehouse.locations SET parent_location_id = %s WHERE id = %s AND tenant_id = %s",
            (parent_location_id, location_id, tenant_id),
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="location.reparented",
            entity_type="location",
            entity_id=location_id,
            payload={"from_parent_location_id": current.parent_location_id, "to_parent_location_id": parent_location_id},
        )
        return Ok(
            Location(
                id=current.id,
                code=current.code,
                name=current.name,
                site_id=current.site_id,
                location_type=current.location_type,
                parent_location_id=parent_location_id,
                sequence=current.sequence,
                is_blocked=current.is_blocked,
                blocked_reason=current.blocked_reason,
            )
        )
