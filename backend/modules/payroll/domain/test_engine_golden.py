"""Golden payslips computed by hand from the SYNTHETIC rule set (round numbers, not Mali).

The spec asks for golden tests from three real payslips once the accountant provides them; until
then these pin the arithmetic. Each docstring spells the sum out so a reviewer can redo it.
Synthetic rules: 20 working days, 160 h; PENSION 5 % / 10 % capped 500 000; HEALTH 2 % / 3 %;
TAX monthly 0 % to 100 000, 10 % to 300 000, 20 % above; professional relief 10 % capped 20 000;
family relief 10 % (1 dependant), 20 % (2+); tax rounded down to 10; employer tax 2 % of gross.
"""
from dataclasses import replace
from datetime import date
from decimal import Decimal

from core.domain.result import Err, Ok
from modules.payroll.domain.engine import calculate_payslip
from modules.payroll.domain.inputs import SECTIONS, ContractComponent, OneOffInput, PresenceInput, SettlementInput
from modules.payroll.domain.net import CarryForward
from modules.payroll.domain.synthetic import synthetic_employee, synthetic_rule_set

D = Decimal
SEPT = date(2026, 9, 1)
FULL = PresenceInput(scheduled_days=22, worked_days=22)


def totals(result):
    assert isinstance(result, Ok), result
    t = result.value.totals
    return {"gross": t.gross, "employee_contrib": t.employee_contrib, "tax": t.tax, "deductions": t.deductions,
            "net": t.net, "employer_contrib": t.employer_contrib, "employer_charges": t.employer_charges,
            "employer_cost": t.employer_cost}


def line_amounts(result):
    return {(line.section, line.code): line.amount for line in result.value.lines}


def _full_month(rules):
    employee = synthetic_employee(tax_dependants=2, components=(ContractComponent("HOUSING", amount=D(30000)),
                                                                ContractComponent("TRANSPORT", amount=D(10000))))
    return calculate_payslip(employee=employee, presence=replace(FULL, ot_minutes_day=600), rules=rules, period=SEPT,
                             inputs=[OneOffInput("ADVANCE", amount=D(50000), source_kind="advance", source_id="a1")])


FULL_MONTH_TOTALS = {"gross": D(497500), "employee_contrib": D(34125), "tax": D(37340), "deductions": D(50000),
                     "net": D(376035), "employer_contrib": D(63375), "employer_charges": D(9950), "employer_cost": D(570825)}


def test_golden_full_month_with_overtime_allowances_dependants_and_an_advance():
    """BASE 400 000; seniority 5 y → 5 % = 20 000; HOUSING 30 000; TRANSPORT 10 000 (neither taxable
    nor contributable); OT day 10 h × 2 500 × 1.5 = 37 500 → gross 497 500.
    Contributable 487 500: PENSION 24 375 / 48 750; HEALTH 9 750 / 14 625.
    Taxable 487 500 − 34 125 = 453 375 − 20 000 (10 % capped) = 433 375; tax 20 000 + 20 % × 133 375
    = 46 675; 2 dependants −20 % → 37 340. Net 497 500 − 34 125 − 37 340 − 50 000 = 376 035.
    Employer tax 9 950; cost 497 500 + 63 375 + 9 950 = 570 825."""
    result = _full_month(synthetic_rule_set())
    assert totals(result) == FULL_MONTH_TOTALS
    amounts = line_amounts(result)
    assert amounts[("earning", "SENIORITY")] == D(20000)
    assert amounts[("relief", "TAX_PROF_RELIEF")] == D(20000)
    assert amounts[("relief", "TAX_FAMILY_RELIEF")] == D(9335)
    assert result.value.warnings == () and result.value.carry_forwards == ()
    sections = [line.section for line in result.value.lines]
    assert sections == sorted(sections, key=SECTIONS.index)


def test_golden_annual_brackets_give_the_same_payslip():
    assert totals(_full_month(synthetic_rule_set(annualised=True))) == FULL_MONTH_TOTALS


def test_golden_mid_month_hire_with_unpaid_absence():
    """Hired 11 Sept, 14 of 20 days: BASE 280 000; 2 unpaid days −40 000; HOUSING 21 000; TRANSPORT
    7 000 → gross 268 000. Contributable 261 000: PENSION 13 050 / 26 100; HEALTH 5 220 / 7 830.
    Taxable 242 730 − 20 000 = 222 730; tax 12 273; 1 dependant −10 % = 11 045.7 → 11 040.
    Net 268 000 − 18 270 − 11 040 = 238 690. Employer tax 5 360; cost 307 290."""
    employee = synthetic_employee(hire_date=date(2026, 9, 11), contract_start=date(2026, 9, 11), tax_dependants=1,
                                  components=(ContractComponent("HOUSING", amount=D(30000)),
                                              ContractComponent("TRANSPORT", amount=D(10000))))
    result = calculate_payslip(employee=employee, presence=PresenceInput(scheduled_days=14, worked_days=12, unpaid_absence_days=2),
                               rules=synthetic_rule_set(), period=SEPT)
    assert totals(result) == {"gross": D(268000), "employee_contrib": D(18270), "tax": D(11040), "deductions": D(0),
                              "net": D(238690), "employer_contrib": D(33930), "employer_charges": D(5360),
                              "employer_cost": D(307290)}


