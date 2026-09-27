from datetime import date

from core.domain.result import Ok
from modules.hr.domain.document import EmployeeDocument, validate_document


def test_an_unknown_kind_is_refused_and_other_needs_a_title():
    assert validate_document(EmployeeDocument(kind="selfie")).code == "INVALID_CHOICE"
    assert validate_document(EmployeeDocument(kind="other")).code == "INVALID_DOCUMENT"
    assert isinstance(validate_document(EmployeeDocument(kind="other", title="Attestation")), Ok)


def test_a_document_cannot_expire_before_it_is_issued():
    refused = validate_document(EmployeeDocument(kind="passport", issued_on=date(2026, 1, 1), expires_on=date(2025, 1, 1)))
    assert refused.code == "INVALID_DATES"


def test_blank_text_becomes_null_and_text_is_trimmed():
    clean = validate_document(EmployeeDocument(kind="passport", title=" ", file_ref="  \\\\srv-rh\\dossiers\\p.pdf ")).value
    assert (clean.title, clean.file_ref) == (None, "\\\\srv-rh\\dossiers\\p.pdf")
