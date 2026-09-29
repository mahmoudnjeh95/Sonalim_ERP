from decimal import Decimal

from modules.payroll.domain.inputs import OneOffInput, PayslipLine, PresenceInput
from modules.payroll.domain.net import (
    CarryForward,
    PayslipTotals,
    apply_net_floor,
    deduction_lines,
    employer_charge_lines,
    payslip_totals,
)
from modules.payroll.domain.synthetic import synthetic_rule_set

D = Decimal
RULES = synthetic_rule_set()


def deduction(code, amount, kind, source_id):
    return PayslipLine(section="deduction", code=code, name_en=code, name_fr=code, amount=D(amount),
                       source_kind=kind, source_id=source_id)


def line(section, code, amount, **extra):
    return PayslipLine(section=section, code=code, name_en=code, name_fr=code, amount=D(amount), **extra)


def test_deductions_come_in_priority_order_and_earnings_are_ignored():
    inputs = [
        OneOffInput("CANTEEN", amount=D(3000), source_id="r1"),
        OneOffInput("ADVANCE", amount=D(50000), source_kind="advance", source_id="a1"),
        OneOffInput("LOAN", amount=D(20000), source_kind="loan_instalment", source_id="i1"),
        OneOffInput("CANTEEN", amount=D(5000), source_kind="carry_forward", source_id="c1"),
        OneOffInput("BONUS", amount=D(9)),
    ]
    lines = deduction_lines(inputs, PresenceInput(), RULES)
    assert [(item.code, item.source_kind) for item in lines] == [
        ("CANTEEN", "carry_forward"), ("LOAN", "loan_instalment"), ("ADVANCE", "advance"), ("CANTEEN", "input"),
    ]


def test_deductions_that_fit_are_all_kept():
    kept, carried = apply_net_floor(D(100000), [deduction("LOAN", 20000, "loan_instalment", "i1")])
    assert [item.amount for item in kept] == [D(20000)] and carried == []


def test_the_overflowing_deduction_is_cut_and_the_rest_carried():
    kept, carried = apply_net_floor(D(93000), [
        deduction("CANTEEN", 5000, "carry_forward", "c1"),
        deduction("LOAN", 20000, "loan_instalment", "i1"),
        deduction("ADVANCE", 90000, "advance", "a1"),
        deduction("CANTEEN", 3000, "input", "r1"),
    ])
    assert [(item.code, item.amount) for item in kept] == [("CANTEEN", 5000), ("LOAN", 20000), ("ADVANCE", 68000)]
    assert carried == [CarryForward("ADVANCE", D(22000), "advance", "a1"), CarryForward("CANTEEN", D(3000), "input", "r1")]


def test_nothing_left_means_everything_is_carried():
    kept, carried = apply_net_floor(D(0), [deduction("LOAN", 20000, "loan_instalment", "i1")])
    assert kept == [] and carried == [CarryForward("LOAN", D(20000), "loan_instalment", "i1")]


def test_employer_charges_apply_their_rate_to_their_base():
    lines = employer_charge_lines(RULES, gross=D(497500), contributable=D(487500), earned=D(400000))
    assert [(item.code, item.base, item.amount, item.declaration_code) for item in lines] == [
        ("EMP_TAX", D(497500), D(9950), "EMP_TAX")
    ]


def test_totals_add_up():
    lines = [
        line("earning", "BASE", 400000, taxable=True, contributable=True),
        line("earning", "TRANSPORT", 10000),
        line("employee_contribution", "PENSION", 30000),
        line("employer_contribution", "PENSION", 60000),
        line("tax", "TAX", 20000, base=D(300000)),
        line("deduction", "ADVANCE", 50000),
        line("employer_charge", "EMP_TAX", 8000),
    ]
    assert payslip_totals(lines) == PayslipTotals(
        gross=D(410000), contributable=D(400000), taxable=D(300000), employee_contrib=D(30000),
        employer_contrib=D(60000), employer_charges=D(8000), tax=D(20000), deductions=D(50000),
        net=D(310000), employer_cost=D(478000),
    )
