"""Checks on rule rows before they are stored, and on a whole rule set before it is confirmed.

Each validator takes the values an admin typed (strings, ints, floats or Decimals) and returns
the cleaned row, keyed by the DB column names, or Err("RULE_INVALID", english, french).
"""
from __future__ import annotations

import datetime
import re
from decimal import Decimal, InvalidOperation
from typing import Any

from core.domain.result import Err, Ok, Result
from modules.payroll.domain.money import ROUND_MODES
from modules.payroll.domain.rules import (
    BASE,
    OVERTIME_BANDS,
    SYSTEM_COMPONENTS,
    UNPAID_ABSENCE,
    FamilyRelief,
    FamilyReliefStep,
    ProfessionalRelief,
    RuleSet,
)

CODE = re.compile(r"^[A-Z][A-Z0-9_]{0,31}$")
COUNTRY = re.compile(r"^[A-Z]{2}$")
COMPONENT_KINDS = ("earning", "deduction", "employer_charge")
FORMULA_TYPES = ("fixed", "rate_x_base", "qty_x_rate", "per_day")
BASE_REFS = ("base_salary", "earned_base", "gross", "contributable")
PAYSLIP_SECTIONS = ("earnings", "deductions", "employer")
CONTRIBUTION_BASES = ("gross", "contributable")
RELIEF_KINDS = ("family", "professional_expenses")
FAMILY_MODES = ("percent_of_tax", "amount")
_SECTION_FOR_KIND = {"earning": "earnings", "deduction": "deductions", "employer_charge": "employer"}
_HUNDRED = Decimal(100)


class _Invalid(ValueError):
    def __init__(self, english: str, french: str) -> None:
        super().__init__(english)
        self.english = english
        self.french = french


def _refused(problem: _Invalid) -> Err:
    return Err("RULE_INVALID", problem.english, problem.french)


def _missing(values: dict[str, Any], name: str) -> bool:
    raw = values.get(name)
    return raw is None or (isinstance(raw, str) and raw.strip() == "")


def _decimal(values, name, *, required=True, minimum=None, maximum=None) -> Decimal | None:
    if _missing(values, name):
        if required:
            raise _Invalid(f"{name} is required", f"{name} est obligatoire")
        return None
    raw = values[name]
    if isinstance(raw, bool):
        raise _Invalid(f"{name} must be a number", f"{name} doit être un nombre")
    try:
        value = raw if isinstance(raw, Decimal) else Decimal(str(raw).strip().replace(",", "."))
    except (InvalidOperation, ValueError):
        raise _Invalid(f"{name} must be a number", f"{name} doit être un nombre") from None
    if not value.is_finite():
        raise _Invalid(f"{name} must be a number", f"{name} doit être un nombre")
    if minimum is not None and value < minimum:
        raise _Invalid(f"{name} must be at least {minimum}", f"{name} doit être au moins {minimum}")
    if maximum is not None and value > maximum:
        raise _Invalid(f"{name} must be at most {maximum}", f"{name} doit être au plus {maximum}")
    return value


def _money(values, name, *, required=True, minimum=Decimal(0)) -> Decimal | None:
    value = _decimal(values, name, required=required, minimum=minimum)
    if value is not None and value != value.to_integral_value():
        raise _Invalid(f"{name} is in whole francs", f"{name} s'exprime en francs entiers")
    return value


def _percent(values, name, *, required=True) -> Decimal | None:
    return _decimal(values, name, required=required, minimum=Decimal(0), maximum=_HUNDRED)


def _integer(values, name, *, minimum=0, default=None) -> int:
    if _missing(values, name):
        if default is None:
            raise _Invalid(f"{name} is required", f"{name} est obligatoire")
        return default
    value = _decimal(values, name, minimum=Decimal(minimum))
    if value != value.to_integral_value():
        raise _Invalid(f"{name} must be a whole number", f"{name} doit être un nombre entier")
    return int(value)


def _text(values, name, *, required=True) -> str | None:
    if _missing(values, name):
        if required:
            raise _Invalid(f"{name} is required", f"{name} est obligatoire")
        return None
    return str(values[name]).strip()


def _code(values, name, *, required=True) -> str | None:
    text = _text(values, name, required=required)
    if text is None:
        return None
    code = text.upper()
    if not CODE.match(code):
        raise _Invalid(f"{name} uses capitals, digits and _ (e.g. OT_DAY)",
                       f"{name} s'écrit en majuscules, chiffres et _ (ex. OT_DAY)")
    return code


