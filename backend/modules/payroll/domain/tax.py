"""Step 4: from taxable earnings to the tax withheld (the ITS in Mali), with its reliefs."""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from decimal import Decimal

from modules.payroll.domain.inputs import PayslipLine
from modules.payroll.domain.money import ZERO, percent_of
from modules.payroll.domain.rules import FamilyRelief, ProfessionalRelief, RuleSet, TaxBracket

PROFESSIONAL_RELIEF_NAMES = ("Professional expenses relief", "Abattement pour frais professionnels")
FAMILY_RELIEF_NAMES = ("Family relief", "Réduction pour charges de famille")


def taxable_earnings(lines: Iterable[PayslipLine]) -> Decimal:
    return sum((line.amount for line in lines if line.section == "earning" and line.taxable), ZERO)


def deductible_contributions(lines: Iterable[PayslipLine]) -> Decimal:
    return sum((line.amount for line in lines if line.section == "employee_contribution" and line.deductible), ZERO)


def professional_relief_amount(relief: ProfessionalRelief, base: Decimal) -> Decimal:
    amount = percent_of(max(base, ZERO), relief.percent)
    return amount if relief.cap_monthly is None else min(amount, relief.cap_monthly)


def bracket_tax(brackets: Sequence[TaxBracket], amount: Decimal) -> Decimal:
    """Progressive tax on `amount` (brackets sorted by lower bound). Not rounded."""
    tax = ZERO
    for bracket in brackets:
        if amount <= bracket.lower:
            break
        top = amount if bracket.upper is None else min(amount, bracket.upper)
        tax += percent_of(top - bracket.lower, bracket.rate)
    return tax


def family_relief_amount(relief: FamilyRelief, tax: Decimal, dependants: int, *, months: int = 1) -> Decimal:
    """Relief for `dependants` on a tax computed over `months` months; the last step applies beyond it."""
    reached = [step for step in relief.steps if step.dependants <= dependants]
    if not reached or tax <= 0:
        return ZERO
    step = max(reached, key=lambda item: item.dependants)
    amount = percent_of(tax, step.value) if relief.mode == "percent_of_tax" else step.value * months
    if relief.cap_monthly is not None:
        amount = min(amount, relief.cap_monthly * months)
    return min(amount, tax)


def _relief_line(code: str, names: tuple[str, str], amount: Decimal, *, base: Decimal | None = None,
                 qty: Decimal | None = None, rate: Decimal | None = None) -> PayslipLine:
    return PayslipLine(section="relief", code=code, name_en=names[0], name_fr=names[1], amount=amount,
                       base=base, qty=qty, rate=rate)


def tax_lines(rules: RuleSet, lines: Sequence[PayslipLine], dependants: int) -> list[PayslipLine]:
    net_taxable = max(taxable_earnings(lines) - deductible_contributions(lines), ZERO)
    out: list[PayslipLine] = []
    for tax_code in rules.tax_codes():
        professional = rules.professional_relief(tax_code)
        professional_amount = rules.round(professional_relief_amount(professional, net_taxable)) if professional else ZERO
        if professional_amount > 0:
            out.append(_relief_line(f"{tax_code}_PROF_RELIEF", PROFESSIONAL_RELIEF_NAMES, professional_amount,
                                    base=net_taxable, rate=professional.percent))
        taxable = net_taxable - professional_amount
        brackets = rules.brackets_for(tax_code)
        months = 12 if brackets[0].annualised else 1
        tax = bracket_tax(brackets, taxable * months)
        family = rules.family_relief(tax_code)
        relief = family_relief_amount(family, tax, dependants, months=months) if family else ZERO
        if relief > 0:
            out.append(_relief_line(f"{tax_code}_FAMILY_RELIEF", FAMILY_RELIEF_NAMES, rules.round(relief / months),
                                    qty=Decimal(dependants)))
        out.append(PayslipLine(section="tax", code=tax_code, name_en=tax_code, name_fr=tax_code,
                               amount=rules.round_tax((tax - relief) / months), base=taxable,
                               declaration_code=tax_code, display_order=0))
    return out
