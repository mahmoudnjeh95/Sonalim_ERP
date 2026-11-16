from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

from core.domain.result import Err, Ok, Result

KINDS = ("bank", "cash", "mobile_money")


def normalize_iban(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = re.sub(r"\s+", "", value).upper()
    return cleaned or None


def _missing(field: str, kind: str) -> Err:
    return Err(
        "ACCOUNT_FIELD_REQUIRED",
        f"{field} is required for a {kind} account",
        f"{field} est obligatoire pour un compte de type {kind}",
    )


def validate_account(kind: str, fields: dict[str, Any], format_rules: list[dict[str, str]] | None = None) -> Result[None]:
    """Kind-specific required fields, then any configured number-format rule for this kind.
    No format is hard-coded: a rule is data (`regex` per kind), absent until someone adds one."""
    if kind not in KINDS:
        return Err("INVALID_ACCOUNT_KIND", f"unknown account kind {kind}", f"type de compte inconnu {kind}")
    if not fields.get("name"):
        return _missing("name", kind)
    if not fields.get("currency"):
        return _missing("currency", kind)
    if kind == "bank":
        for required in ("branch_id", "account_number"):
            if not fields.get(required):
                return _missing(required, kind)
    if kind == "mobile_money":
        for required in ("operator", "phone"):
            if not fields.get(required):
                return _missing(required, kind)
    number = fields.get("account_number")
    if number:
        for rule in format_rules or []:
            if rule["kind"] == kind and not re.fullmatch(rule["regex"], number):
                return Err(
                    "ACCOUNT_FORMAT_INVALID",
                    rule.get("hint_en") or "account number does not match the expected format",
                    rule.get("hint_fr") or "le numéro de compte ne respecte pas le format attendu",
                )
    return Ok(None)


def apply_movement(balance: Decimal, signed_amount: Decimal, *, allow_negative: bool) -> Result[Decimal]:
    if signed_amount == 0:
        return Err("INVALID_AMOUNT", "a movement amount cannot be zero", "le montant d'un mouvement ne peut pas être nul")
    new_balance = balance + signed_amount
    if new_balance < 0 and not allow_negative:
        return Err(
            "INSUFFICIENT_BALANCE",
            f"balance {balance} is not enough for a movement of {signed_amount}",
            f"le solde {balance} est insuffisant pour un mouvement de {signed_amount}",
        )
    return Ok(new_balance)
