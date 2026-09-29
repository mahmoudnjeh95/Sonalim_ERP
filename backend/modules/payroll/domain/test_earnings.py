from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from modules.payroll.domain.earnings import (
    base_salary_lines,
    contract_component_lines,
    earned_base,
    input_earning_lines,
    overtime_lines,
    seniority_line,
)
from modules.payroll.domain.inputs import ContractComponent, OneOffInput, PresenceInput
from modules.payroll.domain.rules import ComponentMisuse, RuleSetIncomplete
from modules.payroll.domain.synthetic import synthetic_employee, synthetic_rule_set

D = Decimal
SEPT = date(2026, 9, 1)
RULES = synthetic_rule_set()
FULL = PresenceInput(scheduled_days=22, worked_days=22)


def amounts(lines):
    return {line.code: line.amount for line in lines}


def test_a_full_month_pays_the_whole_base():
    assert amounts(base_salary_lines(synthetic_employee(), FULL, RULES, SEPT)) == {"BASE": D(400000)}


def test_a_mid_month_hire_is_paid_scheduled_days_over_working_days():
    hired = synthetic_employee(hire_date=date(2026, 9, 11), contract_start=date(2026, 9, 11))
    lines = base_salary_lines(hired, PresenceInput(scheduled_days=14, worked_days=14), RULES, SEPT)
    assert amounts(lines) == {"BASE": D(280000)}
    assert lines[0].qty == D(14)


def test_an_exit_mid_month_is_prorated_the_same_way():
    leaving = synthetic_employee(termination_date=date(2026, 9, 15))
    assert amounts(base_salary_lines(leaving, PresenceInput(scheduled_days=10, worked_days=10), RULES, SEPT)) == {"BASE": D(200000)}


def test_more_scheduled_days_than_the_monthly_basis_never_pay_more_than_the_base():
    hired = synthetic_employee(hire_date=date(2026, 9, 2), contract_start=date(2026, 9, 2))
    assert amounts(base_salary_lines(hired, PresenceInput(scheduled_days=25), RULES, SEPT)) == {"BASE": D(400000)}


def test_unpaid_absence_days_are_taken_off_at_the_daily_rate():
    lines = base_salary_lines(synthetic_employee(), PresenceInput(scheduled_days=22, worked_days=20, unpaid_absence_days=2), RULES, SEPT)
    assert amounts(lines) == {"BASE": D(400000), "UNPAID_ABSENCE": D(-40000)}
    assert earned_base(lines) == D(360000)


def test_unpaid_absence_never_takes_more_than_the_base_earned():
    hired = synthetic_employee(hire_date=date(2026, 9, 25), contract_start=date(2026, 9, 25))
    lines = base_salary_lines(hired, PresenceInput(scheduled_days=3, unpaid_absence_days=5), RULES, SEPT)
    assert amounts(lines) == {"BASE": D(60000), "UNPAID_ABSENCE": D(-60000)}
    assert earned_base(lines) == 0


def test_a_daily_rate_is_paid_per_worked_leave_and_holiday_day():
    daily = synthetic_employee(base_salary=D(10000), pay_frequency="daily")
    presence = PresenceInput(scheduled_days=22, worked_days=18, paid_leave_days=1, holiday_days=1, unpaid_absence_days=2)
    assert amounts(base_salary_lines(daily, presence, RULES, SEPT)) == {"BASE": D(200000)}


def test_a_worked_holiday_draws_one_day_rate_not_two():
    # hr's month_summary counts a worked holiday in both worked_days and holiday_days
    # (holidays_worked_days marks the overlap) -- the daily base must not pay it twice;
    # its hours are paid separately as OT_REST_HOLIDAY overtime.
    daily = synthetic_employee(base_salary=D(10000), pay_frequency="daily")
    presence = PresenceInput(worked_days=19, holiday_days=1, holidays_worked_days=1)
    assert amounts(base_salary_lines(daily, presence, RULES, SEPT)) == {"BASE": D(190000)}


