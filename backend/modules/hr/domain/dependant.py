"""The people an employee supports. ITS family relief (phase 3) counts the tax dependants valid
on the last day of the pay period. Pure rules, no database."""
from __future__ import annotations

import datetime
from collections.abc import Iterable
from dataclasses import dataclass

from core.domain.result import Err, Ok, Result

DEPENDANT_KINDS = ("spouse", "child")


@dataclass(frozen=True)
class Dependant:
    kind: str
    name: str
    valid_from: datetime.date
    birth_date: datetime.date | None = None
    dependent_for_tax: bool = False
    valid_to: datetime.date | None = None


def validate_dependant(dependant: Dependant) -> Result[Dependant]:
    if dependant.kind not in DEPENDANT_KINDS:
        return Err("INVALID_CHOICE", "a dependant is a spouse or a child", "une personne à charge est un conjoint ou un enfant")
    name = (dependant.name or "").strip()
    if not name or dependant.valid_from is None:
        return Err("INVALID_DEPENDANT", "a dependant needs a name and a start date", "une personne à charge demande un nom et une date de début")
    if dependant.valid_to is not None and dependant.valid_to < dependant.valid_from:
        return Err("INVALID_DATES", "the validity cannot end before it starts", "la validité ne peut pas finir avant de commencer")
    if dependant.birth_date is not None and dependant.birth_date > dependant.valid_from:
        return Err("INVALID_DATES", "a dependant cannot count before being born", "une personne ne peut pas être à charge avant sa naissance")
    return Ok(
        Dependant(
            kind=dependant.kind,
            name=name,
            valid_from=dependant.valid_from,
            birth_date=dependant.birth_date,
            dependent_for_tax=dependant.dependent_for_tax,
            valid_to=dependant.valid_to,
        )
    )


def is_tax_dependant_on(dependant: Dependant, day: datetime.date) -> bool:
    return dependant.dependent_for_tax and dependant.valid_from <= day and (dependant.valid_to is None or dependant.valid_to >= day)


def count_tax_dependants(dependants: Iterable[Dependant], day: datetime.date) -> int:
    return sum(1 for dependant in dependants if is_tax_dependant_on(dependant, day))
