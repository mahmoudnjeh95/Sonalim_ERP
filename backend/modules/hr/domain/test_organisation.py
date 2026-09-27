import datetime
from decimal import Decimal

from core.domain.result import Err, Ok
from modules.hr.domain.money import is_whole_amount
from modules.hr.domain.organisation import (
    DepartmentInput,
    GradeInput,
    PositionInput,
    validate_department,
    validate_grade,
    validate_position,
)

JAN_1 = datetime.date(2026, 1, 1)


def test_amounts_are_whole_non_negative_francs():
    assert is_whole_amount(Decimal("150000"))
    assert is_whole_amount(Decimal("0"))
    assert not is_whole_amount(Decimal("150000.5"))
    assert not is_whole_amount(Decimal("-1"))
    assert not is_whole_amount(Decimal("NaN"))
    assert not is_whole_amount(None)


def test_amounts_stay_below_the_numeric_18_0_column():
    assert is_whole_amount(Decimal(10) ** 18 - 1)
    assert not is_whole_amount(Decimal(10) ** 18)


def test_a_department_needs_a_code_and_a_name_and_is_trimmed():
    assert isinstance(validate_department(DepartmentInput(code=" ", name="Production")), Err)
    ok = validate_department(DepartmentInput(code=" PROD ", name=" Production ", manager_employee_id=""))
    assert ok == Ok(DepartmentInput(code="PROD", name="Production", manager_employee_id=None))


def test_a_position_budget_cannot_be_negative_but_can_be_absent():
    refused = validate_position(PositionInput(code="OP", title="Opérateur", headcount_budget=-1))
    assert isinstance(refused, Err) and refused.code == "INVALID_POSITION"
    assert validate_position(PositionInput(code="OP", title="Opérateur")).value.headcount_budget is None


def test_a_position_budget_cannot_exceed_the_integer_column():
    assert isinstance(validate_position(PositionInput(code="OP", title="Opérateur", headcount_budget=2_147_483_647)), Ok)
    refused = validate_position(PositionInput(code="OP", title="Opérateur", headcount_budget=2_147_483_648))
    assert isinstance(refused, Err) and refused.code == "INVALID_POSITION"


def test_a_grade_minimum_is_whole_francs():
    grade = GradeInput(code="OS1", category="3", echelon="A", base_salary=Decimal("75000.5"), valid_from=JAN_1)
    assert validate_grade(grade).code == "INVALID_AMOUNT"


def test_a_grade_needs_every_field():
    assert validate_grade(GradeInput(code="OS1", category="", echelon="A", base_salary=Decimal("75000"), valid_from=JAN_1)).code == "INVALID_GRADE"
    assert validate_grade(GradeInput(code="OS1", category="3", echelon="A", base_salary=None, valid_from=JAN_1)).code == "INVALID_AMOUNT"
    assert validate_grade(GradeInput(code="OS1", category="3", echelon="A", base_salary=Decimal("1"), valid_from=None)).code == "INVALID_GRADE"
