from core.domain.result import Err, Ok
from modules.crm.domain.activity import validate_activity


def test_valid_activity_passes():
    result = validate_activity(kind="call", subject_type="partner", note="Discussed renewal")
    assert isinstance(result, Ok)


def test_invalid_kind_is_rejected():
    result = validate_activity(kind="fax", subject_type="partner", note="hi")
    assert isinstance(result, Err)
    assert result.code == "INVALID_KIND"


def test_invalid_subject_type_is_rejected():
    result = validate_activity(kind="call", subject_type="invoice", note="hi")
    assert isinstance(result, Err)
    assert result.code == "INVALID_SUBJECT_TYPE"


def test_blank_note_is_rejected():
    result = validate_activity(kind="comment", subject_type="lead", note="   ")
    assert isinstance(result, Err)
    assert result.code == "EMPTY_NOTE"
