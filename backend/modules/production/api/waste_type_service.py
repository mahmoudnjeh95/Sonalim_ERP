from __future__ import annotations

import psycopg
from ulid import ULID

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from modules.production.domain.production_report import WASTE_CATEGORIES_BY_REPORT_TYPE
from modules.production.domain.waste_type import WASTE_TYPE_REPORT_TYPES, validate_waste_type

_COLUMNS = "id, name, report_type, sort_order, is_active"


def _row_to_dict(row) -> dict:
    return {"id": row[0], "name": row[1], "report_type": row[2], "sort_order": int(row[3]), "is_active": row[4]}


def custom_waste_categories(
    connection: psycopg.Connection, *, tenant_id: str, report_type: str
) -> frozenset[str]:
    """The ids of a tenant's own waste types for one report type.

    Retired types are included on purpose: a report that used one before it was
    retired must stay editable, and refusing its own lines would strand it. The
    form stops offering a retired type; the domain does not stop honouring it.
    """
    rows = connection.execute(
        "SELECT id FROM production.waste_types WHERE tenant_id = %s AND report_type = %s",
        (tenant_id, report_type),
    ).fetchall()
    return frozenset(row[0] for row in rows)


class WasteTypeService:
    """The déchet kinds a plant adds to the built-in ones.

    Deleting one that a line already uses retires it instead: a line stores the
    type's id as its category, so removing the row would leave old reports saying
    something nobody can read. Retiring takes it off the next form and keeps the
    archive legible.

    The built-ins cannot be deleted (they live in code), but a plant can rename
    them, hide them and order them among its own kinds; see
    production.waste_type_builtin_settings.
    """

    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def list_types(
        self, *, tenant_id: str, report_type: str | None = None, include_inactive: bool = True
    ) -> list[dict]:
        clauses = ["tenant_id = %s"]
        params: list[object] = [tenant_id]
        if report_type is not None:
            clauses.append("report_type = %s")
            params.append(report_type)
        if not include_inactive:
            clauses.append("is_active")
        rows = self._connection.execute(
            f"""
            SELECT {_COLUMNS} FROM production.waste_types
            WHERE {' AND '.join(clauses)}
            ORDER BY report_type, sort_order, lower(name)
            """,
            params,
        ).fetchall()
        return [_row_to_dict(row) for row in rows]

    def create_type(
        self, *, tenant_id: str, actor_id: str, name: str, report_type: str, sort_order: int = 0
    ) -> Result[dict]:
        checked = validate_waste_type(name=name, report_type=report_type)
        if isinstance(checked, Err):
            return checked
        name = checked.value

        existing = self._connection.execute(
            "SELECT id, is_active FROM production.waste_types "
            "WHERE tenant_id = %s AND report_type = %s AND lower(name) = lower(%s)",
            (tenant_id, report_type, name),
        ).fetchone()
        if existing is not None:
            # Adding a name that was retired is how an administrator brings a
            # kind back, so it is a reactivation rather than a duplicate.
            if not existing[1]:
                return self.update_type(
                    tenant_id=tenant_id, actor_id=actor_id, waste_type_id=existing[0], is_active=True
                )
            return Err(
                "DUPLICATE_WASTE_TYPE",
                f"a {report_type} waste type called {name!r} already exists",
                f"un type de déchet {report_type} appelé {name!r} existe déjà",
            )

        waste_type_id = str(ULID())
        self._connection.execute(
            "INSERT INTO production.waste_types (id, tenant_id, name, report_type, sort_order) "
            "VALUES (%s, %s, %s, %s, %s)",
            (waste_type_id, tenant_id, name, report_type, sort_order),
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="waste_type.created",
            entity_type="waste_type",
            entity_id=waste_type_id,
            payload={"name": name, "report_type": report_type, "sort_order": sort_order},
        )
        return Ok(self._read(tenant_id=tenant_id, waste_type_id=waste_type_id))

    def update_type(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        waste_type_id: str,
        name: str | None = None,
        sort_order: int | None = None,
        is_active: bool | None = None,
    ) -> Result[dict]:
        """Rename, reorder, retire or bring back a kind. The report it is entered
        on is not editable: lines already filed under it were validated against
        that report."""
        current = self._connection.execute(
            f"SELECT {_COLUMNS} FROM production.waste_types WHERE id = %s AND tenant_id = %s FOR UPDATE",
            (waste_type_id, tenant_id),
        ).fetchone()
        if current is None:
            return Err("NOT_FOUND", f"waste type {waste_type_id} not found", f"type de déchet {waste_type_id} introuvable")
        _, current_name, report_type, current_sort, current_active = current

        new_name = current_name
        if name is not None:
            checked = validate_waste_type(name=name, report_type=report_type)
            if isinstance(checked, Err):
                return checked
            new_name = checked.value
        if new_name.lower() != current_name.lower():
            clash = self._connection.execute(
                "SELECT 1 FROM production.waste_types "
                "WHERE tenant_id = %s AND report_type = %s AND lower(name) = lower(%s) AND id <> %s",
                (tenant_id, report_type, new_name, waste_type_id),
            ).fetchone()
            if clash is not None:
                return Err(
                    "DUPLICATE_WASTE_TYPE",
                    f"a {report_type} waste type called {new_name!r} already exists",
                    f"un type de déchet {report_type} appelé {new_name!r} existe déjà",
                )

        new_sort = int(current_sort) if sort_order is None else sort_order
        new_active = current_active if is_active is None else is_active
        self._connection.execute(
            "UPDATE production.waste_types SET name = %s, sort_order = %s, is_active = %s, updated_at = NOW() "
            "WHERE id = %s AND tenant_id = %s",
            (new_name, new_sort, new_active, waste_type_id, tenant_id),
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="waste_type.updated",
            entity_type="waste_type",
            entity_id=waste_type_id,
            payload={
                "name": new_name,
                "previous_name": current_name,
                "report_type": report_type,
                "sort_order": new_sort,
                "is_active": new_active,
            },
        )
        return Ok(self._read(tenant_id=tenant_id, waste_type_id=waste_type_id))

    def delete_type(self, *, tenant_id: str, actor_id: str, waste_type_id: str) -> Result[dict]:
        """Remove the kind, or retire it if a report already has a line under it."""
        current = self._connection.execute(
            "SELECT name, report_type FROM production.waste_types WHERE id = %s AND tenant_id = %s FOR UPDATE",
            (waste_type_id, tenant_id),
        ).fetchone()
        if current is None:
            return Err("NOT_FOUND", f"waste type {waste_type_id} not found", f"type de déchet {waste_type_id} introuvable")
        name, report_type = current

        in_use = self._connection.execute(
            """
            SELECT EXISTS (SELECT 1 FROM production.report_waste_lines WHERE tenant_id = %s AND category = %s)
                OR EXISTS (SELECT 1 FROM production.shift_waste_lines WHERE tenant_id = %s AND category = %s)
            """,
            (tenant_id, waste_type_id, tenant_id, waste_type_id),
        ).fetchone()[0]
        if in_use:
            result = self.update_type(tenant_id=tenant_id, actor_id=actor_id, waste_type_id=waste_type_id, is_active=False)
            if isinstance(result, Err):
                return result
            return Ok({"outcome": "retired", "waste_type": result.value})

        self._connection.execute(
            "DELETE FROM production.waste_types WHERE id = %s AND tenant_id = %s", (waste_type_id, tenant_id)
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="waste_type.deleted",
            entity_type="waste_type",
            entity_id=waste_type_id,
            payload={"name": name, "report_type": report_type},
        )
        return Ok({"outcome": "deleted", "waste_type": {"id": waste_type_id, "name": name, "report_type": report_type}})

    # --- built-ins ---------------------------------------------------------

    def list_builtin_settings(self, *, tenant_id: str) -> list[dict]:
        """Every built-in with what this plant changed about it. `name` None means
        the translated default; `sort_order` None means code order, ahead of the
        plant's own kinds."""
        rows = self._connection.execute(
            "SELECT category, name, sort_order, is_active FROM production.waste_type_builtin_settings "
            "WHERE tenant_id = %s",
            (tenant_id,),
        ).fetchall()
        saved = {row[0]: row for row in rows}
        result = []
        for report_type, categories in WASTE_CATEGORIES_BY_REPORT_TYPE.items():
            for category in categories:
                row = saved.get(category)
                result.append(
                    {
                        "category": category,
                        "report_type": report_type,
                        "name": row[1] if row else None,
                        "sort_order": None if row is None or row[2] is None else int(row[2]),
                        "is_active": row[3] if row else True,
                    }
                )
        return result

    def update_builtin(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        category: str,
        name: str | None = None,
        reset_name: bool = False,
        is_active: bool | None = None,
    ) -> Result[dict]:
        """Rename a built-in (`reset_name` goes back to the translated default), or
        take it off / put it back on the forms."""
        report_type = _builtin_report_type(category)
        if report_type is None:
            return Err(
                "NOT_FOUND",
                f"built-in waste type {category} not found",
                f"type de déchet intégré {category} introuvable",
            )
        current = self._builtin(tenant_id=tenant_id, category=category)

        new_name = current["name"]
        if reset_name:
            new_name = None
        elif name is not None:
            checked = validate_waste_type(name=name, report_type=report_type)
            if isinstance(checked, Err):
                return checked
            new_name = checked.value
            clash = self._connection.execute(
                "SELECT 1 FROM production.waste_types "
                "WHERE tenant_id = %s AND report_type = %s AND lower(name) = lower(%s)",
                (tenant_id, report_type, new_name),
            ).fetchone()
            if clash is not None:
                return Err(
                    "DUPLICATE_WASTE_TYPE",
                    f"a {report_type} waste type called {new_name!r} already exists",
                    f"un type de déchet {report_type} appelé {new_name!r} existe déjà",
                )
        new_active = current["is_active"] if is_active is None else is_active

        self._connection.execute(
            """
            INSERT INTO production.waste_type_builtin_settings (tenant_id, category, report_type, name, is_active)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (tenant_id, category)
            DO UPDATE SET name = EXCLUDED.name, is_active = EXCLUDED.is_active, updated_at = NOW()
            """,
            (tenant_id, category, report_type, new_name, new_active),
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="waste_type.builtin_updated",
            entity_type="waste_type",
            entity_id=category,
            payload={"name": new_name, "previous_name": current["name"], "is_active": new_active},
        )
        return Ok(self._builtin(tenant_id=tenant_id, category=category))

    def reorder(self, *, tenant_id: str, actor_id: str, report_type: str, order: list[str]) -> Result[dict]:
        """Put one report's kinds -- built-in keys and plant ids together -- in the
        given order. The list must name every kind of that report exactly once, so
        a stale screen cannot silently push one to the end."""
        if report_type not in WASTE_TYPE_REPORT_TYPES:
            return Err(
                "INVALID_REPORT_TYPE",
                f"report_type must be one of {list(WASTE_TYPE_REPORT_TYPES)}",
                f"report_type doit être l'un de {list(WASTE_TYPE_REPORT_TYPES)}",
            )
        builtins = set(WASTE_CATEGORIES_BY_REPORT_TYPE[report_type])
        own = set(custom_waste_categories(self._connection, tenant_id=tenant_id, report_type=report_type))
        if len(order) != len(set(order)) or set(order) != builtins | own:
            return Err(
                "INVALID_ORDER",
                "the order must list every waste type of the report exactly once; reload and try again",
                "l'ordre doit citer chaque type de déchet du rapport une seule fois ; rechargez et réessayez",
            )

        for position, key in enumerate(order, start=1):
            if key in builtins:
                self._connection.execute(
                    """
                    INSERT INTO production.waste_type_builtin_settings (tenant_id, category, report_type, sort_order)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (tenant_id, category)
                    DO UPDATE SET sort_order = EXCLUDED.sort_order, updated_at = NOW()
                    """,
                    (tenant_id, key, report_type, position),
                )
            else:
                self._connection.execute(
                    "UPDATE production.waste_types SET sort_order = %s, updated_at = NOW() "
                    "WHERE id = %s AND tenant_id = %s",
                    (position, key, tenant_id),
                )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="waste_type.reordered",
            entity_type="waste_type",
            entity_id=report_type,
            payload={"order": order},
        )
        return Ok({"report_type": report_type, "order": order})

    def _builtin(self, *, tenant_id: str, category: str) -> dict:
        return next(
            entry for entry in self.list_builtin_settings(tenant_id=tenant_id) if entry["category"] == category
        )

    def _read(self, *, tenant_id: str, waste_type_id: str) -> dict:
        row = self._connection.execute(
            f"SELECT {_COLUMNS} FROM production.waste_types WHERE id = %s AND tenant_id = %s",
            (waste_type_id, tenant_id),
        ).fetchone()
        return _row_to_dict(row)


def _builtin_report_type(category: str) -> str | None:
    for report_type, categories in WASTE_CATEGORIES_BY_REPORT_TYPE.items():
        if category in categories:
            return report_type
    return None
