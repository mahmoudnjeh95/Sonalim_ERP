from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from psycopg.types.json import Jsonb
from pydantic import BaseModel

from core.db import get_connection
from core.tenancy import TenantContext, require_session

router = APIRouter(prefix="/core", tags=["core.table_preferences"])


class TablePreferences(BaseModel):
    table_key: str
    columns: dict[str, Any]


class SaveTablePreferencesRequest(BaseModel):
    columns: dict[str, Any]


@router.get("/table-preferences/{table_key}", response_model=TablePreferences)
def get_table_preferences(
    table_key: str,
    tenant: TenantContext = Depends(require_session),
) -> TablePreferences:
    with get_connection() as connection:
        row = connection.execute(
            "SELECT columns FROM core.user_table_preferences WHERE user_id = %s AND table_key = %s",
            (tenant.user_id, table_key),
        ).fetchone()
    return TablePreferences(table_key=table_key, columns=row[0] if row else {})


@router.put("/table-preferences/{table_key}", response_model=TablePreferences)
def save_table_preferences(
    table_key: str,
    body: SaveTablePreferencesRequest,
    tenant: TenantContext = Depends(require_session),
) -> TablePreferences:
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO core.user_table_preferences (user_id, tenant_id, table_key, columns)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (user_id, table_key)
            DO UPDATE SET columns = EXCLUDED.columns, updated_at = NOW()
            """,
            (tenant.user_id, tenant.tenant_id, table_key, Jsonb(body.columns)),
        )
        connection.commit()
    return TablePreferences(table_key=table_key, columns=body.columns)
