"""An employee's papers. Pure rules, no database."""
from __future__ import annotations

import datetime
from dataclasses import dataclass

from core.domain.result import Err, Ok, Result

DOCUMENT_KINDS = (
    "id_card",
    "passport",
    "work_permit",
    "medical_certificate",
    "driving_licence",
    "diploma",
    "criminal_record",
    "signed_contract",
    "other",
)


@dataclass(frozen=True)
class EmployeeDocument:
    kind: str
    title: str | None = None
    file_ref: str | None = None
    issued_on: datetime.date | None = None
    expires_on: datetime.date | None = None


def _text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def validate_document(document: EmployeeDocument) -> Result[EmployeeDocument]:
    if document.kind not in DOCUMENT_KINDS:
        return Err("INVALID_CHOICE", "unknown document kind", "type de document inconnu")
    title = _text(document.title)
    if document.kind == "other" and title is None:
        return Err("INVALID_DOCUMENT", "an 'other' document needs a title", "un document « autre » demande un intitulé")
    if document.issued_on is not None and document.expires_on is not None and document.expires_on < document.issued_on:
        return Err("INVALID_DATES", "a document cannot expire before it is issued", "un document ne peut pas expirer avant sa délivrance")
    return Ok(
        EmployeeDocument(
            kind=document.kind, title=title, file_ref=_text(document.file_ref), issued_on=document.issued_on, expires_on=document.expires_on
        )
    )