def _choice(values, name, choices, *, default=None, required=True) -> str | None:
    if _missing(values, name):
        if default is not None:
            return default
        if required:
            raise _Invalid(f"{name} is required", f"{name} est obligatoire")
        return None
    value = str(values[name]).strip()
    if value not in choices:
        allowed = ", ".join(choices)
        raise _Invalid(f"{name} must be one of {allowed}", f"{name} doit valoir l'une de ces valeurs : {allowed}")
    return value


def _flag(values, name, *, default=False) -> bool:
    raw = values.get(name, default)
    if raw is None:
        return default
    if not isinstance(raw, bool):
        raise _Invalid(f"{name} is true or false", f"{name} vaut vrai ou faux")
    return raw


def validate_rule_set_header(values: dict[str, Any]) -> Result[dict[str, Any]]:
    try:
        country = (_text(values, "country") or "").upper()
        if not COUNTRY.match(country):
            raise _Invalid("country is a two-letter ISO code (e.g. ML)", "le pays est un code ISO à deux lettres (ex. ML)")
        valid_from = values.get("valid_from")
        if not isinstance(valid_from, datetime.date) or valid_from.day != 1:
            raise _Invalid("valid_from is the first day of a month", "valid_from est le premier jour d'un mois")
        return Ok({
            "country": country,
            "name": _text(values, "name"),
            "valid_from": valid_from,
            "round_to": _integer(values, "round_to", minimum=1, default=1),
            "round_mode": _choice(values, "round_mode", ROUND_MODES, default="half_up"),
            "tax_round_to": _integer(values, "tax_round_to", minimum=1, default=1),
            "tax_round_mode": _choice(values, "tax_round_mode", ROUND_MODES, default="half_up"),
            "working_days_per_month": _decimal(values, "working_days_per_month", minimum=Decimal(1), maximum=Decimal(31)),
            "working_hours_per_month": _decimal(values, "working_hours_per_month", minimum=Decimal(1), maximum=Decimal(744)),
            "settlement_reference_months": _integer(values, "settlement_reference_months", minimum=1, default=12),
            "notes": _text(values, "notes", required=False),
        })
    except _Invalid as problem:
        return _refused(problem)


def validate_component(values: dict[str, Any]) -> Result[dict[str, Any]]:
    try:
        code = _code(values, "code")
        kind = _choice(values, "kind", COMPONENT_KINDS)
        formula = _choice(values, "formula_type", FORMULA_TYPES)
        base_ref = _choice(values, "base_ref", BASE_REFS, required=False)
        if formula == "rate_x_base" and base_ref is None:
            raise _Invalid("a rate_x_base component needs its base (base_ref)",
                           "une rubrique taux × base doit indiquer sa base (base_ref)")
        if kind == "earning" and base_ref in ("gross", "contributable"):
            raise _Invalid("an earning cannot be computed on the gross it is part of",
                           "un gain ne peut pas être calculé sur le brut dont il fait partie")
        if kind == "employer_charge" and formula not in ("fixed", "rate_x_base"):
            raise _Invalid("an employer charge is fixed or a rate × base", "une charge patronale est fixe ou un taux × base")
        if code in SYSTEM_COMPONENTS and SYSTEM_COMPONENTS[code] != (kind, formula):
            expected_kind, expected_formula = SYSTEM_COMPONENTS[code]
            raise _Invalid(f"{code} is computed by the engine as {expected_kind} / {expected_formula}",
                           f"{code} est calculée par le moteur en {expected_kind} / {expected_formula}")
        is_earning = kind == "earning"
        return Ok({
            "code": code,
            "name_en": _text(values, "name_en"),
            "name_fr": _text(values, "name_fr"),
            "kind": kind,
            "taxable": _flag(values, "taxable") if is_earning else False,
            "contributable": _flag(values, "contributable") if is_earning else False,
            "formula_type": formula,
            "base_ref": base_ref,
            "default_amount": _money(values, "default_amount", required=False),
            "default_rate": _percent(values, "default_rate", required=False),
            "display_order": _integer(values, "display_order", minimum=0, default=100),
            "payslip_section": _choice(values, "payslip_section", PAYSLIP_SECTIONS, default=_SECTION_FOR_KIND[kind]),
            "declaration_code": _code(values, "declaration_code", required=False),
        })
    except _Invalid as problem:
        return _refused(problem)


