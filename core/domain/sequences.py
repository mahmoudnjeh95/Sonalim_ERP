from __future__ import annotations

import psycopg


def next_sequence_value(connection: psycopg.Connection, *, tenant_id: str, name: str, prefix: str = "") -> str:
    row = connection.execute(
        """
        UPDATE core.sequences
        SET next_value = next_value + 1
        WHERE tenant_id = %s AND name = %s
        RETURNING prefix, next_value
        """,
        (tenant_id, name),
    ).fetchone()

    if row is None:
        # First use of this sequence for this tenant — seed it lazily rather
        # than requiring a provisioning step per tenant. ON CONFLICT handles
        # the race where two concurrent callers both miss the UPDATE above.
        row = connection.execute(
            """
            INSERT INTO core.sequences (tenant_id, name, prefix, next_value)
            VALUES (%s, %s, %s, 1)
            ON CONFLICT (tenant_id, name) DO UPDATE SET next_value = core.sequences.next_value + 1
            RETURNING prefix, next_value
            """,
            (tenant_id, name, prefix),
        ).fetchone()

    prefix, next_value = row
    return f"{prefix}{next_value:06d}"
