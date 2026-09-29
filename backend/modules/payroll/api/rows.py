"""Row helpers: dicts from cursors, and JSON-safe values (money as integers)."""
from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any

import psycopg


def fetch_all(connection: psycopg.Connection, sql: str, params: tuple | list = ()) -> list[dict[str, Any]]:
    cursor = connection.execute(sql, params)
    names = [column.name for column in cursor.description or []]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def fetch_one(connection: psycopg.Connection, sql: str, params: tuple | list = ()) -> dict[str, Any] | None:
    rows = fetch_all(connection, sql, params)
    return rows[0] if rows else None


def jsonable(value: Any) -> Any:
    """Decimal -> int when whole (money, counts), float otherwise (rates); dates -> ISO strings."""
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    return value
