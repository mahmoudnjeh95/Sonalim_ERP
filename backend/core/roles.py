from __future__ import annotations

import psycopg
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from ulid import ULID

from core.audit import record_audit
from core.db import get_connection
from core.permissions_registry import permission_catalog
from core.tenancy import TenantContext, require_permission

router = APIRouter(prefix="/core", tags=["core.roles"])

MANAGE_PERMISSIONS = "core.manage_permissions"


class RoleSummary(BaseModel):
    id: str
    code: str
    name: str
    description: str | None
    permissions: list[str]


class CreateRoleRequest(BaseModel):
    code: str
    name: str
    description: str | None = None
    permissions: list[str] = []


class UpdateRoleRequest(BaseModel):
    name: str
    description: str | None = None
    permissions: list[str]


class AssignRoleRequest(BaseModel):
    role_id: str


def _validate_known_permissions(permissions: list[str]) -> None:
    known = {entry["permission"] for entry in permission_catalog()}
    unknown = sorted(set(permissions) - known)
    if unknown:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            {
                "code": "UNKNOWN_PERMISSION",
                "message": f"not declared permissions: {', '.join(unknown)}",
                "message_fr": f"permissions non déclarées : {', '.join(unknown)}",
            },
        )


def _assert_same_tenant_user(connection: psycopg.Connection, *, tenant_id: str, user_id: str) -> None:
    row = connection.execute(
        "SELECT 1 FROM core.users WHERE id = %s AND tenant_id = %s",
        (user_id, tenant_id),
    ).fetchone()
    if row is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            {"code": "NOT_FOUND", "message": f"user {user_id} not found", "message_fr": f"utilisateur {user_id} introuvable"},
        )


def _get_role(connection: psycopg.Connection, *, tenant_id: str, role_id: str) -> tuple[str, str]:
    row = connection.execute(
        "SELECT id, code FROM core.roles WHERE id = %s AND tenant_id = %s",
        (role_id, tenant_id),
    ).fetchone()
    if row is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            {"code": "NOT_FOUND", "message": f"role {role_id} not found", "message_fr": f"rôle {role_id} introuvable"},
        )
    return row[0], row[1]


def _would_lose_manage_permissions(connection: psycopg.Connection, *, user_id: str, excluding_role_id: str) -> bool:
    """True if, after removing excluding_role_id, the user would hold core.manage_permissions nowhere else."""
    row = connection.execute(
        """
        SELECT 1 FROM core.user_permissions WHERE user_id = %s AND permission = %s
        UNION
        SELECT 1 FROM core.user_roles ur
        JOIN core.role_permissions rp ON rp.role_id = ur.role_id
        WHERE ur.user_id = %s AND rp.permission = %s AND ur.role_id != %s
        LIMIT 1
        """,
        (user_id, MANAGE_PERMISSIONS, user_id, MANAGE_PERMISSIONS, excluding_role_id),
    ).fetchone()
    return row is None


