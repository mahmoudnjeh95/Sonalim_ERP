from __future__ import annotations

import datetime

import psycopg
from ulid import ULID

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from modules.crm.domain.activity import Activity, validate_activity


class ActivityService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def create_activity(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        kind: str,
        subject_type: str,
        subject_id: str,
        note: str,
        due_at: datetime.datetime | None = None,
    ) -> Result[Activity]:
        validation = validate_activity(kind=kind, subject_type=subject_type, note=note)
        if isinstance(validation, Err):
            return validation

        activity_id = str(ULID())
        self._connection.execute(
            """
            INSERT INTO crm.activities (id, tenant_id, kind, subject_type, subject_id, note, due_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (activity_id, tenant_id, kind, subject_type, subject_id, note, due_at),
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="activity.created",
            entity_type="activity",
            entity_id=activity_id,
            payload={"kind": kind, "subject_type": subject_type, "subject_id": subject_id},
        )
        return Ok(
            Activity(
                id=activity_id,
                kind=kind,
                subject_type=subject_type,
                subject_id=subject_id,
                note=note,
                due_at=due_at.isoformat() if due_at else None,
                completed_at=None,
            )
        )

    def list_activities(
        self, *, tenant_id: str, subject_type: str | None = None, subject_id: str | None = None, limit: int = 20
    ) -> list[Activity]:
        if subject_type is not None and subject_id is not None:
            rows = self._connection.execute(
                """
                SELECT id, kind, subject_type, subject_id, note, due_at, completed_at FROM crm.activities
                WHERE tenant_id = %s AND subject_type = %s AND subject_id = %s
                ORDER BY created_at DESC LIMIT %s
                """,
                (tenant_id, subject_type, subject_id, limit),
            ).fetchall()
        else:
            rows = self._connection.execute(
                """
                SELECT id, kind, subject_type, subject_id, note, due_at, completed_at FROM crm.activities
                WHERE tenant_id = %s ORDER BY created_at DESC LIMIT %s
                """,
                (tenant_id, limit),
            ).fetchall()
        return [
            Activity(
                id=r[0],
                kind=r[1],
                subject_type=r[2],
                subject_id=r[3],
                note=r[4],
                due_at=r[5].isoformat() if r[5] else None,
                completed_at=r[6].isoformat() if r[6] else None,
            )
            for r in rows
        ]

    def update_activity(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        activity_id: str,
        note: str | None = None,
        due_at: datetime.datetime | None = None,
    ) -> Result[Activity]:
        row = self._connection.execute(
            """
            SELECT id, kind, subject_type, subject_id, note, due_at, completed_at FROM crm.activities
            WHERE id = %s AND tenant_id = %s FOR UPDATE
            """,
            (activity_id, tenant_id),
        ).fetchone()
        if row is None:
            return Err("NOT_FOUND", f"activity {activity_id} not found")
        if row[6] is not None:
            return Err("ALREADY_COMPLETED", f"activity {activity_id} is already completed and cannot be edited")

        updated_note = note if note is not None else row[4]
        if not updated_note.strip():
            return Err("EMPTY_NOTE", "note is required")
        updated_due_at = due_at if due_at is not None else row[5]

        self._connection.execute(
            "UPDATE crm.activities SET note = %s, due_at = %s WHERE id = %s",
            (updated_note, updated_due_at, activity_id),
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="activity.updated",
            entity_type="activity",
            entity_id=activity_id,
            payload={"note": updated_note, "due_at": updated_due_at.isoformat() if updated_due_at else None},
        )
        return Ok(
            Activity(
                id=row[0],
                kind=row[1],
                subject_type=row[2],
                subject_id=row[3],
                note=updated_note,
                due_at=updated_due_at.isoformat() if updated_due_at else None,
                completed_at=None,
            )
        )

    def complete_activity(self, *, tenant_id: str, actor_id: str, activity_id: str) -> Result[Activity]:
        row = self._connection.execute(
            """
            SELECT id, kind, subject_type, subject_id, note, due_at, completed_at FROM crm.activities
            WHERE id = %s AND tenant_id = %s FOR UPDATE
            """,
            (activity_id, tenant_id),
        ).fetchone()
        if row is None:
            return Err("NOT_FOUND", f"activity {activity_id} not found")
        if row[6] is not None:
            return Err("ALREADY_COMPLETED", f"activity {activity_id} is already completed")

        self._connection.execute("UPDATE crm.activities SET completed_at = NOW() WHERE id = %s", (activity_id,))
        completed_at = self._connection.execute(
            "SELECT completed_at FROM crm.activities WHERE id = %s", (activity_id,)
        ).fetchone()[0]
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="activity.completed",
            entity_type="activity",
            entity_id=activity_id,
            payload={},
        )
        return Ok(
            Activity(
                id=row[0],
                kind=row[1],
                subject_type=row[2],
                subject_id=row[3],
                note=row[4],
                due_at=row[5].isoformat() if row[5] else None,
                completed_at=completed_at.isoformat(),
            )
        )
