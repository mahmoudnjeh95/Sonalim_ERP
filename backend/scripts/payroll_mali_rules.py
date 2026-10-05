"""Mali payroll rule-set values: a DRAFT starting point for the accountant to confirm.

Every number below (contribution rates, ceilings, ITS brackets, family and professional reliefs,
seniority, overtime and severance scales, employer charges, working days/hours, which earnings
are taxable or contributable) is seed data, never code, and is written from general public
knowledge of Mali's payroll structure (INPS pension/family-benefit/work-accident contributions,
AMO health cover, progressive ITS income tax) -- NOT a verified current-year rate table, since
those change with each year's finance law. The rule set this module creates is left `draft`
deliberately: `RuleSetService.confirm_rule_set` would find nothing structurally missing (brackets
have no gaps/overlaps, every component, band and relief the engine needs is present), but going
live on unconfirmed numbers would break "no invented numbers pay anyone" (spec, "Rule on
statutory values"). A run can be calculated on it; approval is refused until it is confirmed.

    .venv/Scripts/python -m scripts.payroll_mali_rules   # prints the values; seed_hr_payroll writes them
"""
from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any

from core.domain.result import Err
from modules.payroll.api.rule_set_service import RuleSetService
from modules.payroll.domain.declarations import EMPLOYER_TAXES

MALI_VALID_FROM = datetime.date(2026, 1, 1)
D = Decimal

# Rule-set header. daily_rest_day_pay: how a daily-paid worker's worked rest day is paid --
# "overtime_only" (its rest/holiday overtime, like a monthly worker) or "day_rate_and_overtime".
_HEADER: dict[str, Any] = {
    "country": "ML",
    "name": "Mali (brouillon, à confirmer)",
    "valid_from": MALI_VALID_FROM,
    "working_days_per_month": D(26),
    "working_hours_per_month": D(208),
    "round_to": 1,
    "round_mode": "half_up",
    "tax_round_to": 1,
    "tax_round_mode": "half_up",
    "settlement_reference_months": 12,
    "daily_rest_day_pay": "overtime_only",
    "notes": "Valeurs DEMO à confirmer par le comptable avant toute paie réelle.",
}

