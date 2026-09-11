from __future__ import annotations

import psycopg
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from core.audit import record_audit
from core.db import get_connection
from core.permissions_registry import permission_catalog
from core.tenancy import TenantContext, require_permission

router = APIRouter(prefix="/core", tags=["core.users"])

MANAGE_PERMISSIONS = "core.manage_permissions"


class RoleRef(BaseModel):
    id: str
    code: str
    name: str


class UserSummary(BaseModel):
    id: str
    email: str
    full_name: str | None
    permissions: list[str]
    roles: list[RoleRef]


class GrantPermissionRequest(BaseModel):
    permission: str


class UpdateUserRequest(BaseModel):
    full_name: str | None = None


@router.get("/permissions/catalog")
def list_permission_catalog(
    tenant: TenantContext = Depends(require_permission(MANAGE_PERMISSIONS)),
) -> list[dict[str, str]]:
    return permission_catalog()


@router.get("/users", response_model=list[UserSummary])
def list_users(tenant: TenantContext = Depends(require_permission(MANAGE_PERMISSIONS))) -> list[UserSummary]:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT u.id, u.email, u.full_name,
                   COALESCE(array_agg(DISTINCT p.permission) FILTER (WHERE p.permission IS NOT NULL), '{}'),
                   COALESCE(
                       json_agg(DISTINCT jsonb_build_object('id', r.id, 'code', r.code, 'name', r.name))
                       FILTER (WHERE r.id IS NOT NULL),
                       '[]'
                   )
            FROM core.users u
            LEFT JOIN core.user_permissions p ON p.user_id = u.id
            LEFT JOIN core.user_roles ur ON ur.user_id = u.id
            LEFT JOIN core.roles r ON r.id = ur.role_id
            WHERE u.tenant_id = %s
            GROUP BY u.id, u.email, u.full_name
            ORDER BY u.email
            """,
            (tenant.tenant_id,),
        ).fetchall()
    return [
        UserSummary(
            id=row[0],
            email=row[1],
            full_name=row[2],
            permissions=sorted(row[3]),
            roles=sorted(row[4], key=lambda role: role["name"]),
        )
        for row in rows
    ]


@router.patch("/users/{user_id}")
def update_user(
    user_id: str,
    body: UpdateUserRequest,
    tenant: TenantContext = Depends(require_permission(MANAGE_PERMISSIONS)),
) -> dict:
    with get_connection() as connection:
        _assert_same_tenant(connection, tenant_id=tenant.tenant_id, user_id=user_id)
        connection.execute(
            "UPDATE core.users SET full_name = %s WHERE id = %s",
            (body.full_name, user_id),
        )
        record_audit(
            connection,
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            action="user.updated",
            entity_type="user",
            entity_id=user_id,
            payload={"full_name": body.full_name},
        )
        connection.commit()
    return {"user_id": user_id, "full_name": body.full_name}


def _assert_same_tenant(connection: psycopg.Connection, *, tenant_id: str, user_id: str) -> None:
    row = connection.execute(
        "SELECT 1 FROM core.users WHERE id = %s AND tenant_id = %s",
        (user_id, tenant_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, {"code": "NOT_FOUND", "message": f"user {user_id} not found"})


@router.post("/users/{user_id}/permissions", status_code=status.HTTP_201_CREATED)
def grant_permission(
    user_id: str,
    body: GrantPermissionRequest,
    tenant: TenantContext = Depends(require_permission(MANAGE_PERMISSIONS)),
) -> dict:
    known = {entry["permission"] for entry in permission_catalog()}
    if body.permission not in known:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            {"code": "UNKNOWN_PERMISSION", "message": f"{body.permission} is not a declared permission"},
        )

    with get_connection() as connection:
        _assert_same_tenant(connection, tenant_id=tenant.tenant_id, user_id=user_id)
        connection.execute(
            """
            INSERT INTO core.user_permissions (user_id, permission)
            VALUES (%s, %s)
            ON CONFLICT (user_id, permission) DO NOTHING
            """,
            (user_id, body.permission),
        )
        record_audit(
            connection,
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            action="user.permission_granted",
            entity_type="user",
            entity_id=user_id,
            payload={"permission": body.permission},
        )
        connection.commit()
    return {"user_id": user_id, "permission": body.permission}


@router.delete("/users/{user_id}/permissions/{permission}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def revoke_permission(
    user_id: str,
    permission: str,
    tenant: TenantContext = Depends(require_permission(MANAGE_PERMISSIONS)),
) -> None:
    if user_id == tenant.user_id and permission == MANAGE_PERMISSIONS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            {"code": "SELF_LOCKOUT", "message": "cannot revoke your own core.manage_permissions"},
        )

    with get_connection() as connection:
        _assert_same_tenant(connection, tenant_id=tenant.tenant_id, user_id=user_id)
        connection.execute(
            "DELETE FROM core.user_permissions WHERE user_id = %s AND permission = %s",
            (user_id, permission),
        )
        record_audit(
            connection,
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            action="user.permission_revoked",
            entity_type="user",
            entity_id=user_id,
            payload={"permission": permission},
        )
        connection.commit()
