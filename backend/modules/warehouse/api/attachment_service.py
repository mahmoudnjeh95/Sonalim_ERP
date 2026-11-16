from __future__ import annotations

from typing import Any

import psycopg
from ulid import ULID

from core.audit import record_audit
from core.domain.result import Err, Ok, Result

MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024
_ENTITY_TABLE = {"voucher": "warehouse.vouchers", "cycle_count": "warehouse.cycle_counts"}


def _not_found() -> Err:
    return Err("NOT_FOUND", "file not found", "fichier introuvable")


class AttachmentService:
    """Files attached to a stock document. Stored in the database with the document's tenant, like the
    rest of its data, and capped so they stay small enough for that. Callers commit."""

    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def list(self, *, tenant_id: str, entity_type: str, entity_id: str) -> list[dict[str, Any]]:
        rows = self._connection.execute(
            """
            SELECT id, filename, content_type, size_bytes, uploaded_at FROM warehouse.document_attachments
            WHERE tenant_id = %s AND entity_type = %s AND entity_id = %s ORDER BY uploaded_at, id
            """,
            (tenant_id, entity_type, entity_id),
        ).fetchall()
        return [{"id": r[0], "filename": r[1], "content_type": r[2], "size_bytes": r[3], "uploaded_at": r[4]} for r in rows]

    def add(self, *, tenant_id: str, actor_id: str, entity_type: str, entity_id: str, filename: str, content_type: str,
            content: bytes) -> Result[dict[str, Any]]:
        if not content:
            return Err("INVALID_FILE", "the file is empty", "le fichier est vide")
        if len(content) > MAX_ATTACHMENT_BYTES:
            return Err("FILE_TOO_LARGE", "a file can be at most 10 MB", "un fichier ne peut pas dépasser 10 Mo")
        document = self._connection.execute(
            f"SELECT 1 FROM {_ENTITY_TABLE[entity_type]} WHERE id = %s AND tenant_id = %s", (entity_id, tenant_id)
        ).fetchone()
        if document is None:
            return _not_found()
        attachment_id = str(ULID())
        self._connection.execute(
            """
            INSERT INTO warehouse.document_attachments (id, tenant_id, entity_type, entity_id, filename, content_type, size_bytes, content, uploaded_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (attachment_id, tenant_id, entity_type, entity_id, filename, content_type, len(content), content, actor_id),
        )
        record_audit(self._connection, tenant_id=tenant_id, actor_id=actor_id, action="warehouse.attachment.added",
                     entity_type=entity_type, entity_id=entity_id, payload={"attachment_id": attachment_id, "filename": filename})
        return Ok({"id": attachment_id, "filename": filename, "content_type": content_type, "size_bytes": len(content)})

    def get(self, *, tenant_id: str, entity_type: str, entity_id: str, attachment_id: str) -> Result[dict[str, Any]]:
        row = self._connection.execute(
            """
            SELECT filename, content_type, content FROM warehouse.document_attachments
            WHERE id = %s AND tenant_id = %s AND entity_type = %s AND entity_id = %s
            """,
            (attachment_id, tenant_id, entity_type, entity_id),
        ).fetchone()
        if row is None:
            return _not_found()
        return Ok({"filename": row[0], "content_type": row[1], "content": bytes(row[2])})

    def delete(self, *, tenant_id: str, actor_id: str, entity_type: str, entity_id: str, attachment_id: str) -> Result[None]:
        deleted = self._connection.execute(
            """
            DELETE FROM warehouse.document_attachments
            WHERE id = %s AND tenant_id = %s AND entity_type = %s AND entity_id = %s RETURNING filename
            """,
            (attachment_id, tenant_id, entity_type, entity_id),
        ).fetchone()
        if deleted is None:
            return _not_found()
        record_audit(self._connection, tenant_id=tenant_id, actor_id=actor_id, action="warehouse.attachment.deleted",
                     entity_type=entity_type, entity_id=entity_id, payload={"attachment_id": attachment_id, "filename": deleted[0]})
        return Ok(None)
