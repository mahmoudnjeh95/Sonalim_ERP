from __future__ import annotations

from typing import Any

import psycopg
from fastapi import APIRouter, Depends
from psycopg.types.json import Jsonb
from ulid import ULID

from core.db import get_connection
from core.tenancy import TenantContext, require_permission

router = APIRouter(prefix="/core/audit-log", tags=["core.audit-log"])


@router.get("")
def list_audit_log(
    entity_type: str | None = None,
    entity_id: str | None = None,
    limit: int = 200,
    tenant: TenantContext = Depends(require_permission("core.view_audit_log")),
) -> list[dict]:
    clauses = ["al.tenant_id = %s"]
    params: list[object] = [tenant.tenant_id]
    if entity_type is not None:
        clauses.append("al.entity_type = %s")
        params.append(entity_type)
    if entity_id is not None:
        clauses.append("al.entity_id = %s")
        params.append(entity_id)
    params.append(limit)

    with get_connection() as connection:
        rows = connection.execute(
            f"""
            SELECT al.id, al.actor_id, u.email, al.action, al.entity_type, al.entity_id, al.occurred_at, al.payload
            FROM core.audit_log al
            LEFT JOIN core.users u ON u.id = al.actor_id
            WHERE {' AND '.join(clauses)}
            ORDER BY al.occurred_at DESC
            LIMIT %s
            """,
            params,
        ).fetchall()

    return [
        {
            "id": entry_id,
            "actor_id": row_actor_id,
            "actor_email": actor_email,
            "action": row_action,
            "entity_type": row_entity_type,
            "entity_id": row_entity_id,
            "occurred_at": occurred_at.isoformat(),
            "payload": payload,
        }
        for entry_id, row_actor_id, actor_email, row_action, row_entity_type, row_entity_id, occurred_at, payload in rows
    ]


def record_audit(
    connection: psycopg.Connection,
    *,
    tenant_id: str,
    actor_id: str,
    action: str,
    entity_type: str,
    entity_id: str,
    payload: dict[str, Any],
) -> None:
    connection.execute(
        """
        INSERT INTO core.audit_log (id, tenant_id, actor_id, action, entity_type, entity_id, payload)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        (str(ULID()), tenant_id, actor_id, action, entity_type, entity_id, Jsonb(payload)),
    )