@router.get("/roles", response_model=list[RoleSummary])
def list_roles(tenant: TenantContext = Depends(require_permission(MANAGE_PERMISSIONS))) -> list[RoleSummary]:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT r.id, r.code, r.name, r.description,
                   COALESCE(array_agg(rp.permission) FILTER (WHERE rp.permission IS NOT NULL), '{}')
            FROM core.roles r
            LEFT JOIN core.role_permissions rp ON rp.role_id = r.id
            WHERE r.tenant_id = %s
            GROUP BY r.id, r.code, r.name, r.description
            ORDER BY r.name
            """,
            (tenant.tenant_id,),
        ).fetchall()
    return [
        RoleSummary(id=row[0], code=row[1], name=row[2], description=row[3], permissions=sorted(row[4]))
        for row in rows
    ]


@router.post("/roles", status_code=status.HTTP_201_CREATED, response_model=RoleSummary)
def create_role(
    body: CreateRoleRequest,
    tenant: TenantContext = Depends(require_permission(MANAGE_PERMISSIONS)),
) -> RoleSummary:
    _validate_known_permissions(body.permissions)

    with get_connection() as connection:
        existing = connection.execute(
            "SELECT 1 FROM core.roles WHERE tenant_id = %s AND code = %s",
            (tenant.tenant_id, body.code),
        ).fetchone()
        if existing is not None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                {
                    "code": "ROLE_CODE_TAKEN",
                    "message": f"role code {body.code} already exists",
                    "message_fr": f"le code de rôle {body.code} existe déjà",
                },
            )

        role_id = str(ULID())
        connection.execute(
            "INSERT INTO core.roles (id, tenant_id, code, name, description) VALUES (%s, %s, %s, %s, %s)",
            (role_id, tenant.tenant_id, body.code, body.name, body.description),
        )
        for permission in body.permissions:
            connection.execute(
                "INSERT INTO core.role_permissions (role_id, permission) VALUES (%s, %s)",
                (role_id, permission),
            )
        record_audit(
            connection,
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            action="role.created",
            entity_type="role",
            entity_id=role_id,
            payload={"code": body.code, "name": body.name, "permissions": body.permissions},
        )
        connection.commit()

    return RoleSummary(
        id=role_id, code=body.code, name=body.name, description=body.description, permissions=sorted(body.permissions)
    )


@router.patch("/roles/{role_id}", response_model=RoleSummary)
def update_role(
    role_id: str,
    body: UpdateRoleRequest,
    tenant: TenantContext = Depends(require_permission(MANAGE_PERMISSIONS)),
) -> RoleSummary:
    _validate_known_permissions(body.permissions)

    with get_connection() as connection:
        role_id, code = _get_role(connection, tenant_id=tenant.tenant_id, role_id=role_id)

        previous = {
            row[0]
            for row in connection.execute(
                "SELECT permission FROM core.role_permissions WHERE role_id = %s", (role_id,)
            ).fetchall()
        }
        next_permissions = set(body.permissions)

        connection.execute("DELETE FROM core.role_permissions WHERE role_id = %s", (role_id,))
        for permission in next_permissions:
            connection.execute(
                "INSERT INTO core.role_permissions (role_id, permission) VALUES (%s, %s)",
                (role_id, permission),
            )
        connection.execute(
            "UPDATE core.roles SET name = %s, description = %s WHERE id = %s",
            (body.name, body.description, role_id),
        )
        record_audit(
            connection,
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            action="role.updated",
            entity_type="role",
            entity_id=role_id,
            payload={
                "name": body.name,
                "permissions_added": sorted(next_permissions - previous),
                "permissions_removed": sorted(previous - next_permissions),
            },
        )
        connection.commit()

    return RoleSummary(
        id=role_id, code=code, name=body.name, description=body.description, permissions=sorted(next_permissions)
    )


@router.delete("/roles/{role_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def delete_role(
    role_id: str,
    tenant: TenantContext = Depends(require_permission(MANAGE_PERMISSIONS)),
) -> None:
    with get_connection() as connection:
        role_id, code = _get_role(connection, tenant_id=tenant.tenant_id, role_id=role_id)

        in_use = connection.execute(
            "SELECT 1 FROM core.user_roles WHERE role_id = %s LIMIT 1", (role_id,)
        ).fetchone()
        if in_use is not None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                {
                    "code": "ROLE_IN_USE",
                    "message": "unassign this role from every user before deleting it",
                    "message_fr": "retirez ce rôle de tous les utilisateurs avant de le supprimer",
                },
            )

        connection.execute("DELETE FROM core.role_permissions WHERE role_id = %s", (role_id,))
        connection.execute("DELETE FROM core.roles WHERE id = %s", (role_id,))
        record_audit(
            connection,
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            action="role.deleted",
            entity_type="role",
            entity_id=role_id,
            payload={"code": code},
        )
        connection.commit()


@router.post("/users/{user_id}/roles", status_code=status.HTTP_201_CREATED)
def assign_role(
    user_id: str,
    body: AssignRoleRequest,
    tenant: TenantContext = Depends(require_permission(MANAGE_PERMISSIONS)),
) -> dict:
    with get_connection() as connection:
        _assert_same_tenant_user(connection, tenant_id=tenant.tenant_id, user_id=user_id)
        role_id, code = _get_role(connection, tenant_id=tenant.tenant_id, role_id=body.role_id)

        connection.execute(
            """
            INSERT INTO core.user_roles (user_id, role_id)
            VALUES (%s, %s)
            ON CONFLICT (user_id, role_id) DO NOTHING
            """,
            (user_id, role_id),
        )
        record_audit(
            connection,
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            action="user.role_granted",
            entity_type="user",
            entity_id=user_id,
            payload={"role_id": role_id, "role_code": code},
        )
        connection.commit()
    return {"user_id": user_id, "role_id": role_id}


@router.delete("/users/{user_id}/roles/{role_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def unassign_role(
    user_id: str,
    role_id: str,
    tenant: TenantContext = Depends(require_permission(MANAGE_PERMISSIONS)),
) -> None:
    with get_connection() as connection:
        _assert_same_tenant_user(connection, tenant_id=tenant.tenant_id, user_id=user_id)
        role_id, code = _get_role(connection, tenant_id=tenant.tenant_id, role_id=role_id)

        if user_id == tenant.user_id and _would_lose_manage_permissions(
            connection, user_id=user_id, excluding_role_id=role_id
        ):
            role_permissions = {
                row[0]
                for row in connection.execute(
                    "SELECT permission FROM core.role_permissions WHERE role_id = %s", (role_id,)
                ).fetchall()
            }
            if MANAGE_PERMISSIONS in role_permissions:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    {
                        "code": "SELF_LOCKOUT",
                        "message": "cannot unassign your own only source of core.manage_permissions",
                        "message_fr": "vous ne pouvez pas retirer votre seule source de core.manage_permissions",
                    },
                )

        connection.execute(
            "DELETE FROM core.user_roles WHERE user_id = %s AND role_id = %s",
            (user_id, role_id),
        )
        record_audit(
            connection,
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            action="user.role_revoked",
            entity_type="user",
            entity_id=user_id,
            payload={"role_id": role_id, "role_code": code},
        )
        connection.commit()
