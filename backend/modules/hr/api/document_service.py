"""An employee's papers: add, list with their expiry state, correct."""
from __future__ import annotations

import datetime
from collections.abc import Mapping
from dataclasses import asdict, replace

import psycopg
from ulid import ULID

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from modules.hr.api.settings_service import HrSettingsService
from modules.hr.api.support import change_payload, iso_dates, json_safe, missing_reference
from modules.hr.domain.alerts import expiry_state
from modules.hr.domain.document import EmployeeDocument, validate_document

# EmployeeDocument's field order, which is also the column order used below.
_COLUMNS = ("kind", "title", "file_ref", "issued_on", "expires_on")
_SELECT = f"SELECT id, employee_id, {', '.join(_COLUMNS)} FROM hr.employee_documents"
_INSERT = f"INSERT INTO hr.employee_documents (id, tenant_id, employee_id, {', '.join(_COLUMNS)}) VALUES ({', '.join(['%s'] * (len(_COLUMNS) + 3))})"
_UPDATE = "UPDATE hr.employee_documents SET " + ", ".join(f"{name} = %s" for name in _COLUMNS) + " WHERE id = %s AND tenant_id = %s"


class DocumentService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self.connection = connection

    def _record(self, row, today: datetime.date, horizon: int | None) -> dict:
        document = EmployeeDocument(*row[2:])
        return {"id": row[0], "employee_id": row[1], **iso_dates(asdict(document)), "state": expiry_state(document.expires_on, today, horizon)}

    def _horizon(self, tenant_id: str) -> int | None:
        return HrSettingsService(self.connection).get(tenant_id)["document_expiry_horizon_days"]

    def list_documents(self, *, tenant_id: str, employee_id: str, today: datetime.date | None = None) -> list[dict]:
        day = today or datetime.date.today()
        horizon = self._horizon(tenant_id)
        rows = self.connection.execute(
            f"{_SELECT} WHERE tenant_id = %s AND employee_id = %s ORDER BY expires_on NULLS LAST, kind", (tenant_id, employee_id)
        ).fetchall()
        return [self._record(row, day, horizon) for row in rows]

    def get_document(self, *, tenant_id: str, document_id: str) -> dict | None:
        row = self.connection.execute(f"{_SELECT} WHERE tenant_id = %s AND id = %s", (tenant_id, document_id)).fetchone()
        return None if row is None else self._record(row, datetime.date.today(), self._horizon(tenant_id))

    def create_document(self, *, tenant_id: str, actor_id: str, employee_id: str, document: EmployeeDocument) -> Result[dict]:
        refused = missing_reference(self.connection, "hr.employees", tenant_id, employee_id, "employee", "employé")
        if refused:
            return refused
        validated = validate_document(document)
        if isinstance(validated, Err):
            return validated
        clean = validated.value
        document_id = str(ULID())
        self.connection.execute(_INSERT, (document_id, tenant_id, employee_id, *(getattr(clean, name) for name in _COLUMNS)))
        record_audit(
            self.connection, tenant_id=tenant_id, actor_id=actor_id, action="document.created",
            entity_type="document", entity_id=document_id, payload={"employee_id": employee_id, **json_safe(clean)},
        )
        return Ok(self.get_document(tenant_id=tenant_id, document_id=document_id))

    def update_document(self, *, tenant_id: str, actor_id: str, document_id: str, changes: Mapping[str, object]) -> Result[dict]:
        row = self.connection.execute(
            f"SELECT {', '.join(_COLUMNS)} FROM hr.employee_documents WHERE id = %s AND tenant_id = %s FOR UPDATE", (document_id, tenant_id)
        ).fetchone()
        if row is None:
            return Err("NOT_FOUND", "document not found", "document introuvable")
        current = EmployeeDocument(*row)
        validated = validate_document(replace(current, **changes))
        if isinstance(validated, Err):
            return validated
        clean = validated.value
        self.connection.execute(_UPDATE, (*(getattr(clean, name) for name in _COLUMNS), document_id, tenant_id))
        record_audit(
            self.connection, tenant_id=tenant_id, actor_id=actor_id, action="document.updated",
            entity_type="document", entity_id=document_id, payload=change_payload(asdict(current), asdict(clean)),
        )
        return Ok(self.get_document(tenant_id=tenant_id, document_id=document_id))
