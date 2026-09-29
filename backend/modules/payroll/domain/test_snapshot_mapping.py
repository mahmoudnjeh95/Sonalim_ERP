from datetime import date
from decimal import Decimal

from modules.payroll.domain.inputs import ContractComponent, EmployeeInput, PresenceInput
from modules.payroll.domain.snapshot_mapping import employee_input, presence_input

D = Decimal


def _snapshot(**changes):
    snapshot = {
        "employee_id": "E1", "employee_no": "M-001", "full_name": "Awa Traoré", "department_id": "D1",
        "position_id": None, "grade_id": None, "hire_date": date(2020, 3, 1), "termination_date": None,
        "termination_reason": None, "tax_dependants": 2,
        "contract": {
            "id": "C1", "contract_type": "cdi", "base_salary": D("250000"), "weekly_hours": D(40),
            "pay_frequency": "monthly", "start_date": date(2021, 1, 1), "end_date": None,
            "components": [
                {"component_code": "TRANSPORT", "amount": D("15000"), "rate": None},
                {"component_code": "RESPONSIBILITY", "amount": None, "rate": D("2.5")},
            ],
        },
        "payment_methods": [],
    }
    snapshot.update(changes)
    return snapshot


def test_the_contract_snapshot_becomes_the_engine_employee():
    assert employee_input(_snapshot()) == EmployeeInput(
        employee_id="E1", base_salary=D(250000), pay_frequency="monthly", hire_date=date(2020, 3, 1),
        contract_start=date(2021, 1, 1), contract_end=None, termination_date=None, tax_dependants=2,
        components=(ContractComponent("TRANSPORT", amount=D(15000), rate=None),
                    ContractComponent("RESPONSIBILITY", amount=None, rate=D("2.5"))),
    )


def test_a_termination_date_is_carried():
    assert employee_input(_snapshot(termination_date=date(2026, 9, 15))).termination_date == date(2026, 9, 15)


def test_a_missing_presence_summary_counts_as_nothing_recorded():
    assert presence_input(None) == PresenceInput()


def test_presence_keeps_the_engine_fields_and_ignores_the_rest():
    summary = {"employee_id": "E1", "scheduled_days": 22, "worked_days": 20, "unpaid_absence_days": 1,
               "paid_leave_days": 1, "sick_days": 0, "holiday_days": 0, "holidays_worked_days": 0,
               "ot_minutes_day": 90, "ot_minutes_night": 0, "ot_minutes_rest_holiday": 0,
               "night_minutes": 480, "late_minutes": 12}
    assert presence_input(summary) == PresenceInput(scheduled_days=22, worked_days=20, unpaid_absence_days=1,
                                                    paid_leave_days=1, ot_minutes_day=90)
