from datetime import date
from decimal import Decimal

from modules.payroll.domain.inputs import SettlementInput
from modules.payroll.domain.rules import SeveranceStep
from modules.payroll.domain.settlement import (
    leave_indemnity,
    notice_indemnity,
    reference_salary,
    settlement_lines,
    severance_amount,
    years_of_service,
)
from modules.payroll.domain.synthetic import synthetic_rule_set

D = Decimal
RULES = synthetic_rule_set()


def test_years_of_service_count_whole_months():
    assert years_of_service(date(2014, 9, 15), date(2026, 9, 15)) == D(12)
    assert years_of_service(date(2014, 9, 16), date(2026, 9, 15)) == D(143) / 12


def test_reference_salary_averages_the_most_recent_months_else_the_fallback():
    assert reference_salary([D(300000), D(330000)], months=12, fallback=D(1)) == D(315000)
    assert reference_salary([], months=12, fallback=D(250000)) == D(250000)
    assert reference_salary([D(100)] * 12 + [D(10**9)], months=12, fallback=D(1)) == D(100)
    assert reference_salary([D(100), D(300)], months=1, fallback=D(1)) == D(100)


def test_severance_is_tiered_by_years_of_service():
    assert severance_amount(RULES.severance_scale, D(12), D(300000)) == D(855000)
    assert severance_amount(RULES.severance_scale, D(3), D(300000)) == D(180000)
    assert severance_amount((), D(12), D(300000)) == 0


def test_a_scale_starting_after_year_zero_pays_nothing_before_it():
    scale = (SeveranceStep(1, D(20)),)
    assert severance_amount(scale, D("0.5"), D(300000)) == 0
    assert severance_amount(scale, D(2), D(300000)) == D(60000)


def test_leave_and_notice_indemnities():
    assert leave_indemnity(D(300000), D(10), RULES) == D(150000)
    assert notice_indemnity(D(300000), D("1.5")) == D(450000)


def test_settlement_lines_carry_the_rule_set_flags():
    lines = settlement_lines(RULES, SettlementInput(reference_salary=D(300000), years_of_service=D(12),
                                                    unused_leave_days=D(10), notice_months=D(1)))
    assert [(line.code, line.amount, line.taxable) for line in lines] == [
        ("LEAVE_INDEMNITY", D(150000), True), ("NOTICE_INDEMNITY", D(300000), True), ("SEVERANCE", D(855000), False),
    ]


def test_nothing_owed_gives_no_line():
    assert settlement_lines(RULES, SettlementInput(reference_salary=D(300000), years_of_service=D(0))) == []
