from decimal import Decimal

from modules.payroll.domain.inputs import PayslipLine
from modules.payroll.domain.rules import FamilyRelief, FamilyReliefStep
from modules.payroll.domain.synthetic import synthetic_rule_set
from modules.payroll.domain.tax import bracket_tax, family_relief_amount, professional_relief_amount, tax_lines

D = Decimal
RULES = synthetic_rule_set()


def earning(code, amount, *, taxable=False):
    return PayslipLine(section="earning", code=code, name_en=code, name_fr=code, amount=D(amount), taxable=taxable)


def contribution(code, amount):
    return PayslipLine(section="employee_contribution", code=code, name_en=code, name_fr=code, amount=D(amount), deductible=True)


GOLDEN_LINES = [earning("BASE", 487500, taxable=True), earning("TRANSPORT", 10000),
                contribution("PENSION", 24375), contribution("HEALTH", 9750)]


def test_progressive_brackets():
    brackets = RULES.brackets_for("TAX")
    assert bracket_tax(brackets, D(90000)) == 0
    assert bracket_tax(brackets, D(300000)) == D(20000)
    assert bracket_tax(brackets, D(433375)) == D(46675)


def test_annual_brackets_give_the_same_tax_on_twelve_months():
    annual = synthetic_rule_set(annualised=True).brackets_for("TAX")
    assert bracket_tax(annual, D(433375) * 12) / 12 == D(46675)


def test_professional_relief_is_a_percent_with_a_cap():
    relief = RULES.professional_relief("TAX")
    assert professional_relief_amount(relief, D(453375)) == D(20000)
    assert professional_relief_amount(relief, D(150000)) == D(15000)


def test_family_relief_uses_the_step_for_the_dependants():
    relief = RULES.family_relief("TAX")
    assert family_relief_amount(relief, D(46675), 0) == 0
    assert family_relief_amount(relief, D(46675), 1) == D("4667.5")
    assert family_relief_amount(relief, D(46675), 2) == D(9335)


def test_dependants_beyond_the_last_step_keep_the_last_step():
    assert family_relief_amount(RULES.family_relief("TAX"), D(46675), 7) == D(9335)


def test_an_amount_relief_is_monthly_and_never_exceeds_the_tax():
    relief = FamilyRelief(tax_code="TAX", mode="amount", steps=(FamilyReliefStep(1, D(3000)),))
    assert family_relief_amount(relief, D(10000), 1) == D(3000)
    assert family_relief_amount(relief, D(120000), 1, months=12) == D(36000)
    assert family_relief_amount(relief, D(2000), 1) == D(2000)


def test_a_cap_limits_the_family_relief():
    relief = FamilyRelief(tax_code="TAX", mode="percent_of_tax", steps=(FamilyReliefStep(1, D(50)),), cap_monthly=D(1000))
    assert family_relief_amount(relief, D(10000), 1) == D(1000)


def test_tax_lines_walk_from_taxable_earnings_to_the_rounded_tax():
    got = {line.code: line for line in tax_lines(RULES, GOLDEN_LINES, dependants=2)}
    assert got["TAX_PROF_RELIEF"].amount == D(20000) and got["TAX_PROF_RELIEF"].section == "relief"
    assert got["TAX_FAMILY_RELIEF"].amount == D(9335)
    assert (got["TAX"].base, got["TAX"].amount, got["TAX"].section) == (D(433375), D(37340), "tax")


def test_an_annualised_rule_set_gives_the_same_monthly_tax():
    got = {line.code: line.amount for line in tax_lines(synthetic_rule_set(annualised=True), GOLDEN_LINES, dependants=2)}
    assert (got["TAX_FAMILY_RELIEF"], got["TAX"]) == (D(9335), D(37340))


def test_tax_rounding_follows_the_rule_set_not_the_line_rounding():
    lines = [earning("BASE", 261000, taxable=True), contribution("PENSION", 13050), contribution("HEALTH", 5220)]
    got = {line.code: line.amount for line in tax_lines(RULES, lines, dependants=1)}
    assert got["TAX_FAMILY_RELIEF"] == D(1227)
    assert got["TAX"] == D(11040)