_COMPONENTS: list[dict[str, Any]] = [
    {"code": "BASE", "name_en": "Base salary", "name_fr": "Salaire de base", "kind": "earning",
     "taxable": True, "contributable": True, "formula_type": "fixed", "display_order": 10, "payslip_section": "earnings"},
    {"code": "UNPAID_ABSENCE", "name_en": "Unpaid absence", "name_fr": "Absence non payée", "kind": "earning",
     "taxable": True, "contributable": True, "formula_type": "per_day", "display_order": 11, "payslip_section": "earnings"},
    {"code": "SENIORITY", "name_en": "Seniority bonus", "name_fr": "Prime d'ancienneté", "kind": "earning",
     "taxable": True, "contributable": True, "formula_type": "rate_x_base", "base_ref": "earned_base", "display_order": 20,
     "payslip_section": "earnings"},
    {"code": "OT_DAY", "name_en": "Overtime (day)", "name_fr": "Heures supplémentaires (jour)", "kind": "earning",
     "taxable": True, "contributable": True, "formula_type": "qty_x_rate", "display_order": 30, "payslip_section": "earnings"},
    {"code": "OT_NIGHT", "name_en": "Overtime (night)", "name_fr": "Heures supplémentaires (nuit)", "kind": "earning",
     "taxable": True, "contributable": True, "formula_type": "qty_x_rate", "display_order": 31, "payslip_section": "earnings"},
    {"code": "OT_REST_HOLIDAY", "name_en": "Overtime (rest day / holiday)", "name_fr": "Heures supplémentaires (repos / férié)",
     "kind": "earning", "taxable": True, "contributable": True, "formula_type": "qty_x_rate", "display_order": 32,
     "payslip_section": "earnings"},
    {"code": "TRANSPORT", "name_en": "Transport allowance", "name_fr": "Indemnité de transport", "kind": "earning",
     "taxable": False, "contributable": False, "formula_type": "fixed", "default_amount": 15000, "display_order": 40,
     "payslip_section": "earnings"},
    {"code": "HOUSING", "name_en": "Housing allowance", "name_fr": "Indemnité de logement", "kind": "earning",
     "taxable": True, "contributable": True, "formula_type": "fixed", "default_amount": 50000, "display_order": 41,
     "payslip_section": "earnings"},
    {"code": "BONUS", "name_en": "Bonus", "name_fr": "Prime exceptionnelle", "kind": "earning",
     "taxable": True, "contributable": True, "formula_type": "fixed", "display_order": 50, "payslip_section": "earnings"},
    {"code": "LEAVE_INDEMNITY", "name_en": "Paid-leave indemnity", "name_fr": "Indemnité compensatrice de congés",
     "kind": "earning", "taxable": True, "contributable": True, "formula_type": "per_day", "display_order": 60,
     "payslip_section": "earnings"},
    {"code": "NOTICE_INDEMNITY", "name_en": "Notice indemnity", "name_fr": "Indemnité de préavis", "kind": "earning",
     "taxable": True, "contributable": True, "formula_type": "fixed", "display_order": 61, "payslip_section": "earnings"},
    {"code": "SEVERANCE", "name_en": "Severance pay", "name_fr": "Indemnité de licenciement", "kind": "earning",
     "taxable": False, "contributable": False, "formula_type": "fixed", "display_order": 62, "payslip_section": "earnings"},
    {"code": "ADVANCE", "name_en": "Salary advance", "name_fr": "Avance sur salaire", "kind": "deduction",
     "taxable": False, "contributable": False, "formula_type": "fixed", "display_order": 80, "payslip_section": "deductions"},
    {"code": "LOAN", "name_en": "Loan instalment", "name_fr": "Échéance de prêt", "kind": "deduction",
     "taxable": False, "contributable": False, "formula_type": "fixed", "display_order": 81, "payslip_section": "deductions"},
    {"code": "TAXE_LOGEMENT", "name_en": "Housing tax (employer)", "name_fr": "Taxe logement", "kind": "employer_charge",
     "taxable": False, "contributable": False, "formula_type": "rate_x_base", "base_ref": "gross", "default_rate": "1",
     "display_order": 90, "payslip_section": "employer", "declaration_code": EMPLOYER_TAXES},
    {"code": "CFE", "name_en": "Employer flat-rate contribution", "name_fr": "Contribution forfaitaire employeur",
     "kind": "employer_charge", "taxable": False, "contributable": False, "formula_type": "rate_x_base", "base_ref": "gross",
     "default_rate": "3.5", "display_order": 91, "payslip_section": "employer", "declaration_code": EMPLOYER_TAXES},
    {"code": "FORMATION", "name_en": "Vocational training levy (ANPE/FAFPA)", "name_fr": "Taxe formation professionnelle (ANPE/FAFPA)",
     "kind": "employer_charge", "taxable": False, "contributable": False, "formula_type": "rate_x_base", "base_ref": "gross",
     "default_rate": "2", "display_order": 92, "payslip_section": "employer", "declaration_code": EMPLOYER_TAXES},
]

# declaration_code is also how a declaration finds each employee's number: "<code>_no", i.e.
# hr's inps_no / amo_no (payroll.domain.declarations), so these codes are INPS and AMO.
_CONTRIBUTIONS: list[dict[str, Any]] = [
    {"code": "PENSION", "name_en": "INPS pension", "name_fr": "INPS retraite", "base": "contributable",
     "employee_rate": "3.6", "employer_rate": "5.4", "ceiling_monthly": 600000, "deductible_from_taxable": True,
     "declaration_code": "INPS", "display_order": 10},
    {"code": "FAMILY", "name_en": "INPS family benefits", "name_fr": "INPS prestations familiales", "base": "contributable",
     "employee_rate": "0", "employer_rate": "8", "ceiling_monthly": 600000, "deductible_from_taxable": True,
     "declaration_code": "INPS", "display_order": 11},
    {"code": "WORK_ACCIDENT", "name_en": "INPS work accident", "name_fr": "INPS accidents du travail", "base": "contributable",
     "employee_rate": "0", "employer_rate": "3", "ceiling_monthly": 600000, "deductible_from_taxable": True,
     "declaration_code": "INPS", "display_order": 12},
    {"code": "AMO", "name_en": "AMO health cover", "name_fr": "AMO assurance maladie", "base": "contributable",
     "employee_rate": "3.06", "employer_rate": "3.5", "ceiling_monthly": None, "deductible_from_taxable": True,
     "declaration_code": "AMO", "display_order": 20},
]

