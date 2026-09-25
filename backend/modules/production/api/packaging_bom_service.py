from __future__ import annotations

import psycopg
from ulid import ULID

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from modules.production.domain.packaging_bom import (
    PackagingBom,
    PackagingBomLine,
    transition_bom,
    validate_bom_lines,
)


class PackagingBomService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def create_bom(
        self, *, tenant_id: str, actor_id: str, target_product_id: str, lines: tuple[PackagingBomLine, ...]
    ) -> Result[PackagingBom]:
        validation = validate_bom_lines(lines)
        if isinstance(validation, Err):
            return validation

        # FOR UPDATE can't be combined with an aggregate (MAX) in the same query, so lock
        # every existing row for this target product first and compute the next version
        # in Python; a concurrent create_bom() for the same product blocks here until this
        # transaction commits, then sees this row and picks the version after it.
        existing_versions = self._connection.execute(
            """
            SELECT version
            FROM production.packaging_boms
            WHERE tenant_id = %s AND target_product_id = %s
            FOR UPDATE
            """,
            (tenant_id, target_product_id),
        ).fetchall()
        version = max((row[0] for row in existing_versions), default=0) + 1

        bom_id = str(ULID())
        self._connection.execute(
            """
            INSERT INTO production.packaging_boms (id, tenant_id, target_product_id, version, status)
            VALUES (%s, %s, %s, %s, 'draft')
            """,
            (bom_id, tenant_id, target_product_id, version),
        )
        for line in lines:
            self._connection.execute(
                """
                INSERT INTO production.packaging_bom_lines (id, bom_id, tenant_id, component_product_id, quantity_per_unit)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (str(ULID()), bom_id, tenant_id, line.component_product_id, line.quantity_per_unit),
            )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="packaging_bom.created",
            entity_type="packaging_bom",
            entity_id=bom_id,
            payload={"target_product_id": target_product_id, "version": version},
        )
        return Ok(
            PackagingBom(id=bom_id, target_product_id=target_product_id, version=version, status="draft", lines=lines)
        )

    def activate_bom(self, *, tenant_id: str, actor_id: str, bom_id: str) -> Result[PackagingBom]:
        target_row = self._connection.execute(
            "SELECT target_product_id FROM production.packaging_boms WHERE id = %s AND tenant_id = %s",
            (bom_id, tenant_id),
        ).fetchone()
        if target_row is None:
            return Err("NOT_FOUND", f"packaging BOM {bom_id} not found", f"nomenclature d'emballage {bom_id} introuvable")
        target_product_id = target_row[0]

        # Lock every BOM for this target product, not just the one being activated: the
        # "only one active BOM per target product" invariant below spans that whole family,
        # so a concurrent activate_bom() for a sibling draft must serialize against this one
        # instead of racing it (two concurrent activations could otherwise both end up 'active').
        family_rows = self._connection.execute(
            """
            SELECT id, status
            FROM production.packaging_boms
            WHERE tenant_id = %s AND target_product_id = %s
            FOR UPDATE
            """,
            (tenant_id, target_product_id),
        ).fetchall()
        status_by_id = dict(family_rows)
        if bom_id not in status_by_id:
            return Err("NOT_FOUND", f"packaging BOM {bom_id} not found", f"nomenclature d'emballage {bom_id} introuvable")

        bom = PackagingBom(
            id=bom_id, target_product_id=target_product_id, version=0, status=status_by_id[bom_id], lines=()
        )
        result = transition_bom(bom, "active")
        if isinstance(result, Err):
            return result

        self._connection.execute(
            """
            UPDATE production.packaging_boms
            SET status = 'archived'
            WHERE tenant_id = %s AND target_product_id = %s AND status = 'active' AND id != %s
            """,
            (tenant_id, target_product_id, bom_id),
        )
        self._connection.execute("UPDATE production.packaging_boms SET status = 'active' WHERE id = %s", (bom_id,))
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="packaging_bom.activated",
            entity_type="packaging_bom",
            entity_id=bom_id,
            payload={"target_product_id": target_product_id},
        )
        return Ok(self._get_bom(tenant_id, bom_id))

    def archive_bom(self, *, tenant_id: str, actor_id: str, bom_id: str) -> Result[PackagingBom]:
        bom = self._get_bom(tenant_id, bom_id, for_update=True)
        if bom is None:
            return Err("NOT_FOUND", f"packaging BOM {bom_id} not found", f"nomenclature d'emballage {bom_id} introuvable")

        result = transition_bom(bom, "archived")
        if isinstance(result, Err):
            return result

        self._connection.execute("UPDATE production.packaging_boms SET status = 'archived' WHERE id = %s", (bom_id,))
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="packaging_bom.archived",
            entity_type="packaging_bom",
            entity_id=bom_id,
            payload={},
        )
        return Ok(self._get_bom(tenant_id, bom_id))

    def admin_update_bom(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        bom_id: str,
        target_product_id: str | None = None,
        lines: tuple[PackagingBomLine, ...] | None = None,
    ) -> Result[PackagingBom]:
        current = self._get_bom(tenant_id, bom_id, for_update=True)
        if current is None:
            return Err("NOT_FOUND", f"packaging BOM {bom_id} not found", f"nomenclature d'emballage {bom_id} introuvable")

        updated_target_product_id = target_product_id if target_product_id is not None else current.target_product_id
        updated_lines = lines if lines is not None else current.lines
        validation = validate_bom_lines(updated_lines)
        if isinstance(validation, Err):
            return validation

        self._connection.execute(
            "UPDATE production.packaging_boms SET target_product_id = %s WHERE id = %s", (updated_target_product_id, bom_id)
        )
        if lines is not None:
            self._connection.execute("DELETE FROM production.packaging_bom_lines WHERE bom_id = %s", (bom_id,))
            for line in updated_lines:
                self._connection.execute(
                    """
                    INSERT INTO production.packaging_bom_lines (id, bom_id, tenant_id, component_product_id, quantity_per_unit)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (str(ULID()), bom_id, tenant_id, line.component_product_id, line.quantity_per_unit),
                )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="packaging_bom.updated",
            entity_type="packaging_bom",
            entity_id=bom_id,
            payload={"target_product_id": updated_target_product_id, "line_count": len(updated_lines)},
        )
        return Ok(self._get_bom(tenant_id, bom_id))

    def get_bom(self, tenant_id: str, bom_id: str) -> PackagingBom | None:
        return self._get_bom(tenant_id, bom_id)

    def list_boms(
        self, tenant_id: str, target_product_id: str | None = None, status: str | None = None
    ) -> list[PackagingBom]:
        query = "SELECT id FROM production.packaging_boms WHERE tenant_id = %s"
        params: list[object] = [tenant_id]
        if target_product_id is not None:
            query += " AND target_product_id = %s"
            params.append(target_product_id)
        if status is not None:
            query += " AND status = %s"
            params.append(status)

        rows = self._connection.execute(query, params).fetchall()
        boms = [self._get_bom(tenant_id, bom_id) for (bom_id,) in rows]
        return [bom for bom in boms if bom is not None]

    def _get_bom(self, tenant_id: str, bom_id: str, *, for_update: bool = False) -> PackagingBom | None:
        if for_update:
            row = self._connection.execute(
                """
                SELECT id, target_product_id, version, status
                FROM production.packaging_boms
                WHERE id = %s AND tenant_id = %s
                FOR UPDATE
                """,
                (bom_id, tenant_id),
            ).fetchone()
        else:
            row = self._connection.execute(
                """
                SELECT id, target_product_id, version, status
                FROM production.packaging_boms
                WHERE id = %s AND tenant_id = %s
                """,
                (bom_id, tenant_id),
            ).fetchone()
        if row is None:
            return None
        bom_id, target_product_id, version, bom_status = row

        line_rows = self._connection.execute(
            """
            SELECT component_product_id, quantity_per_unit
            FROM production.packaging_bom_lines
            WHERE bom_id = %s AND tenant_id = %s
            """,
            (bom_id, tenant_id),
        ).fetchall()
        lines = tuple(
            PackagingBomLine(component_product_id=component_product_id, quantity_per_unit=float(quantity_per_unit))
            for component_product_id, quantity_per_unit in line_rows
        )
        return PackagingBom(id=bom_id, target_product_id=target_product_id, version=version, status=bom_status, lines=lines)
