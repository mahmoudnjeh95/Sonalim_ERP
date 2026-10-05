from __future__ import annotations

import psycopg
from ulid import ULID

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from modules.warehouse.domain.entities import Site
from modules.warehouse.domain.site import validate_site_code

_SITE_COLUMNS = "id, tenant_id, code, name, address, is_active"


def _site_from_row(row) -> Site:
    return Site(id=row[0], tenant_id=row[1], code=row[2], name=row[3], address=row[4], is_active=row[5])


class SiteService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def create_site(
        self, *, tenant_id: str, actor_id: str, code: str, name: str, address: str | None = None
    ) -> Result[Site]:
        validation = validate_site_code(code)
        if isinstance(validation, Err):
            return validation
        code = validation.value
        if not name.strip():
            return Err("INVALID_NAME", "name is required", "le nom est obligatoire")

        site_id = str(ULID())
        try:
            self._connection.execute(
                "INSERT INTO warehouse.sites (id, tenant_id, code, name, address) VALUES (%s, %s, %s, %s, %s)",
                (site_id, tenant_id, code, name, address),
            )
        except psycopg.errors.UniqueViolation:
            return Err("DUPLICATE_CODE", f"a site with code {code} already exists", f"un site avec le code {code} existe déjà")
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="site.created",
            entity_type="site",
            entity_id=site_id,
            payload={"code": code, "name": name},
        )
        return Ok(Site(id=site_id, tenant_id=tenant_id, code=code, name=name, address=address, is_active=True))

    def list_sites(self, *, tenant_id: str, include_inactive: bool = True) -> list[Site]:
        clauses = ["tenant_id = %s"]
        params: list[object] = [tenant_id]
        if not include_inactive:
            clauses.append("is_active")
        rows = self._connection.execute(
            f"SELECT {_SITE_COLUMNS} FROM warehouse.sites WHERE {' AND '.join(clauses)} ORDER BY created_at",
            params,
        ).fetchall()
        return [_site_from_row(row) for row in rows]

    def update_site(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        site_id: str,
        code: str | None = None,
        name: str | None = None,
        address: str | None = None,
        is_active: bool | None = None,
    ) -> Result[Site]:
        row = self._connection.execute(
            f"SELECT {_SITE_COLUMNS} FROM warehouse.sites WHERE id = %s AND tenant_id = %s",
            (site_id, tenant_id),
        ).fetchone()
        if row is None:
            return Err("NOT_FOUND", f"site {site_id} not found", f"site {site_id} introuvable")
        current = _site_from_row(row)

        updated_code = current.code
        if code is not None:
            validation = validate_site_code(code)
            if isinstance(validation, Err):
                return validation
            updated_code = validation.value
        updated_name = name if name is not None else current.name
        if not updated_name.strip():
            return Err("INVALID_NAME", "name is required", "le nom est obligatoire")
        updated_address = address if address is not None else current.address
        updated_active = is_active if is_active is not None else current.is_active

        try:
            self._connection.execute(
                """
                UPDATE warehouse.sites SET code = %s, name = %s, address = %s, is_active = %s
                WHERE id = %s AND tenant_id = %s
                """,
                (updated_code, updated_name, updated_address, updated_active, site_id, tenant_id),
            )
        except psycopg.errors.UniqueViolation:
            return Err(
                "DUPLICATE_CODE", f"a site with code {updated_code} already exists", f"un site avec le code {updated_code} existe déjà"
            )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="site.updated",
            entity_type="site",
            entity_id=site_id,
            payload={"code": updated_code, "name": updated_name, "is_active": updated_active},
        )
        return Ok(
            Site(id=site_id, tenant_id=tenant_id, code=updated_code, name=updated_name, address=updated_address, is_active=updated_active)
        )

    def deactivate_site(self, *, tenant_id: str, actor_id: str, site_id: str) -> Result[Site]:
        """Soft-disable only -- a site is never hard-deleted, the same stance the
        platform already takes for locations themselves."""
        return self.update_site(tenant_id=tenant_id, actor_id=actor_id, site_id=site_id, is_active=False)