def validate_contribution(values: dict[str, Any]) -> Result[dict[str, Any]]:
    try:
        return Ok({
            "code": _code(values, "code"),
            "name_en": _text(values, "name_en"),
            "name_fr": _text(values, "name_fr"),
            "base": _choice(values, "base", CONTRIBUTION_BASES),
            "employee_rate": _percent(values, "employee_rate", required=False) or Decimal(0),
            "employer_rate": _percent(values, "employer_rate", required=False) or Decimal(0),
            "ceiling_monthly": _money(values, "ceiling_monthly", required=False, minimum=Decimal(1)),
            "deductible_from_taxable": _flag(values, "deductible_from_taxable", default=True),
            "declaration_code": _code(values, "declaration_code"),
            "liability_account_code": _text(values, "liability_account_code", required=False),
            "display_order": _integer(values, "display_order", minimum=0, default=100),
        })
    except _Invalid as problem:
        return _refused(problem)


def validate_tax_bracket(values: dict[str, Any]) -> Result[dict[str, Any]]:
    try:
        lower = _money(values, "lower_bound")
        upper = _money(values, "upper_bound", required=False)
        if upper is not None and upper <= lower:
            raise _Invalid("upper_bound must be above lower_bound", "upper_bound doit être supérieur à lower_bound")
        return Ok({
            "tax_code": _code(values, "tax_code"),
            "lower_bound": lower,
            "upper_bound": upper,
            "rate": _percent(values, "rate"),
            "annualised": _flag(values, "annualised"),
        })
    except _Invalid as problem:
        return _refused(problem)


def _family_relief(tax_code: str, parameters: dict[str, Any]) -> FamilyRelief:
    mode = _choice(parameters, "mode", FAMILY_MODES)
    raw_steps = parameters.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise _Invalid("a family relief needs at least one step {dependants, value}",
                       "une réduction pour charges de famille demande au moins un palier {dependants, value}")
    steps: list[FamilyReliefStep] = []
    for raw in raw_steps:
        if not isinstance(raw, dict):
            raise _Invalid("each step is {dependants, value}", "chaque palier est {dependants, value}")
        value = _percent(raw, "value") if mode == "percent_of_tax" else _money(raw, "value")
        steps.append(FamilyReliefStep(dependants=_integer(raw, "dependants", minimum=0), value=value))
    if len({step.dependants for step in steps}) != len(steps):
        raise _Invalid("two steps have the same number of dependants", "deux paliers ont le même nombre de personnes à charge")
    return FamilyRelief(tax_code=tax_code, mode=mode, steps=tuple(sorted(steps, key=lambda step: step.dependants)),
                        cap_monthly=_money(parameters, "cap_monthly", required=False))


def _professional_relief(tax_code: str, parameters: dict[str, Any]) -> ProfessionalRelief:
    return ProfessionalRelief(tax_code=tax_code, percent=_percent(parameters, "percent"),
                              cap_monthly=_money(parameters, "cap_monthly", required=False))


def relief_from_parameters(tax_code: str, kind: str, parameters: dict[str, Any]) -> FamilyRelief | ProfessionalRelief:
    """Stored JSON -> domain relief. Raises ValueError (an _Invalid) on data that was never validated."""
    if kind == "family":
        return _family_relief(tax_code, parameters)
    if kind == "professional_expenses":
        return _professional_relief(tax_code, parameters)
    raise _Invalid(f"unknown relief kind {kind}", f"type d'abattement inconnu {kind}")


def relief_parameters(relief: FamilyRelief | ProfessionalRelief) -> dict[str, Any]:
    """Domain relief -> the JSON stored in payroll.tax_reliefs.parameters (decimals as strings)."""
    cap = None if relief.cap_monthly is None else str(relief.cap_monthly)
    if isinstance(relief, FamilyRelief):
        return {"mode": relief.mode, "cap_monthly": cap,
                "steps": [{"dependants": step.dependants, "value": str(step.value)} for step in relief.steps]}
    return {"percent": str(relief.percent), "cap_monthly": cap}


