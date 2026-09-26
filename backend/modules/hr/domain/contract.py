"""Employment contracts: the terms payroll pays from, and the rule that a person has at most
one signed contract on any given day. Pure rules, no database."""
from __future__ import annotations

import datetime
import re
from collections.abc import Iterable
from dataclasses import dataclass, fields, replace
from decimal import Decimal

from core.domain.result import Err, Ok, Result
from modules.hr.domain.employee import END_REASONS
from modules.hr.domain.money import invalid_amount, is_whole_amount

CONTRACT_TYPES = ("cdi", "cdd", "apprentice", "daily", "intern")
PAY_FREQUENCIES = ("monthly", "daily")
CONTRACT_STATUSES = ("draft", "active", "expired", "terminated")
HOURS_IN_A_WEEK = Decimal("168")
_COMPONENT_CODE = re.compile(r"^[A-Z][A-Z0-9_]{1,31}$")


@dataclass(frozen=True)
class ContractComponent:
    component_code: str
    amount: Decimal | None = None
    rate: Decimal | None = None


@dataclass(frozen=True)
class ContractTerms:
    employee_id: str
    contract_type: str
    start_date: datetime.date
    base_salary: Decimal
    end_date: datetime.date | None = None
    trial_end_date: datetime.date | None = None
    weekly_hours: Decimal = Decimal("40")
    pay_frequency: str = "monthly"
    position_id: str | None = None
    grade_id: str | None = None
    status: str = "active"
    amends_contract_id: str | None = None
    end_reason: str | None = None
    components: tuple[ContractComponent, ...] = ()


# Stored columns of hr.contracts in ContractTerms order; components live in their own table.
COLUMNS = tuple(field.name for field in fields(ContractTerms) if field.name != "components")


@dataclass(frozen=True)
class ContractPeriod:
    id: str
    start_date: datetime.date
    end_date: datetime.date | None
    status: str


def validate_components(components: Iterable[ContractComponent]) -> Result[tuple[ContractComponent, ...]]:
    cleaned: list[ContractComponent] = []
    for component in components:
        code = (component.component_code or "").strip().upper()
        if not _COMPONENT_CODE.match(code):
            return Err(
                "INVALID_COMPONENT",
                f"'{component.component_code}' is not a component code (capitals, digits, underscores)",
                f"« {component.component_code} » n'est pas un code d'élément (majuscules, chiffres, tirets bas)",
            )
        if (component.amount is None) == (component.rate is None):
            return Err("INVALID_COMPONENT", f"{code}: give either an amount or a rate", f"{code} : indiquez soit un montant, soit un taux")
        if component.amount is not None and not is_whole_amount(component.amount):
            return invalid_amount(f"the amount of {code}", f"le montant de {code}")
        if component.rate is not None and (not component.rate.is_finite() or component.rate < 0):
            return Err("INVALID_COMPONENT", f"{code}: a rate cannot be negative", f"{code} : un taux ne peut pas être négatif")
        cleaned.append(ContractComponent(component_code=code, amount=component.amount, rate=component.rate))
    codes = [component.component_code for component in cleaned]
    if len(codes) != len(set(codes)):
        return Err("INVALID_COMPONENT", "an allowance appears twice on the contract", "une indemnité figure deux fois sur le contrat")
    return Ok(tuple(cleaned))


def validate_terms(terms: ContractTerms) -> Result[ContractTerms]:
    if terms.contract_type not in CONTRACT_TYPES:
        return Err(
            "INVALID_CONTRACT_TYPE",
            f"contract type must be one of {', '.join(CONTRACT_TYPES)}",
            f"le type de contrat doit être l'un de {', '.join(CONTRACT_TYPES)}",
        )
    if terms.pay_frequency not in PAY_FREQUENCIES:
        return Err("INVALID_CONTRACT", "pay frequency is monthly or daily", "la périodicité de paie est mensuelle ou journalière")
    if terms.status not in CONTRACT_STATUSES:
        return Err(
            "INVALID_STATUS",
            f"status must be one of {', '.join(CONTRACT_STATUSES)}",
            f"le statut doit être l'un de {', '.join(CONTRACT_STATUSES)}",
        )
    if terms.start_date is None:
        return Err("INVALID_DATES", "a contract needs a start date", "un contrat demande une date de début")
    if not is_whole_amount(terms.base_salary):
        return invalid_amount("the base salary", "le salaire de base")
    if terms.weekly_hours is None or not Decimal("0") < terms.weekly_hours <= HOURS_IN_A_WEEK:
        return Err("INVALID_CONTRACT", "weekly hours are above 0 and at most 168", "les heures hebdomadaires sont supérieures à 0 et au plus 168")
    if terms.end_date is not None and terms.end_date < terms.start_date:
        return Err("INVALID_DATES", "a contract cannot end before it starts", "un contrat ne peut pas finir avant de commencer")
    if terms.trial_end_date is not None and (
        terms.trial_end_date < terms.start_date or (terms.end_date is not None and terms.trial_end_date > terms.end_date)
    ):
        return Err("INVALID_DATES", "the trial period ends within the contract", "la période d'essai se termine pendant le contrat")
    if terms.end_reason is not None and terms.end_reason not in END_REASONS:
        return Err("INVALID_END_REASON", "unknown end reason", "motif de fin inconnu")
    if terms.end_reason is not None and terms.end_date is None:
        return Err("INVALID_END_REASON", "an end reason needs an end date", "un motif de fin demande une date de fin")
    components = validate_components(terms.components)
    if isinstance(components, Err):
        return components
    return Ok(replace(terms, components=components.value))


def overlapping(candidate: ContractPeriod, others: Iterable[ContractPeriod]) -> ContractPeriod | None:
    """The earliest signed contract of the same person sharing a day with `candidate`.
    A draft is not signed: it never conflicts, and nothing conflicts with it."""
    if candidate.status == "draft":
        return None
    clashes = [
        other
        for other in others
        if other.id != candidate.id
        and other.status != "draft"
        and other.start_date <= (candidate.end_date or datetime.date.max)
        and candidate.start_date <= (other.end_date or datetime.date.max)
    ]
    return min(clashes, key=lambda other: other.start_date, default=None)


def overlap_refusal(other: ContractPeriod) -> Err:
    start = other.start_date.isoformat()
    if other.end_date is None:
        span_en, span_fr = f"from {start}, open-ended", f"depuis le {start}, sans date de fin"
    else:
        end = other.end_date.isoformat()
        span_en, span_fr = f"from {start} to {end}", f"du {start} au {end}"
    return Err("CONTRACT_OVERLAP", f"the employee already has a signed contract {span_en}", f"l'employé a déjà un contrat signé {span_fr}")


def end_status(end_reason: str) -> str:
    """A contract that ran to its term, or that an amendment replaced, expired; any other end is a termination."""
    return "expired" if end_reason in ("term_reached", "amended") else "terminated"
