from dataclasses import replace
from decimal import Decimal

from modules.payroll.domain.contributions import contributable_earnings, contribution_lines
from modules.payroll.domain.inputs import PayslipLine
from modules.payroll.domain.rules import ContributionRule
from modules.payroll.domain.synthetic import synthetic_rule_set

D = Decimal
RULES = synthetic_rule_set()


def earning(code, amount, *, contributable=False):
    return PayslipLine(section="earning", code=code, name_en=code, name_fr=code, amount=D(amount), contributable=contributable)


def test_only_contributable_earnings_count_and_the_base_never_goes_negative():
    assert contributable_earnings([earning("BASE", 400000, contributable=True), earning("TRANSPORT", 10000)]) == D(400000)
    assert contributable_earnings([earning("UNPAID_ABSENCE", -5, contributable=True)]) == 0


def test_a_ceiling_caps_the_base_of_that_contribution_only():
    lines = contribution_lines(RULES, gross=D(610000), contributable=D(600000))
    got = {(line.section, line.code): (line.base, line.amount) for line in lines}
    assert got == {
        ("employee_contribution", "PENSION"): (D(500000), D(25000)),
        ("employer_contribution", "PENSION"): (D(500000), D(50000)),
        ("employee_contribution", "HEALTH"): (D(600000), D(12000)),
        ("employer_contribution", "HEALTH"): (D(600000), D(18000)),
    }


def test_a_contribution_on_gross_ignores_the_contributable_flag():
    solidarity = ContributionRule(code="SOLIDARITY", name_en="Solidarity", name_fr="Solidarité", base="gross",
                                  employee_rate=D(1), employer_rate=D(0), ceiling_monthly=None,
                                  deductible_from_taxable=False, declaration_code="SOL")
    lines = contribution_lines(replace(RULES, contributions=(solidarity,)), gross=D(410000), contributable=D(400000))
    assert [(line.section, line.amount, line.deductible, line.declaration_code) for line in lines] == [
        ("employee_contribution", D(4100), False, "SOL")
    ]


def test_employee_contributions_say_whether_they_lower_the_taxable_base():
    lines = contribution_lines(RULES, gross=D(100000), contributable=D(100000))
    assert all(line.deductible for line in lines if line.section == "employee_contribution")
    assert not any(line.deductible for line in lines if line.section == "employer_contribution")


def test_no_base_no_contribution():
    assert contribution_lines(RULES, gross=D(0), contributable=D(0)) == []
