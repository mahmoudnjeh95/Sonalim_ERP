"""What a caller without hr.view_sensitive may not see: pay, national identifiers, bank details.

The HTTP layer runs every employee, contract and payment-method record through these before
answering, and refuses a write that sets one of these fields from a caller who could not read
it back: they would be typing blind over a value they cannot see.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping

VIEW_SENSITIVE = "hr.view_sensitive"

EMPLOYEE_FIELDS = ("national_id", "inps_no", "amo_no")
CONTRACT_FIELDS = ("base_salary",)
# A contract's components are pay too: writing them needs the right, reading them is masked below.
CONTRACT_WRITE_FIELDS = ("base_salary", "components")
PAYMENT_FIELDS = ("account_no", "mobile_number")


def mask(record: Mapping[str, object], fields: tuple[str, ...], *, visible: bool) -> dict:
    """A copy of `record` with `fields` emptied when not `visible`, flagged either way."""
    shown = dict(record)
    if not visible:
        for name in fields:
            if name in shown:
                shown[name] = None
    shown["sensitive_hidden"] = not visible
    return shown


def mask_contract(record: Mapping[str, object], *, visible: bool) -> dict:
    """Like mask(), and a hidden contract keeps its component codes but not their amounts or rates."""
    shown = mask(record, CONTRACT_FIELDS, visible=visible)
    if not visible:
        shown["components"] = [{**component, "amount": None, "rate": None} for component in record.get("components", [])]
    return shown


def written(changes: Mapping[str, object], fields: Iterable[str]) -> list[str]:
    """The sensitive fields a PATCH mentions; clearing one is a write too."""
    return [name for name in fields if name in changes]


def filled(record: Mapping[str, object], fields: Iterable[str]) -> list[str]:
    """The sensitive fields a create or a replaced list actually sets (0 is a value, '' is not)."""
    return [name for name in fields if record.get(name) not in (None, "", [])]