_TAX_CODE = "ITS"
# (lower, upper, rate %) monthly ITS brackets -- to confirm against the current finance law.
_ITS_BRACKETS = [
    (0, 175000, 0), (175000, 600000, 5), (600000, 1200000, 13), (1200000, 1800000, 20),
    (1800000, 2400000, 28), (2400000, 3500000, 34), (3500000, None, 40),
]
# Family relief: % of the ITS by number of dependants (the last step applies beyond it).
_FAMILY_RELIEF_STEPS = [(1, "10"), (2, "15"), (3, "20"), (4, "23"), (5, "25"), (6, "30")]
_FAMILY_RELIEF_CAP = None
# Professional-expenses relief: % of the net taxable, before the brackets.
_PROFESSIONAL_RELIEF_PERCENT = "20"
_PROFESSIONAL_RELIEF_CAP = None

_SENIORITY = [(2, 2), (5, 5), (10, 10), (15, 15), (20, 20), (25, 25)]  # years_from, % of earned base
_OVERTIME = [("day", "1.4"), ("night", "1.75"), ("rest_holiday", "2")]  # band_code, multiplier
_SEVERANCE = [(0, 20), (5, 25), (10, 30)]  # years_from, % of reference salary per year


def _ok(result):
    if isinstance(result, Err):
        raise RuntimeError(f"{result.code}: {result.message}")
    return result.value


def _fcfa(amount) -> str:
    return f"{int(amount):,}".replace(",", " ") + " F CFA"


def _rows() -> list[tuple[str, dict[str, Any]]]:
    """Every rule row as (CHILD_KINDS kind, the values RuleSetService.add_child validates)."""
    rows: list[tuple[str, dict[str, Any]]] = []
    rows += [("components", dict(component)) for component in _COMPONENTS]
    rows += [("contributions", dict(contribution)) for contribution in _CONTRIBUTIONS]
    rows += [("tax_brackets", {"tax_code": _TAX_CODE, "lower_bound": lower, "upper_bound": upper, "rate": rate,
                               "annualised": False}) for lower, upper, rate in _ITS_BRACKETS]
    rows.append(("tax_reliefs", {"tax_code": _TAX_CODE, "kind": "family", "parameters": {
        "mode": "percent_of_tax", "cap_monthly": _FAMILY_RELIEF_CAP,
        "steps": [{"dependants": dependants, "value": value} for dependants, value in _FAMILY_RELIEF_STEPS]}}))
    rows.append(("tax_reliefs", {"tax_code": _TAX_CODE, "kind": "professional_expenses", "parameters": {
        "percent": _PROFESSIONAL_RELIEF_PERCENT, "cap_monthly": _PROFESSIONAL_RELIEF_CAP}}))
    rows += [("seniority_scale", {"years_from": years_from, "percent": percent}) for years_from, percent in _SENIORITY]
    rows += [("overtime_rates", {"band_code": band_code, "multiplier": multiplier}) for band_code, multiplier in _OVERTIME]
    rows += [("severance_scale", {"years_from": years_from, "percent_per_year": percent_per_year})
             for years_from, percent_per_year in _SEVERANCE]
    return rows


def create_mali_rule_set(service: RuleSetService, *, tenant_id: str, actor_id: str) -> dict:
    """Write the Mali rule set through the real service and return it. It stays a DRAFT."""
    created = _ok(service.create_rule_set(tenant_id=tenant_id, actor_id=actor_id, **_HEADER))
    rule_set_id = created["id"]
    for kind, values in _rows():
        _ok(service.add_child(tenant_id=tenant_id, actor_id=actor_id, rule_set_id=rule_set_id, kind=kind, values=values))
    return service.get_rule_set(tenant_id=tenant_id, rule_set_id=rule_set_id)


