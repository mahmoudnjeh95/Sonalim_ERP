from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, status

from core.db import get_connection


@dataclass(frozen=True)
class TenantContext:
    tenant_id: str
    user_id: str
    session_token: str


def require_session(authorization: str | None = Header(default=None)) -> TenantContext:
    """Resolves tenant identity from the server-side session, never from a client-supplied tenant_id."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")
    token = authorization.removeprefix("Bearer ").strip()

    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT tenant_id, user_id
            FROM core.sessions
            WHERE token = %s AND expires_at > NOW()
            """,
            (token,),
        ).fetchone()

    if row is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or expired session")

    tenant_id, user_id = row
    return TenantContext(tenant_id=tenant_id, user_id=user_id, session_token=token)


def require_permission(permission: str):
    """Dependency factory: proves the session's user was explicitly granted `permission`.

    require_session only proves *who* is calling; this proves *what* they're
    allowed to do, checked against core.user_permissions.
    """

    def dependency(tenant: TenantContext = Depends(require_session)) -> TenantContext:
        with get_connection() as connection:
            row = connection.execute(
                "SELECT 1 FROM core.user_permissions WHERE user_id = %s AND permission = %s",
                (tenant.user_id, permission),
            ).fetchone()
        if row is None:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                {"code": "FORBIDDEN", "message": f"missing permission: {permission}"},
            )
        return tenant

    return dependency