def test_a_worked_rest_day_draws_only_its_overtime_by_default():
    # hr counts a worked rest day in worked_days and pays all its minutes as rest_holiday
    # overtime; like a monthly worker, the daily worker gets the overtime, not a day rate too.
    daily = synthetic_employee(base_salary=D(10000), pay_frequency="daily")
    presence = PresenceInput(worked_days=20, rest_days_worked=2)
    assert RULES.daily_rest_day_pay == "overtime_only"
    assert amounts(base_salary_lines(daily, presence, RULES, SEPT)) == {"BASE": D(180000)}


def test_a_rule_set_can_pay_a_worked_rest_day_its_day_rate_as_well():
    daily = synthetic_employee(base_salary=D(10000), pay_frequency="daily")
    presence = PresenceInput(worked_days=20, rest_days_worked=2)
    rules = replace(RULES, daily_rest_day_pay="day_rate_and_overtime")
    assert amounts(base_salary_lines(daily, presence, rules, SEPT)) == {"BASE": D(200000)}


def test_seniority_uses_the_highest_step_reached_by_the_end_of_the_month():
    assert seniority_line(synthetic_employee(hire_date=date(2021, 9, 1)), D(400000), RULES, SEPT).amount == D(20000)
    assert seniority_line(synthetic_employee(hire_date=date(2021, 10, 1)), D(400000), RULES, SEPT).amount == D(12000)
    assert seniority_line(synthetic_employee(hire_date=date(2024, 1, 1)), D(400000), RULES, SEPT) is None


def test_seniority_is_counted_up_to_the_exit_date():
    leaving = synthetic_employee(hire_date=date(2021, 9, 20), termination_date=date(2026, 9, 15))
    assert seniority_line(leaving, D(400000), RULES, SEPT).amount == D(12000)


def test_overtime_is_hours_times_hourly_rate_times_band_multiplier():
    lines = overtime_lines(synthetic_employee(), PresenceInput(ot_minutes_day=600, ot_minutes_night=90), RULES)
    assert amounts(lines) == {"OT_DAY": D(37500), "OT_NIGHT": D(7500)}
    assert [line.qty for line in lines] == [D("10.00"), D("1.50")]


def test_a_daily_workers_hourly_rate_comes_from_the_day_rate():
    daily = synthetic_employee(base_salary=D(10000), pay_frequency="daily")
    assert amounts(overtime_lines(daily, PresenceInput(ot_minutes_night=90), RULES)) == {"OT_NIGHT": D(3750)}


def test_contract_components_follow_their_formula_and_the_month_coverage():
    hired = synthetic_employee(hire_date=date(2026, 9, 11), contract_start=date(2026, 9, 11),
                               components=(ContractComponent("HOUSING", amount=D(30000)), ContractComponent("MEAL")))
    lines = contract_component_lines(hired, PresenceInput(scheduled_days=14, worked_days=12), RULES, SEPT, earned=D(280000))
    assert amounts(lines) == {"HOUSING": D(21000), "MEAL": D(6000)}


def test_a_contract_component_unknown_to_the_rule_set_is_reported():
    ghost = synthetic_employee(components=(ContractComponent("GHOST", amount=D(1)),))
    with pytest.raises(RuleSetIncomplete):
        contract_component_lines(ghost, FULL, RULES, SEPT, earned=D(400000))


def test_a_deduction_cannot_be_written_on_a_contract():
    with pytest.raises(ComponentMisuse):
        contract_component_lines(synthetic_employee(components=(ContractComponent("CANTEEN", amount=D(1)),)), FULL, RULES, SEPT, earned=D(400000))


def test_monthly_inputs_become_earning_lines_and_deductions_are_left_for_later():
    inputs = [OneOffInput("BONUS", amount=D(25000)), OneOffInput("MEAL", qty=D(5)), OneOffInput("ADVANCE", amount=D(1))]
    assert amounts(input_earning_lines(inputs, FULL, RULES)) == {"BONUS": D(25000), "MEAL": D(2500)}


def test_a_computed_component_cannot_be_typed_as_an_input():
    with pytest.raises(ComponentMisuse):
        input_earning_lines([OneOffInput("SENIORITY", amount=D(1))], FULL, RULES)
