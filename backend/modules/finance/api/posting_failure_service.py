"""Automatic postings that were refused, and why.

One row per (source_module, source_id, source_kind): a new refusal of the same posting overwrites
the reason and reopens it. The consumer writes it in its own committed transaction before the
event is dead-lettered; a later successful posting resolves it; reversing the run cancels it.
Whoever reads the ledger is notified in-app when a failure opens (new, or reopened after it was
resolved), not each time an already open one is refused again."""
from __future__ import annotations

import psycopg
from psycopg.types.json import Jsonb
from ulid import ULID

from core.audit import record_audit
from core.domain.result import Err
from core.notifications import notify, users_with_permission
from modules.finance.api.ledger_posting_service import SYSTEM_ACTOR

FAILURE_KEYS = (
    "id", "source_module", "source_id", "source_kind", "event_id", "event_type",
    "error_code", "error_message", "error_message_fr", "status", "failed_at", "resolved_at",
)
FAILURE_COLUMNS = ", ".join(FAILURE_KEYS)
FAILURE_STATUS_FR = {"open": "ouvert", "resolved": "résolu", "cancelled": "annulé"}
NOTIFY_PERMISSION = "finance.view_ledger"
NOTIFICATION_KIND = "finance.posting.refused"


class PostingFailureService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def record(
        self, *, tenant_id: str, source_module: str, source_id: str, source_kind: str, envelope: dict, err: Err
    ) -> str:
        previous = self._connection.execute(
            "SELECT status FROM finance.posting_failures"
            " WHERE tenant_id = %s AND source_module = %s AND source_id = %s AND source_kind = %s",
            (tenant_id, source_module, source_id, source_kind),
        ).fetchone()
        row = self._connection.execute(
            """
            INSERT INTO finance.posting_failures
                (id, tenant_id, source_module, source_id, source_kind, event_id, event_type, envelope,
                 error_code, error_message, error_message_fr)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (tenant_id, source_module, source_id, source_kind) DO UPDATE SET
                event_id = EXCLUDED.event_id,
                event_type = EXCLUDED.event_type,
                envelope = EXCLUDED.envelope,
                error_code = EXCLUDED.error_code,
                error_message = EXCLUDED.error_message,
                error_message_fr = EXCLUDED.error_message_fr,
                status = 'open',
                failed_at = NOW(),
                resolved_at = NULL
            RETURNING id
            """,
            (
                str(ULID()), tenant_id, source_module, source_id, source_kind,
                envelope["event_id"], envelope["event_type"], Jsonb(envelope),
                err.code, err.message, err.message_fr,
            ),
        ).fetchone()
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=SYSTEM_ACTOR,
            action="posting.refused",
            entity_type="posting_failure",
            entity_id=row[0],
            payload={"source_module": source_module, "source_id": source_id, "source_kind": source_kind, "code": err.code},
        )
        if previous is None or previous[0] != "open":
            notify(
                self._connection,
                tenant_id=tenant_id,
                user_ids=users_with_permission(self._connection, tenant_id, NOTIFY_PERMISSION),
                kind=NOTIFICATION_KIND,
                title=f"Automatic posting refused: {source_module} {source_kind}",
                title_fr=f"Écriture automatique refusée : {source_module} {source_kind}",
                body=err.message,
                body_fr=err.message_fr or err.message,
                link="/finance/entries",
            )
        return row[0]

    def open_counts_by_tenant(self) -> dict[str, int]:
        """Open failures per tenant, every tenant: the worker's alert monitor watches this grow."""
        rows = self._connection.execute(
            "SELECT tenant_id, count(*) FROM finance.posting_failures WHERE status = 'open' GROUP BY tenant_id"
        ).fetchall()
        return {tenant_id: count for tenant_id, count in rows}

    def resolve(
        self, *, tenant_id: str, source_module: str, source_id: str, source_kind: str, actor_id: str = SYSTEM_ACTOR
    ) -> int:
        rows = self._connection.execute(
            """
            UPDATE finance.posting_failures SET status = 'resolved', resolved_at = NOW()
            WHERE tenant_id = %s AND source_module = %s AND source_id = %s AND source_kind = %s AND status = 'open'
            RETURNING id
            """,
            (tenant_id, source_module, source_id, source_kind),
        ).fetchall()
        for (failure_id,) in rows:
            record_audit(
                self._connection,
                tenant_id=tenant_id,
                actor_id=actor_id,
                action="posting_failure.resolved",
                entity_type="posting_failure",
                entity_id=failure_id,
                payload={"source_kind": source_kind},
            )
        return len(rows)

    def cancel_for_source(self, *, tenant_id: str, source_module: str, source_id: str, kinds: list[str]) -> int:
        rows = self._connection.execute(
            """
            UPDATE finance.posting_failures SET status = 'cancelled', resolved_at = NOW()
            WHERE tenant_id = %s AND source_module = %s AND source_id = %s AND source_kind = ANY(%s) AND status = 'open'
            RETURNING id, source_kind
            """,
            (tenant_id, source_module, source_id, kinds),
        ).fetchall()
        for failure_id, kind in rows:
            record_audit(
                self._connection,
                tenant_id=tenant_id,
                actor_id=SYSTEM_ACTOR,
                action="posting_failure.cancelled",
                entity_type="posting_failure",
                entity_id=failure_id,
                payload={"source_kind": kind},
            )
        return len(rows)

    def get(self, *, tenant_id: str, failure_id: str) -> dict | None:
        row = self._connection.execute(
            f"SELECT {FAILURE_COLUMNS}, envelope FROM finance.posting_failures WHERE tenant_id = %s AND id = %s",
            (tenant_id, failure_id),
        ).fetchone()
        return None if row is None else dict(zip(FAILURE_KEYS + ("envelope",), row))

    def list_failures(self, *, tenant_id: str, status: str | None = "open") -> list[dict]:
        sql = f"SELECT {FAILURE_COLUMNS} FROM finance.posting_failures WHERE tenant_id = %s"
        params: list[object] = [tenant_id]
        if status:
            sql += " AND status = %s"
            params.append(status)
        rows = self._connection.execute(sql + " ORDER BY failed_at DESC", params).fetchall()
        return [dict(zip(FAILURE_KEYS, row)) for row in rows]

    def failures_for_source(self, *, tenant_id: str, source_module: str, source_id: str) -> list[dict]:
        rows = self._connection.execute(
            f"""
            SELECT {FAILURE_COLUMNS} FROM finance.posting_failures
            WHERE tenant_id = %s AND source_module = %s AND source_id = %s
            ORDER BY failed_at
            """,
            (tenant_id, source_module, source_id),
        ).fetchall()
        return [dict(zip(FAILURE_KEYS, row)) for row in rows]
