from __future__ import annotations

import base64
import binascii
from typing import Any

import psycopg
from ulid import ULID

from core.audit import record_audit
from core.domain.result import Err, Ok, Result

MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024


def _invoice_not_found(invoice_id: str) -> Err:
    return Err("NOT_FOUND", f"purchase invoice {invoice_id} not found", f"facture d'achat {invoice_id} introuvable")


class PurchaseInvoiceAttachmentService:
    """Files kept on a purchase invoice, typically the supplier's scanned invoice. Callers commit."""

    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def _invoice_exists(self, tenant_id: str, invoice_id: str) -> bool:
        return self._connection.execute(
            "SELECT 1 FROM procurement.purchase_invoices WHERE id = %s AND tenant_id = %s", (invoice_id, tenant_id)
        ).fetchone() is not None

    def list(self, *, tenant_id: str, invoice_id: str) -> Result[list[dict[str, Any]]]:
        if not self._invoice_exists(tenant_id, invoice_id):
            return _invoice_not_found(invoice_id)
        rows = self._connection.execute(
            "SELECT id, filename, content_type, size_bytes, created_at FROM procurement.purchase_invoice_attachments "
            "WHERE invoice_id = %s AND tenant_id = %s ORDER BY created_at, id",
            (invoice_id, tenant_id),
        ).fetchall()
        keys = ["id", "filename", "content_type", "size_bytes", "created_at"]
        return Ok([dict(zip(keys, r, strict=True)) for r in rows])

    def add(self, *, tenant_id: str, actor_id: str, invoice_id: str, filename: str, content_type: str | None,
            content_base64: str) -> Result[dict[str, Any]]:
        if not self._invoice_exists(tenant_id, invoice_id):
            return _invoice_not_found(invoice_id)
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
        kind = content_type or "application/octet-stream"
        self._connection.execute(
            "INSERT INTO procurement.purchase_invoice_attachments (id, tenant_id, invoice_id, filename, content_type, size_bytes, "
            "content, created_by) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (attachment_id, tenant_id, invoice_id, filename.strip(), kind, len(content), content, actor_id),
        )
        record_audit(self._connection, tenant_id=tenant_id, actor_id=actor_id, action="purchase_invoice.attachment_added",
                     entity_type="purchase_invoice", entity_id=invoice_id, payload={"filename": filename.strip(), "size": len(content)})
        return Ok({"id": attachment_id, "filename": filename.strip(), "content_type": kind, "size_bytes": len(content)})

    def read(self, *, tenant_id: str, invoice_id: str, attachment_id: str) -> Result[dict[str, Any]]:
        row = self._connection.execute(
            "SELECT filename, content_type, content FROM procurement.purchase_invoice_attachments "
            "WHERE id = %s AND invoice_id = %s AND tenant_id = %s",
            (attachment_id, invoice_id, tenant_id),
        ).fetchone()
        if row is None:
            return Err("NOT_FOUND", f"attachment {attachment_id} not found", f"pièce jointe {attachment_id} introuvable")
        return Ok({"filename": row[0], "content_type": row[1], "content": bytes(row[2])})

    def delete(self, *, tenant_id: str, actor_id: str, invoice_id: str, attachment_id: str) -> Result[None]:
        row = self._connection.execute(
            "DELETE FROM procurement.purchase_invoice_attachments WHERE id = %s AND invoice_id = %s AND tenant_id = %s "
            "RETURNING filename",
            (attachment_id, invoice_id, tenant_id),
        ).fetchone()
        if row is None:
            return Err("NOT_FOUND", f"attachment {attachment_id} not found", f"pièce jointe {attachment_id} introuvable")
        record_audit(self._connection, tenant_id=tenant_id, actor_id=actor_id, action="purchase_invoice.attachment_deleted",
                     entity_type="purchase_invoice", entity_id=invoice_id, payload={"attachment_id": attachment_id, "filename": row[0]})
        return Ok(None)