def validate_tax_relief(values: dict[str, Any]) -> Result[dict[str, Any]]:
    try:
        tax_code = _code(values, "tax_code")
        kind = _choice(values, "kind", RELIEF_KINDS)
        parameters = values.get("parameters")
        if not isinstance(parameters, dict):
            raise _Invalid("parameters is a JSON object", "parameters est un objet JSON")
        relief = relief_from_parameters(tax_code, kind, parameters)
        return Ok({"tax_code": tax_code, "kind": kind, "parameters": relief_parameters(relief)})
    except _Invalid as problem:
        return _refused(problem)


def validate_seniority_step(values: dict[str, Any]) -> Result[dict[str, Any]]:
    try:
        return Ok({"years_from": _integer(values, "years_from", minimum=0), "percent": _percent(values, "percent")})
    except _Invalid as problem:
        return _refused(problem)


def validate_overtime_rate(values: dict[str, Any]) -> Result[dict[str, Any]]:
    try:
        return Ok({
            "band_code": _choice(values, "band_code", OVERTIME_BANDS),
            "multiplier": _decimal(values, "multiplier", minimum=Decimal(1), maximum=Decimal(10)),
        })
    except _Invalid as problem:
        return _refused(problem)


def validate_severance_step(values: dict[str, Any]) -> Result[dict[str, Any]]:
    try:
        return Ok({"years_from": _integer(values, "years_from", minimum=0),
                   "percent_per_year": _percent(values, "percent_per_year")})
    except _Invalid as problem:
        return _refused(problem)


def _bound(value: Decimal | None) -> str:
    return "∞" if value is None else str(value)


def check_complete(rule_set: RuleSet) -> list[tuple[str, str]]:
    """What stops this rule set from being confirmed, as (english, french) pairs."""
    problems: list[tuple[str, str]] = []
    by_code = {component.code: component for component in rule_set.components}
    for code in SYSTEM_COMPONENTS:
        if code not in by_code:
            problems.append((f"component {code} is missing", f"la rubrique {code} manque"))
    if BASE in by_code and UNPAID_ABSENCE in by_code:
        base, absence = by_code[BASE], by_code[UNPAID_ABSENCE]
        if (absence.taxable, absence.contributable) != (base.taxable, base.contributable):
            problems.append((
                f"{UNPAID_ABSENCE} must have the same taxable/contributable flags as {BASE}, "
                "or the absence would not reduce the base it is deducted from",
                f"{UNPAID_ABSENCE} doit avoir les mêmes indicateurs imposable/cotisable que {BASE}, "
                "sinon l'absence ne réduirait pas la base dont elle est déduite",
            ))
    bands = {rate.band_code for rate in rule_set.overtime_rates}
    for band in OVERTIME_BANDS:
        if band not in bands:
            problems.append((f"the overtime rate for band {band} is missing",
                             f"le taux d'heures supplémentaires de la tranche {band} manque"))
    tax_codes = rule_set.tax_codes()
    if not tax_codes:
        problems.append(("there is no tax bracket", "il n'y a aucune tranche d'impôt"))
    for tax_code in tax_codes:
        brackets = rule_set.brackets_for(tax_code)
        if len({bracket.annualised for bracket in brackets}) > 1:
            problems.append((f"{tax_code}: brackets mix annual and monthly amounts",
                             f"{tax_code} : les tranches mélangent montants annuels et mensuels"))
        if brackets[0].lower != 0:
            problems.append((f"{tax_code}: the first bracket starts at {brackets[0].lower}, not 0",
                             f"{tax_code} : la première tranche commence à {brackets[0].lower}, pas à 0"))
        for previous, current in zip(brackets, brackets[1:]):
            if previous.upper != current.lower:
                problems.append((f"{tax_code}: gap or overlap between {_bound(previous.upper)} and {current.lower}",
                                 f"{tax_code} : trou ou chevauchement entre {_bound(previous.upper)} et {current.lower}"))
        if brackets[-1].upper is not None:
            problems.append((f"{tax_code}: the last bracket must be open-ended",
                             f"{tax_code} : la dernière tranche doit être sans plafond"))
    for relief in (*rule_set.family_reliefs, *rule_set.professional_reliefs):
        if relief.tax_code not in tax_codes:
            problems.append((f"a relief refers to tax {relief.tax_code}, which has no bracket",
                             f"un abattement vise l'impôt {relief.tax_code}, qui n'a pas de tranche"))
    return problems
