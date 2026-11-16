from __future__ import annotations

import base64
import binascii
from typing import Any

import psycopg
from ulid import ULID

from core.audit import record_audit
from core.domain.result import Err, Ok, Result

MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024


class DocumentAttachmentService:
    """Files kept on a receipt or disbursement. Callers commit."""

    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def _document_exists(self, tenant_id: str, direction: str, document_id: str) -> bool:
        return self._connection.execute(
            "SELECT 1 FROM treasury.documents WHERE id = %s AND tenant_id = %s AND direction = %s", (document_id, tenant_id, direction)
        ).fetchone() is not None

    def list(self, *, tenant_id: str, direction: str, document_id: str) -> Result[list[dict[str, Any]]]:
        if not self._document_exists(tenant_id, direction, document_id):
            return Err("NOT_FOUND", f"document {document_id} not found", f"document {document_id} introuvable")
        rows = self._connection.execute(
            "SELECT id, filename, content_type, size_bytes, created_at FROM treasury.document_attachments "
            "WHERE document_id = %s AND tenant_id = %s ORDER BY created_at, id",
            (document_id, tenant_id),
        ).fetchall()
        keys = ["id", "filename", "content_type", "size_bytes", "created_at"]
        return Ok([dict(zip(keys, r, strict=True)) for r in rows])

    def add(self, *, tenant_id: str, actor_id: str, direction: str, document_id: str, filename: str,
            content_type: str | None, content_base64: str) -> Result[dict[str, Any]]:
        if not self._document_exists(tenant_id, direction, document_id):
            return Err("NOT_FOUND", f"document {document_id} not found", f"document {document_id} introuvable")
        if not filename.strip():
            return Err("ATTACHMENT_NAME_REQUIRED", "a file needs a name", "un fichier doit avoir un nom")
        try:
            content = base64.b64decode(content_base64, validate=True)
        except (binascii.Error, ValueError):
            return Err("ATTACHMENT_UNREADABLE", "the file could not be read", "le fichier n'a pas pu être lu")
        if not content:
            return Err("ATTACHMENT_EMPTY", "the file is empty", "le fichier est vide")
        if len(content) > MAX_ATTACHMENT_BYTES:
            return Err("ATTACHMENT_TOO_LARGE", "a file cannot exceed 10 MB", "un fichier ne peut pas dépasser 10 Mo")
        attachment_id = str(ULID())
        self._connection.execute(
            "INSERT INTO treasury.document_attachments (id, tenant_id, document_id, filename, content_type, size_bytes, content, created_by) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (attachment_id, tenant_id, document_id, filename.strip(), content_type or "application/octet-stream", len(content), content, actor_id),
        )
        record_audit(self._connection, tenant_id=tenant_id, actor_id=actor_id, action="treasury.document.attachment_added",
                     entity_type="treasury_document", entity_id=document_id, payload={"filename": filename.strip(), "size": len(content)})
        return Ok({"id": attachment_id, "filename": filename.strip(), "content_type": content_type or "application/octet-stream", "size_bytes": len(content)})

    def read(self, *, tenant_id: str, direction: str, document_id: str, attachment_id: str) -> Result[dict[str, Any]]:
        row = self._connection.execute(
            "SELECT a.filename, a.content_type, a.content FROM treasury.document_attachments a "
            "JOIN treasury.documents d ON d.id = a.document_id "
            "WHERE a.id = %s AND a.document_id = %s AND a.tenant_id = %s AND d.direction = %s",
            (attachment_id, document_id, tenant_id, direction),
        ).fetchone()
        if row is None:
            return Err("NOT_FOUND", f"attachment {attachment_id} not found", f"pièce jointe {attachment_id} introuvable")
        return Ok({"filename": row[0], "content_type": row[1], "content": bytes(row[2])})

    def delete(self, *, tenant_id: str, actor_id: str, direction: str, document_id: str, attachment_id: str) -> Result[None]:
        if not self._document_exists(tenant_id, direction, document_id):
            return Err("NOT_FOUND", f"document {document_id} not found", f"document {document_id} introuvable")
        deleted = self._connection.execute(
            "DELETE FROM treasury.document_attachments WHERE id = %s AND document_id = %s AND tenant_id = %s",
            (attachment_id, document_id, tenant_id),
        ).rowcount
        if not deleted:
            return Err("NOT_FOUND", f"attachment {attachment_id} not found", f"pièce jointe {attachment_id} introuvable")
        record_audit(self._connection, tenant_id=tenant_id, actor_id=actor_id, action="treasury.document.attachment_deleted",
                     entity_type="treasury_document", entity_id=document_id, payload={"attachment_id": attachment_id})
        return Ok(None)
