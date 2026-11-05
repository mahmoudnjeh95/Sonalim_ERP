"""How treasury activity becomes journal lines, with no database and no account numbers of its own.

Every account number comes from a `finance.posting_rules` row (source 'treasury') or from the
`ledger_account_code` of the treasury account that moved. Nothing is hard-coded: the accountant
has not confirmed the accounts, and a missing rule or code refuses the posting.

Rule shapes (code = payment method, direction for instrument kinds, or '*' as the fallback):

  receipt_payment       credit = the customer account (411); debit = holding account, used only for a
                        cheque or draft that sits in no treasury account yet (effets à recevoir)
  disbursement_payment  debit  = the supplier account (401); credit = holding account for an issued
                        cheque or draft (effets à payer)
  receipt_advance /     self-contained: the part of a document tied to no invoice moves from the
  disbursement_advance  customer/supplier account to the advance account
  receipt_withheld /    self-contained: what the partner kept back settles the invoice without moving money.
  disbursement_withheld in: debit = the withheld-tax receivable, credit = the customer account;
                        out: debit = the supplier account, credit = the withheld-tax payable
  instrument_collected  in:  debit = the slip's account (its ledger code), credit = holding account
                        out: debit = holding account, credit = the slip's account
  instrument_unpaid     self-contained: in: debit customer, credit holding; out: debit holding, credit supplier
  instrument_rejection_fee  debit = the bank-charges account; the credit is the ledger code of the
                        treasury account the bank charged, so any credit on the rule is ignored

Every rule also names the journal. The money side of a payment is the ledger code of the treasury
account it moved, so each mobile-money operator keeps its own 5xx account.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable, Mapping

from core.domain.result import Err, Ok, Result
from modules.finance.domain.ledger import ZERO, EntryLine
from modules.finance.domain.posting import WILDCARD, PostingRule, _amount, resolve_rule

DIRECTION_NOUN = {"in": "receipt", "out": "disbursement"}
METHODS = ("cash", "transfer", "mobile_money", "cheque", "draft")
INSTRUMENT_KINDS = ("instrument_collected", "instrument_unpaid", "instrument_rejection_fee")
RULE_KINDS = ("receipt_payment", "receipt_advance", "receipt_withheld", "disbursement_payment", "disbursement_advance",
              "disbursement_withheld") + INSTRUMENT_KINDS


@dataclass(frozen=True)
class TreasuryEntry:
    suffix: str  # appended to the failure kind to make the entry's source kind unique, e.g. 'cash'
    journal_code: str
    lines: list[EntryLine]


def valid_rule_code(source_kind: str, code: str) -> bool:
    if code == WILDCARD:
        return True
    if source_kind in INSTRUMENT_KINDS:
        return code in ("in", "out")
    return code in METHODS


def _incomplete(rule: PostingRule, what: str) -> Err:
    return Err(
        "POSTING_RULE_MISSING",
        f"the {rule.source_kind} / {rule.code} rule needs {what}",
        f"la règle {rule.source_kind} / {rule.code} doit indiquer {what}",
    )


def _no_ledger_code(what: str) -> Err:
    return Err(
        "LEDGER_ACCOUNT_MISSING",
        f"{what} has no ledger account code; set one on the treasury account",
        f"{what} n'a pas de compte comptable ; renseignez-le sur le compte de trésorerie",
    )


def _not_xof(currency: str) -> Err:
    return Err(
        "CURRENCY_NOT_XOF",
        f"only XOF amounts are posted to the ledger, not {currency}",
        f"seuls les montants en XOF (F CFA) sont comptabilisés, pas {currency}",
    )


def document_entries(
    direction: str,
    *,
    payments: Iterable[Mapping],
    unallocated: object,
    partner_id: str,
    currency: str,
    label: str,
    rules: Iterable[PostingRule],
    withheld: object = 0,
) -> Result[list[TreasuryEntry]]:
    """One entry per payment method of a receipt or a disbursement, then one each for its advance and
    withheld parts."""
    if currency != "XOF":
        return _not_xof(currency)
    rules = list(rules)
    noun = DIRECTION_NOUN[direction]
    per_method: dict[str, list[Mapping]] = defaultdict(list)
    for payment in payments:
        per_method[str(payment["method"])].append(payment)
    entries: list[TreasuryEntry] = []
    for method in METHODS:
        group = per_method.get(method)
        if not group:
            continue
        resolved = resolve_rule(rules, source="treasury", source_kind=f"{noun}_payment", code=method)
        if isinstance(resolved, Err):
            return resolved
        rule = resolved.value
        counterparty = rule.credit_account_code if direction == "in" else rule.debit_account_code
        if not counterparty or not rule.journal_code:
            return _incomplete(rule, "the customer/supplier account and a journal")
        money: dict[str, Decimal] = defaultdict(lambda: ZERO)
        for payment in group:
            amount = _amount(payment["amount"], code=method)
            if isinstance(amount, Err):
                return amount
            if payment.get("account_id"):
                account = payment.get("ledger_account_code")
                if not account:
                    return _no_ledger_code(f"the treasury account of a {method} payment")
            else:
                account = rule.debit_account_code if direction == "in" else rule.credit_account_code
                if not account:
                    return _incomplete(rule, "a holding account for instruments not yet in an account")
            money[str(account)] += amount.value
        total = sum(money.values(), ZERO)
        if total == ZERO:
            continue
        if direction == "in":
            lines = [EntryLine(a, debit=v, label=label) for a, v in sorted(money.items())]
            lines.append(EntryLine(str(counterparty), credit=total, label=label, partner_id=partner_id))
        else:
            lines = [EntryLine(str(counterparty), debit=total, label=label, partner_id=partner_id)]
            lines += [EntryLine(a, credit=v, label=label) for a, v in sorted(money.items())]
        entries.append(TreasuryEntry(method, str(rule.journal_code), lines))
    advance = _amount(unallocated, code="advance")
    if isinstance(advance, Err):
        return advance
    if advance.value > ZERO:
        resolved = resolve_rule(rules, source="treasury", source_kind=f"{noun}_advance", code=WILDCARD)
        if isinstance(resolved, Err):
            return resolved
        rule = resolved.value
        if not (rule.debit_account_code and rule.credit_account_code and rule.journal_code):
            return _incomplete(rule, "a debit account, a credit account and a journal")
        on_debit = direction == "in"
        entries.append(
            TreasuryEntry(
                "advance",
                str(rule.journal_code),
                [
                    EntryLine(rule.debit_account_code, debit=advance.value, label=label, partner_id=partner_id if on_debit else None),
                    EntryLine(rule.credit_account_code, credit=advance.value, label=label, partner_id=None if on_debit else partner_id),
                ],
            )
        )
    kept = _amount(withheld, code="withheld")
    if isinstance(kept, Err):
        return kept
    if kept.value > ZERO:
        resolved = resolve_rule(rules, source="treasury", source_kind=f"{noun}_withheld", code=WILDCARD)
        if isinstance(resolved, Err):
            return resolved
        rule = resolved.value
        if not (rule.debit_account_code and rule.credit_account_code and rule.journal_code):
            return _incomplete(rule, "a debit account, a credit account and a journal")
        customer_side = direction == "in"
        entries.append(
            TreasuryEntry(
                "withheld",
                str(rule.journal_code),
                [
                    EntryLine(rule.debit_account_code, debit=kept.value, label=label, partner_id=None if customer_side else partner_id),
                    EntryLine(rule.credit_account_code, credit=kept.value, label=label, partner_id=partner_id if customer_side else None),
                ],
            )
        )
    return Ok(entries)


def instrument_entry(
    kind: str,
    *,
    direction: str,
    amount: object,
    currency: str,
    partner_id: str | None,
    account_ledger_code: str | None,
    label: str,
    rules: Iterable[PostingRule],
) -> Result[TreasuryEntry]:
    """`kind` is 'instrument_collected' or 'instrument_unpaid'."""
    if currency != "XOF":
        return _not_xof(currency)
    value = _amount(amount, code=kind)
    if isinstance(value, Err):
        return value
    resolved = resolve_rule(list(rules), source="treasury", source_kind=kind, code=direction)
    if isinstance(resolved, Err):
        return resolved
    rule = resolved.value
    if not rule.journal_code:
        return _incomplete(rule, "a journal")
    if kind == "instrument_collected":
        holding = rule.credit_account_code if direction == "in" else rule.debit_account_code
        if not holding:
            return _incomplete(rule, "the holding account")
        if not account_ledger_code:
            return _no_ledger_code("the account the instrument was credited to or debited from")
        money_side = account_ledger_code
        lines = (
            [EntryLine(money_side, debit=value.value, label=label), EntryLine(holding, credit=value.value, label=label)]
            if direction == "in"
            else [EntryLine(holding, debit=value.value, label=label), EntryLine(money_side, credit=value.value, label=label)]
        )
        return Ok(TreasuryEntry("", str(rule.journal_code), lines))
    if not (rule.debit_account_code and rule.credit_account_code):
        return _incomplete(rule, "a debit and a credit account")
    on_debit = direction == "in"
    return Ok(
        TreasuryEntry(
            "",
            str(rule.journal_code),
            [
                EntryLine(rule.debit_account_code, debit=value.value, label=label, partner_id=partner_id if on_debit else None),
                EntryLine(rule.credit_account_code, credit=value.value, label=label, partner_id=None if on_debit else partner_id),
            ],
        )
    )


def rejection_fee_entry(
    *,
    direction: str,
    amount: object,
    currency: str,
    account_ledger_code: str | None,
    label: str,
    rules: Iterable[PostingRule],
) -> Result[TreasuryEntry]:
    """What the bank charged for rejecting a cheque: an expense against the account it came out of."""
    if currency != "XOF":
        return _not_xof(currency)
    value = _amount(amount, code="instrument_rejection_fee")
    if isinstance(value, Err):
        return value
    resolved = resolve_rule(list(rules), source="treasury", source_kind="instrument_rejection_fee", code=direction)
    if isinstance(resolved, Err):
        return resolved
    rule = resolved.value
    if not rule.debit_account_code or not rule.journal_code:
        return _incomplete(rule, "the bank-charges account and a journal")
    if not account_ledger_code:
        return _no_ledger_code("the account charged for the rejection")
    return Ok(
        TreasuryEntry(
            "",
            str(rule.journal_code),
            [
                EntryLine(rule.debit_account_code, debit=value.value, label=label),
                EntryLine(account_ledger_code, credit=value.value, label=label),
            ],
        )
    )
