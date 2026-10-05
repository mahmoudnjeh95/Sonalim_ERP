"""Double-entry rules the ledger never bends, with no database.

An entry is a list of lines; each line hits one postable account on one side, in whole francs
(XOF has no sub-unit), and the two sides of a postable entry are equal and both present.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Iterable, Mapping

from core.domain.result import Err, Ok, Result

ZERO = Decimal("0")
ACCOUNT_TYPES = ("asset", "liability", "equity", "income", "expense")


@dataclass(frozen=True)
class Account:
    code: str
    name: str
    class_no: int
    account_type: str
    is_postable: bool
    parent_code: str | None = None


@dataclass(frozen=True)
class EntryLine:
    account_code: str
    debit: Decimal = ZERO
    credit: Decimal = ZERO
    label: str | None = None
    partner_id: str | None = None
    employee_ref: str | None = None


@dataclass(frozen=True)
class SourceRef:
    """What an automatic entry was posted for; (module, id, kind) is unique among entries."""

    module: str
    id: str
    kind: str


def _whole(value: Decimal) -> bool:
    return value == value.to_integral_value()


def validate_lines(lines: Iterable[EntryLine], accounts: Mapping[str, Account]) -> Result[list[EntryLine]]:
    """Each line on its own: one side, a whole non-negative amount, a postable account.

    The balance is not checked here, so a draft can be saved while it is still being written.
    """
    checked = list(lines)
    for index, line in enumerate(checked, start=1):
        if line.debit < ZERO or line.credit < ZERO or not _whole(line.debit) or not _whole(line.credit):
            return Err(
                "INVALID_ENTRY_LINE",
                f"line {index}: amounts are whole, non-negative francs",
                f"ligne {index} : les montants sont des francs entiers et positifs",
            )
        if (line.debit > ZERO) == (line.credit > ZERO):
            return Err(
                "INVALID_ENTRY_LINE",
                f"line {index}: a line carries either a debit or a credit",
                f"ligne {index} : une ligne porte soit un débit, soit un crédit",
            )
        account = accounts.get(line.account_code)
        if account is None or not account.is_postable:
            return Err(
                "ACCOUNT_NOT_POSTABLE",
                f"line {index}: account {line.account_code} does not exist or is a heading that cannot be posted to",
                f"ligne {index} : le compte {line.account_code} n'existe pas ou est un compte de regroupement non imputable",
            )
    return Ok(checked)


def totals(lines: Iterable[EntryLine]) -> tuple[Decimal, Decimal]:
    debit = credit = ZERO
    for line in lines:
        debit += line.debit
        credit += line.credit
    return debit, credit


def build_entry(lines: Iterable[EntryLine], accounts: Mapping[str, Account]) -> Result[list[EntryLine]]:
    """The lines of a postable entry: every line valid, at least one debit and one credit, sides equal."""
    checked = validate_lines(lines, accounts)
    if isinstance(checked, Err):
        return checked
    debit, credit = totals(checked.value)
    has_both_sides = any(line.debit > ZERO for line in checked.value) and any(line.credit > ZERO for line in checked.value)
    if not has_both_sides or debit != credit:
        return Err(
            "ENTRY_UNBALANCED",
            f"debits ({debit}) and credits ({credit}) must be equal, with at least one line on each side",
            f"le total des débits ({debit}) doit égaler celui des crédits ({credit}), avec au moins une ligne de chaque côté",
        )
    return Ok(checked.value)


def reverse_lines(lines: Iterable[EntryLine]) -> list[EntryLine]:
    """The mirror of an entry: every debit becomes a credit of the same amount on the same account, and back."""
    return [replace(line, debit=line.credit, credit=line.debit) for line in lines]


def split_balance(net: Decimal) -> tuple[Decimal, Decimal]:
    """A signed balance (debit minus credit) as the (debit balance, credit balance) pair a trial balance prints."""
    return (net, ZERO) if net >= ZERO else (ZERO, -net)


def validate_account(account: Account, parent: Account | None) -> Result[Account]:
    """A SYSCOHADA account number: digits, its first digit is its class, it extends its parent's number."""
    code = account.code
    if not code.isdigit() or not 1 <= len(code) <= 10 or code[0] == "0":
        return Err(
            "INVALID_ACCOUNT",
            f"account number {code!r} must be 1 to 10 digits, not starting with 0",
            f"le numéro de compte {code!r} doit compter 1 à 10 chiffres, sans commencer par 0",
        )
    if account.class_no != int(code[0]):
        return Err(
            "INVALID_ACCOUNT",
            f"account {code} belongs to class {code[0]}",
            f"le compte {code} appartient à la classe {code[0]}",
        )
    if account.account_type not in ACCOUNT_TYPES:
        return Err(
            "INVALID_ACCOUNT",
            f"unknown account type {account.account_type!r}",
            f"type de compte inconnu {account.account_type!r}",
        )
    if not account.name.strip():
        return Err("INVALID_ACCOUNT", "an account needs a name", "un compte doit avoir un intitulé")
    if account.parent_code is not None:
        if parent is None:
            return Err(
                "INVALID_ACCOUNT",
                f"parent account {account.parent_code} does not exist",
                f"le compte parent {account.parent_code} n'existe pas",
            )
        if not (code.startswith(parent.code) and len(code) > len(parent.code)):
            return Err(
                "INVALID_ACCOUNT",
                f"account {code} must start with its parent's number {parent.code}",
                f"le compte {code} doit commencer par le numéro de son parent {parent.code}",
            )
    return Ok(account)
