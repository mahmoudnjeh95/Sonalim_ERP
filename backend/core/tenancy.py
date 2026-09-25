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
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            {"code": "MISSING_TOKEN", "message": "missing bearer token", "message_fr": "vous n'êtes pas connecté"},
        )
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
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            {
                "code": "INVALID_SESSION",
                "message": "invalid or expired session",
                "message_fr": "session invalide ou expirée ; reconnectez-vous",
            },
        )

    tenant_id, user_id = row
    return TenantContext(tenant_id=tenant_id, user_id=user_id, session_token=token)


def user_has_permission(connection, *, user_id: str, permission: str) -> bool:
    """Whether the user holds `permission`, directly or through any role they are assigned.

    The one check behind require_permission, exposed for the places that only know
    which permission they need at run time (a per-section edit right in the URL).
    """
    row = connection.execute(
        """
        SELECT 1 FROM core.user_permissions WHERE user_id = %s AND permission = %s
        UNION
        SELECT 1 FROM core.user_roles ur
        JOIN core.role_permissions rp ON rp.role_id = ur.role_id
        WHERE ur.user_id = %s AND rp.permission = %s
        LIMIT 1
        """,
        (user_id, permission, user_id, permission),
    ).fetchone()
    return row is not None


def require_permission(permission: str):
    """Dependency factory: proves the session's user holds `permission`, directly or via a role.

    require_session only proves *who* is calling; this proves *what* they're
    allowed to do, checked against core.user_permissions and, live, every role
    (core.user_roles -> core.role_permissions) the user is currently assigned.
    """

    def dependency(tenant: TenantContext = Depends(require_session)) -> TenantContext:
        with get_connection() as connection:
            allowed = user_has_permission(connection, user_id=tenant.user_id, permission=permission)
        if not allowed:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                {
                    "code": "FORBIDDEN",
                    "message": f"missing permission: {permission}",
                    "message_fr": f"permission manquante : {permission}",
                },
            )
        return tenant

    return dependency