def _percent(value) -> str:
    return f"{value} %"


def print_to_confirm() -> None:
    h = _HEADER
    print("\n=========== TO CONFIRM BY ACCOUNTANT: Mali payroll rule set (DRAFT) ===========")
    print(f"  rule set \"{h['name']}\" starts {MALI_VALID_FROM.isoformat()}; status left as DRAFT (this seed confirms nothing)")
    print(f"  working days per month {h['working_days_per_month']}, working hours per month {h['working_hours_per_month']}"
          " (hourly rate = monthly salary / working hours)")
    print(f"  rounding: amounts to {h['round_to']} F CFA ({h['round_mode']}), ITS to {h['tax_round_to']} F CFA ({h['tax_round_mode']})")
    print(f"  settlement reference salary: average gross of the last {h['settlement_reference_months']} months")
    print(f"  daily worker's worked rest day: {h['daily_rest_day_pay']}"
          " (overtime_only = its rest/holiday overtime only; day_rate_and_overtime = day rate as well)")
    print("  components (kind, formula, taxable / contributable, default):")
    for c in _COMPONENTS:
        flags = f"{'taxable' if c['taxable'] else 'not taxable'} / {'contributable' if c['contributable'] else 'not contributable'}"
        default = (_fcfa(c["default_amount"]) if c.get("default_amount") is not None
                   else f"{c['default_rate']} % of {c['base_ref']}" if c.get("default_rate") is not None else "-")
        print(f"    {c['code']:<16} {c['kind']:<15} {c['formula_type']:<11} {flags:<32} {default}")
    print("  contributions (employee % / employer % of the contributable base, monthly ceiling, declared under):")
    for row in _CONTRIBUTIONS:
        ceiling = _fcfa(row["ceiling_monthly"]) if row["ceiling_monthly"] else "none"
        deductible = "deductible from ITS base" if row["deductible_from_taxable"] else "not deductible"
        print(f"    {row['code']:<14} {row['employee_rate']:>5} % / {row['employer_rate']:>5} %  ceiling {ceiling:<16}"
              f" {row['declaration_code']:<5} {deductible}")
    print("    WORK_ACCIDENT's rate depends on the company's risk class; maternity has no row of its own here"
          " (confirm whether FAMILY covers it); liability account codes are left empty.")
    print(f"  {_TAX_CODE} monthly brackets (lower, upper, rate):")
    for lower, upper, rate in _ITS_BRACKETS:
        range_text = f"to {_fcfa(upper)}" if upper is not None else "and above"
        print(f"    {_fcfa(lower):>16} {range_text:<19} : {rate} %")
    cap = _fcfa(_FAMILY_RELIEF_CAP) if _FAMILY_RELIEF_CAP is not None else "no cap"
    last = _FAMILY_RELIEF_STEPS[-1][0]
    print(f"  {_TAX_CODE} family relief (% of the tax by dependants, {cap}): "
          + ", ".join(f"{dependants}{'+' if dependants == last else ''}={_percent(value)}"
                      for dependants, value in _FAMILY_RELIEF_STEPS))
    cap = _fcfa(_PROFESSIONAL_RELIEF_CAP) if _PROFESSIONAL_RELIEF_CAP is not None else "no cap"
    print(f"  {_TAX_CODE} professional expenses relief: {_percent(_PROFESSIONAL_RELIEF_PERCENT)} of the net taxable, {cap}")
    print("  employer charges (% of gross): "
          + ", ".join(f"{c['code']} {_percent(c['default_rate'])}" for c in _COMPONENTS if c["kind"] == "employer_charge"))
    print("  seniority scale (years -> % of earned base): " + ", ".join(f"{y}y={_percent(p)}" for y, p in _SENIORITY))
    print("  overtime multipliers: " + ", ".join(f"{band}=x{mult}" for band, mult in _OVERTIME))
    print("  severance scale (years -> % of reference salary per year): " + ", ".join(f"{y}y={_percent(p)}" for y, p in _SEVERANCE))
    print("  TRANSPORT and HOUSING default amounts, and every rate above, are DEMO placeholders.")
    print("================================================================================")


if __name__ == "__main__":
    print_to_confirm()
