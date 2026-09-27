import datetime

from core.domain.result import Ok
from modules.hr.domain.employee import EmployeeFile, validate_employee_file
from modules.hr.domain.employee import terminate  # noqa: E402

HIRED = datetime.date(2024, 3, 1)


def _file(**overrides) -> EmployeeFile:
    return EmployeeFile(**{"employee_no": "HRP-001", "first_name": "Awa", "last_name": "Traoré", "hire_date": HIRED, **overrides})


def test_blank_optional_text_is_stored_as_null_and_text_is_trimmed():
    result = validate_employee_file(_file(first_name="  Awa ", badge_no="  ", phone=" 76 00 00 00 "))
    assert isinstance(result, Ok)
    assert (result.value.first_name, result.value.badge_no, result.value.phone) == ("Awa", None, "76 00 00 00")


def test_names_number_and_hire_date_are_required():
    assert validate_employee_file(_file(last_name=" ")).code == "INVALID_EMPLOYEE"
    assert validate_employee_file(_file(first_name=None)).code == "INVALID_EMPLOYEE"
    assert validate_employee_file(_file(hire_date=None)).code == "INVALID_EMPLOYEE"


def test_closed_lists_are_closed():
    assert validate_employee_file(_file(status="retired")).code == "INVALID_STATUS"
    assert validate_employee_file(_file(marital_status="engaged")).code == "INVALID_CHOICE"
    assert validate_employee_file(_file(gender="x")).code == "INVALID_CHOICE"


def test_a_birth_date_on_or_after_hiring_is_refused():
    assert validate_employee_file(_file(birth_date=datetime.date(2025, 1, 1))).code == "INVALID_DATES"


def test_terminated_status_and_termination_fields_go_together():
    assert validate_employee_file(_file(status="terminated")).code == "INVALID_TERMINATION"
    left = _file(termination_date=datetime.date(2026, 1, 31), termination_reason="resignation")
    assert validate_employee_file(left).code == "INVALID_TERMINATION"
    complete = _file(status="terminated", termination_date=datetime.date(2026, 1, 31), termination_reason="resignation")
    assert isinstance(validate_employee_file(complete), Ok)


def test_amended_ends_a_contract_never_an_employment():
    assert validate_employee_file(
        _file(status="terminated", termination_date=datetime.date(2026, 1, 31), termination_reason="amended")
    ).code == "INVALID_TERMINATION"


def test_terminating_sets_status_date_and_reason():
    result = terminate(_file(), termination_date=datetime.date(2026, 9, 30), termination_reason="resignation")
    assert isinstance(result, Ok)
    assert (result.value.status, result.value.termination_date, result.value.termination_reason) == (
        "terminated", datetime.date(2026, 9, 30), "resignation",
    )


def test_an_exit_needs_a_known_reason_and_cannot_precede_hiring():
    assert terminate(_file(), termination_date=datetime.date(2026, 9, 30), termination_reason="amended").code == "INVALID_TERMINATION"
    assert terminate(_file(), termination_date=datetime.date(2026, 9, 30), termination_reason="").code == "INVALID_TERMINATION"
    assert terminate(_file(), termination_date=datetime.date(2024, 2, 1), termination_reason="resignation").code == "INVALID_DATES"


def test_an_employee_leaves_only_once():
    left = terminate(_file(), termination_date=datetime.date(2026, 9, 30), termination_reason="resignation").value
    assert terminate(left, termination_date=datetime.date(2026, 10, 31), termination_reason="dismissal").code == "ALREADY_TERMINATED"
