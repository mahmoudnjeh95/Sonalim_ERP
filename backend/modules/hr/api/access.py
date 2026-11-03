"""Permission checks an hr route can only make once it has read the request body."""
from __future__ import annotations

from collections.abc import Iterable

from fastapi import HTTPException, status

from core.tenancy import TenantContext, user_has_permission
from modules.hr.domain.sensitive import VIEW_SENSITIVE


def require(connection, tenant: TenantContext, permission: str) -> None:
    if not user_has_permission(connection, user_id=tenant.user_id, permission=permission):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            {
                "code": "FORBIDDEN",
                "message": f"missing permission: {permission}",
                "message_fr": f"permission manquante : {permission}",
            },
        )


def can_view_sensitive(connection, tenant: TenantContext) -> bool:
    return user_has_permission(connection, user_id=tenant.user_id, permission=VIEW_SENSITIVE)


def require_sensitive_for(connection, tenant: TenantContext, fields: Iterable[str]) -> None:
    """A write that sets pay, a national identifier or bank details needs hr.view_sensitive."""
    if list(fields):
        require(connection, tenant, VIEW_SENSITIVE)