def test_golden_daily_worker():
    """Day rate 10 000 × (18 worked + 1 leave + 1 holiday) = 200 000; seniority 6 y → 5 % = 10 000;
    MEAL 500 × 18 = 9 000 (neither taxable nor contributable); OT night 1.5 h × (200 000 / 160 = 1 250)
    × 2 = 3 750 → gross 222 750. Contributable 213 750: PENSION 10 688 / 21 375; HEALTH 4 275 / 6 413.
    Taxable 213 750 − 14 963 = 198 787 − 19 879 (10 %) = 178 908; tax 7 890.8 → 7 890.
    Net 222 750 − 14 963 − 7 890 = 199 897. Employer tax 4 455; cost 254 993."""
    employee = synthetic_employee(base_salary=D(10000), pay_frequency="daily", hire_date=date(2020, 3, 1),
                                  contract_start=date(2020, 3, 1), components=(ContractComponent("MEAL"),))
    presence = PresenceInput(scheduled_days=22, worked_days=18, paid_leave_days=1, holiday_days=1, ot_minutes_night=90)
    result = calculate_payslip(employee=employee, presence=presence, rules=synthetic_rule_set(), period=SEPT)
    assert totals(result) == {"gross": D(222750), "employee_contrib": D(14963), "tax": D(7890), "deductions": D(0),
                              "net": D(199897), "employer_contrib": D(27788), "employer_charges": D(4455),
                              "employer_cost": D(254993)}


def test_golden_net_negative_carries_the_overflow():
    """Gross 100 000; contributions 7 000; taxable 93 000 − 9 300 = 83 700 → no tax. Available 93 000:
    carried canteen 5 000, loan 20 000, then the 90 000 advance only fits 68 000 → 22 000 carried."""
    employee = synthetic_employee(base_salary=D(100000), hire_date=date(2026, 1, 1), contract_start=date(2026, 1, 1))
    inputs = [
        OneOffInput("ADVANCE", amount=D(90000), source_kind="advance", source_id="a1"),
        OneOffInput("LOAN", amount=D(20000), source_kind="loan_instalment", source_id="i1"),
        OneOffInput("CANTEEN", amount=D(5000), source_kind="carry_forward", source_id="c1"),
    ]
    result = calculate_payslip(employee=employee, presence=FULL, rules=synthetic_rule_set(), period=SEPT, inputs=inputs)
    assert totals(result) == {"gross": D(100000), "employee_contrib": D(7000), "tax": D(0), "deductions": D(93000),
                              "net": D(0), "employer_contrib": D(13000), "employer_charges": D(2000),
                              "employer_cost": D(115000)}
    assert result.value.carry_forwards == (CarryForward("ADVANCE", D(22000), "advance", "a1"),)
    assert result.value.warnings == ("NET_NEGATIVE",)


def test_golden_final_settlement():
    """Leaves 15 Sept after 12 years, 10 of 20 days: BASE 150 000; seniority 5 % = 7 500; leave 10 d ×
    15 000 = 150 000; notice 1 month 300 000; severance 5×20 % + 5×25 % + 2×30 % of 300 000 = 855 000
    (not taxable, not contributable) → gross 1 462 500. Contributable 607 500: PENSION capped 500 000
    → 25 000 / 50 000; HEALTH 12 150 / 18 225. Taxable 570 350 − 20 000 = 550 350; tax 20 000 + 20 % ×
    250 350 = 70 070. Net 1 462 500 − 37 150 − 70 070 = 1 355 280. Employer tax 29 250; cost 1 559 975."""
    employee = synthetic_employee(base_salary=D(300000), hire_date=date(2014, 9, 15), contract_start=date(2014, 9, 15),
                                  termination_date=date(2026, 9, 15))
    settlement = SettlementInput(reference_salary=D(300000), years_of_service=D(12), unused_leave_days=D(10), notice_months=D(1))
    result = calculate_payslip(employee=employee, presence=PresenceInput(scheduled_days=10, worked_days=10),
                               rules=synthetic_rule_set(), period=SEPT, settlement=settlement)
    assert totals(result) == {"gross": D(1462500), "employee_contrib": D(37150), "tax": D(70070), "deductions": D(0),
                              "net": D(1355280), "employer_contrib": D(68225), "employer_charges": D(29250),
                              "employer_cost": D(1559975)}


def test_golden_correction_payslip_pays_only_the_typed_inputs():
    """Bonus 25 000 alone: PENSION 1 250 / 2 500; HEALTH 500 / 750; taxable 23 250 − 2 325 → no tax.
    Net 23 250; employer tax 500; cost 28 750."""
    result = calculate_payslip(employee=synthetic_employee(), presence=FULL, rules=synthetic_rule_set(), period=SEPT,
                               inputs=[OneOffInput("BONUS", amount=D(25000))], include_salary=False)
    assert totals(result) == {"gross": D(25000), "employee_contrib": D(1750), "tax": D(0), "deductions": D(0),
                              "net": D(23250), "employer_contrib": D(3250), "employer_charges": D(500),
                              "employer_cost": D(28750)}
    assert ("earning", "BASE") not in line_amounts(result)


def test_a_missing_component_is_a_bilingual_refusal():
    rules = synthetic_rule_set()
    rules = replace(rules, components=tuple(component for component in rules.components if component.code != "OT_NIGHT"))
    result = calculate_payslip(employee=synthetic_employee(), presence=replace(FULL, ot_minutes_night=60), rules=rules, period=SEPT)
    assert isinstance(result, Err) and result.code == "COMPONENT_MISSING"
    assert (result.message, result.message_fr) == ("the rule set has no component OT_NIGHT", "le jeu de règles n'a pas de rubrique OT_NIGHT")


def test_a_misused_component_is_a_bilingual_refusal():
    employee = synthetic_employee(components=(ContractComponent("CANTEEN", amount=D(1)),))
    result = calculate_payslip(employee=employee, presence=FULL, rules=synthetic_rule_set(), period=SEPT)
    assert isinstance(result, Err) and result.code == "COMPONENT_INVALID" and result.message_fr
