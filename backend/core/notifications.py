"""Shared-kernel in-app notifications.

Any module writes a row per recipient through `notify()`, in the same
transaction as the change that triggered it (no outbox — these are not
cross-service events, just a user-facing inbox). The four `/core/notifications`
routes let the signed-in user list, count and acknowledge their own rows.
"""
from __future__ import annotations

from typing import Iterable

from fastapi import APIRouter, Depends, status
from ulid import ULID

from core.db import get_connection
from core.tenancy import TenantContext, require_session

router = APIRouter(prefix="/core/notifications", tags=["core.notifications"])


def notify(
    connection,
    *,
    tenant_id: str,
    user_ids: Iterable[str],
    kind: str,
    title: str,
    title_fr: str,
    body: str | None = None,
    body_fr: str | None = None,
    link: str | None = None,
) -> int:
    """Writes one notification row per distinct, non-empty user id. Returns rows written."""
    distinct_ids = {user_id for user_id in user_ids if user_id}
    for user_id in distinct_ids:
        # clock_timestamp(), not NOW(): NOW() is frozen for the whole transaction, so two
        # notifications written together would tie on created_at and sort arbitrarily.
        connection.execute(
            """
            INSERT INTO core.notifications (id, tenant_id, user_id, kind, title, title_fr, body, body_fr, link, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, clock_timestamp())
            """,
            (str(ULID()), tenant_id, user_id, kind, title, title_fr, body, body_fr, link),
        )
    return len(distinct_ids)


def users_with_permission(connection, tenant_id: str, permission: str) -> list[str]:
    """Every user of `tenant_id` holding `permission`, directly or via a role."""
    rows = connection.execute(
        """
        SELECT u.id
        FROM core.users u
        WHERE u.tenant_id = %s
          AND (
            EXISTS (SELECT 1 FROM core.user_permissions up WHERE up.user_id = u.id AND up.permission = %s)
            OR EXISTS (
                SELECT 1 FROM core.user_roles ur
                JOIN core.role_permissions rp ON rp.role_id = ur.role_id
                WHERE ur.user_id = u.id AND rp.permission = %s
            )
          )
        ORDER BY u.id
        """,
        (tenant_id, permission, permission),
    ).fetchall()
    return [row[0] for row in rows]


def _row_to_dict(row: tuple) -> dict:
    (notification_id, kind, title, title_fr, body, body_fr, link, created_at, read_at) = row
    return {
        "id": notification_id,
        "kind": kind,
        "title": title,
        "title_fr": title_fr,
        "body": body,
        "body_fr": body_fr,
        "link": link,
        "created_at": created_at.isoformat(),
        "read_at": read_at.isoformat() if read_at is not None else None,
    }


def list_notifications(connection, *, tenant_id: str, user_id: str, unread_only: bool = False) -> list[dict]:
    """The caller's latest 50 notifications, newest first."""
    clauses = ["tenant_id = %s", "user_id = %s"]
    params: list[object] = [tenant_id, user_id]
    if unread_only:
        clauses.append("read_at IS NULL")

    rows = connection.execute(
        f"""
        SELECT id, kind, title, title_fr, body, body_fr, link, created_at, read_at
        FROM core.notifications
        WHERE {' AND '.join(clauses)}
        ORDER BY created_at DESC, id DESC
        LIMIT 50
        """,
        params,
    ).fetchall()
    return [_row_to_dict(row) for row in rows]


def unread_count(connection, *, tenant_id: str, user_id: str) -> int:
    row = connection.execute(
        "SELECT count(*) FROM core.notifications WHERE tenant_id = %s AND user_id = %s AND read_at IS NULL",
        (tenant_id, user_id),
    ).fetchone()
    return row[0]


def mark_read(connection, *, tenant_id: str, user_id: str, notification_id: str) -> None:
    """Marks one notification read. Only the owning user's own row can be touched."""
    connection.execute(
        """
        UPDATE core.notifications
        SET read_at = NOW()
        WHERE id = %s AND tenant_id = %s AND user_id = %s AND read_at IS NULL
        """,
        (notification_id, tenant_id, user_id),
    )


def mark_all_read(connection, *, tenant_id: str, user_id: str) -> None:
    connection.execute(
        """
        UPDATE core.notifications
        SET read_at = NOW()
        WHERE tenant_id = %s AND user_id = %s AND read_at IS NULL
        """,
        (tenant_id, user_id),
    )


@router.get("")
def list_notifications_route(
    unread: bool = False,
    tenant: TenantContext = Depends(require_session),
) -> list[dict]:
    with get_connection() as connection:
        rows = list_notifications(connection, tenant_id=tenant.tenant_id, user_id=tenant.user_id, unread_only=unread)
    return rows


@router.get("/unread-count")
def unread_count_route(tenant: TenantContext = Depends(require_session)) -> dict:
    with get_connection() as connection:
        count = unread_count(connection, tenant_id=tenant.tenant_id, user_id=tenant.user_id)
    return {"count": count}


@router.post("/{notification_id}/read", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def mark_read_route(notification_id: str, tenant: TenantContext = Depends(require_session)) -> None:
    with get_connection() as connection:
        mark_read(connection, tenant_id=tenant.tenant_id, user_id=tenant.user_id, notification_id=notification_id)
        connection.commit()


@router.post("/read-all", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def mark_all_read_route(tenant: TenantContext = Depends(require_session)) -> None:
    with get_connection() as connection:
        mark_all_read(connection, tenant_id=tenant.tenant_id, user_id=tenant.user_id)
        connection.commit()
