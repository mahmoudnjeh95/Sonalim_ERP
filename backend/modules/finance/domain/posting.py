"""How a payroll run or an invoice becomes journal lines, with no database.

A posting rule is keyed by (source, source_kind, code); code '*' is the fallback of its kind.
A rule names a debit account, a credit account, or both. Payment and invoice rules are
self-contained — both sides and the journal — because they alone make a whole entry.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, replace
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Iterable, Mapping

from core.domain.result import Err, Ok, Result
from modules.finance.domain.ledger import ZERO, Account, EntryLine

WILDCARD = "*"
PAYROLL_LINE_KINDS = (
    "earning",
    "deduction",
    "employee_contribution",
    "employer_contribution",
    "employer_charge",
    "tax",
    "net",
)
PAYMENT_METHODS = ("bank", "mobile_money", "cash")
RULE_KINDS: dict[str, tuple[str, ...]] = {
    "payroll": PAYROLL_LINE_KINDS + ("payment",),
    "invoice": ("issued", "paid"),
    "purchase_invoice": ("validated", "vat"),
    "treasury": ("receipt_payment", "receipt_advance", "receipt_withheld", "disbursement_payment", "disbursement_advance", "disbursement_withheld", "instrument_collected", "instrument_unpaid", "instrument_rejection_fee", "account_opening"),
}
SELF_CONTAINED_KINDS = {("payroll", "payment"), ("invoice", "issued"), ("invoice", "paid"), ("purchase_invoice", "validated")}
RULE_STATUSES = ("to_confirm", "confirmed")


@dataclass(frozen=True)
class PostingRule:
    source: str
    source_kind: str
    code: str
    debit_account_code: str | None
    credit_account_code: str | None
    journal_code: str | None = None
    status: str = "to_confirm"
    id: str | None = None


@dataclass(frozen=True)
class PaymentEntry:
    method: str
    journal_code: str
    lines: list[EntryLine]


def resolve_rule(rules: Iterable[PostingRule], *, source: str, source_kind: str, code: str) -> Result[PostingRule]:
    """The rule written for this exact code, else the '*' rule of its kind."""
    fallback: PostingRule | None = None
    for rule in rules:
        if rule.source != source or rule.source_kind != source_kind:
            continue
        if rule.code == code:
            return Ok(rule)
        if rule.code == WILDCARD:
            fallback = rule
    if fallback is None:
        return Err(
            "POSTING_RULE_MISSING",
            f"no posting rule for {source} / {source_kind} / {code} and no '*' rule for {source_kind}",
            f"aucune règle d'imputation pour {source} / {source_kind} / {code}, ni de règle « * » pour {source_kind}",
        )
    return Ok(fallback)


def _complete(rule: PostingRule, *, code: str) -> Result[PostingRule]:
    if rule.debit_account_code and rule.credit_account_code and rule.journal_code:
        return Ok(rule)
    return Err(
        "POSTING_RULE_MISSING",
        f"the {rule.source} / {rule.source_kind} / {code} rule needs a debit account, a credit account and a journal",
        f"la règle {rule.source} / {rule.source_kind} / {code} doit indiquer un compte au débit, un compte au crédit et un journal",
    )


def _amount(raw: object, *, code: str) -> Result[Decimal]:
    try:
        amount = Decimal(str(raw))
    except (InvalidOperation, ValueError):
        return Err("INVALID_ENTRY_LINE", f"{code}: {raw!r} is not an amount", f"{code} : {raw!r} n'est pas un montant")
    if amount < ZERO or amount != amount.to_integral_value():
        return Err(
            "INVALID_ENTRY_LINE",
            f"{code}: {amount} is not a whole, non-negative amount of francs",
            f"{code} : {amount} n'est pas un montant entier et positif en francs",
        )
    return Ok(amount)


def payroll_run_lines(posting_lines: Iterable[Mapping], rules: Iterable[PostingRule]) -> Result[list[EntryLine]]:
    """The PAIE entry of a run: each payroll line goes to its rule's debit and/or credit account,
    amounts are summed per account and side, debits first, each side ordered by account number."""
    rules = list(rules)
    debits: dict[str, Decimal] = defaultdict(lambda: ZERO)
    credits: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for line in posting_lines:
        code = str(line["code"])
        amount = _amount(line["amount"], code=code)
        if isinstance(amount, Err):
            return amount
        if amount.value == ZERO:
            continue
        resolved = resolve_rule(rules, source="payroll", source_kind=str(line["source_kind"]), code=code)
        if isinstance(resolved, Err):
            return resolved
        rule = resolved.value
        if rule.debit_account_code:
            debits[rule.debit_account_code] += amount.value
        if rule.credit_account_code:
            credits[rule.credit_account_code] += amount.value
    return Ok(
        [EntryLine(account, debit=total) for account, total in sorted(debits.items())]
        + [EntryLine(account, credit=total) for account, total in sorted(credits.items())]
    )


def payroll_payment_entries(payment_lines: Iterable[Mapping], rules: Iterable[PostingRule]) -> Result[list[PaymentEntry]]:
    """One entry per payment method used: net pay (debit side of the rule) against the method's
    bank / e-money / cash account, in the journal the rule names."""
    rules = list(rules)
    per_method: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for line in payment_lines:
        method = str(line["method"])
        if method not in PAYMENT_METHODS:
            return Err(
                "INVALID_ENTRY_LINE",
                f"unknown payment method {method!r}",
                f"mode de paiement inconnu {method!r}",
            )
        amount = _amount(line["amount"], code=method)
        if isinstance(amount, Err):
            return amount
        per_method[method] += amount.value
    entries: list[PaymentEntry] = []
    for method in PAYMENT_METHODS:
        total = per_method.get(method, ZERO)
        if total == ZERO:
            continue
        resolved = resolve_rule(rules, source="payroll", source_kind="payment", code=method)
        if isinstance(resolved, Err):
            return resolved
        complete = _complete(resolved.value, code=method)
        if isinstance(complete, Err):
            return complete
        rule = complete.value
        entries.append(
            PaymentEntry(
                method=method,
                journal_code=str(rule.journal_code),
                lines=[
                    EntryLine(str(rule.debit_account_code), debit=total),
                    EntryLine(str(rule.credit_account_code), credit=total),
                ],
            )
        )
    return Ok(entries)


def to_xof(raw: object, *, currency: str) -> Result[Decimal]:
    """An invoice amount in whole francs. Only XOF is posted; rounding is half up."""
    if currency != "XOF":
        return Err(
            "CURRENCY_NOT_XOF",
            f"only XOF amounts are posted to the ledger, not {currency}",
            f"seuls les montants en XOF (F CFA) sont comptabilisés, pas {currency}",
        )
    try:
        amount = Decimal(str(raw)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        return Err("INVALID_ENTRY_LINE", f"{raw!r} is not an amount", f"{raw!r} n'est pas un montant")
    if amount <= ZERO:
        return Err(
            "INVALID_ENTRY_LINE",
            "an invoice amount must be positive",
            "le montant d'une facture doit être positif",
        )
    return Ok(amount)


def invoice_entry(
    kind: str, *, amount: Decimal, partner_id: str, label: str, rules: Iterable[PostingRule], mirror: bool = False
) -> Result[tuple[str, list[EntryLine]]]:
    """The entry of an issued invoice (the customer side is the debit) or of its payment (the
    customer side is the credit). The partner id rides on the customer line only. `mirror` swaps the
    sides of the issued rule: a credit note takes back from the customer what the invoice charged."""
    resolved = resolve_rule(rules, source="invoice", source_kind=kind, code=WILDCARD)
    if isinstance(resolved, Err):
        return resolved
    complete = _complete(resolved.value, code=WILDCARD)
    if isinstance(complete, Err):
        return complete
    rule = complete.value
    customer_on_debit = kind == "issued"
    lines = [
        EntryLine(str(rule.debit_account_code), debit=amount, label=label, partner_id=partner_id if customer_on_debit else None),
        EntryLine(str(rule.credit_account_code), credit=amount, label=label, partner_id=None if customer_on_debit else partner_id),
    ]
    if mirror:
        lines = [replace(line, debit=line.credit, credit=line.debit) for line in lines]
    return Ok((str(rule.journal_code), lines))


def _split_whole(total: Decimal, parts: list[tuple[str, Decimal]]) -> list[tuple[str, Decimal]]:
    """Whole francs per account summing exactly to `total`: each part rounded, the rounding gap put on the
    largest one."""
    grouped: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for account, value in parts:
        grouped[account] += value
    rounded = {account: value.quantize(Decimal("1"), rounding=ROUND_HALF_UP) for account, value in grouped.items()}
    gap = total - sum(rounded.values(), ZERO)
    if gap and rounded:
        largest = max(rounded, key=lambda account: rounded[account])
        rounded[largest] += gap
    return [(account, value) for account, value in rounded.items() if value]


def purchase_invoice_entry(
    *, amount: Decimal, partner_id: str, label: str, rules: Iterable[PostingRule], vat: Decimal = ZERO,
    lines: Iterable[tuple[str | None, Decimal]] = (), mirror: bool = False,
) -> Result[tuple[str, list[EntryLine]]]:
    """A validated purchase invoice: the purchases excluding tax on the debit, the deductible VAT on the
    debit, the supplier on the credit for the total including tax (`amount`), with the partner id.

    `lines` are (purchase account or None, value excluding tax): a line whose product names its own purchase
    account posts there, the others to the rule's account. Without lines everything but the VAT goes to the
    rule's account. `mirror` swaps the sides, for a credit note."""
    rules = list(rules)
    resolved = resolve_rule(rules, source="purchase_invoice", source_kind="validated", code=WILDCARD)
    if isinstance(resolved, Err):
        return resolved
    complete = _complete(resolved.value, code=WILDCARD)
    if isinstance(complete, Err):
        return complete
    rule = complete.value
    vat_account: str | None = None
    if vat:
        vat_rule = resolve_rule(rules, source="purchase_invoice", source_kind="vat", code=WILDCARD)
        if isinstance(vat_rule, Err):
            return vat_rule
        if not vat_rule.value.debit_account_code:
            return Err(
                "POSTING_RULE_MISSING",
                "the purchase_invoice / vat / * rule needs the deductible VAT account on the debit",
                "la règle purchase_invoice / vat / * doit indiquer le compte de TVA déductible au débit",
            )
        vat_account = str(vat_rule.value.debit_account_code)
    excl = amount - vat
    parts = [(account or str(rule.debit_account_code), value) for account, value in lines] or [(str(rule.debit_account_code), excl)]
    purchases = _split_whole(excl, parts)

    def side(account: str, value: Decimal, *, debit: bool, partner: str | None = None) -> EntryLine:
        if debit != mirror:
            return EntryLine(account, debit=value, label=label, partner_id=partner)
        return EntryLine(account, credit=value, label=label, partner_id=partner)

    entry = [side(account, value, debit=True) for account, value in purchases]
    if vat_account:
        entry.append(side(vat_account, vat, debit=True))
    entry.append(side(str(rule.credit_account_code), amount, debit=False, partner=partner_id))
    return Ok((str(rule.journal_code), entry))


def validate_rule(rule: PostingRule, accounts: Mapping[str, Account], journal_codes: set[str]) -> Result[PostingRule]:
    kinds = RULE_KINDS.get(rule.source)
    if kinds is None:
        return Err(
            "INVALID_POSTING_RULE",
            f"unknown source {rule.source!r}; use one of {', '.join(RULE_KINDS)}",
            f"source inconnue {rule.source!r} ; utilisez {', '.join(RULE_KINDS)}",
        )
    if rule.source_kind not in kinds:
        return Err(
            "INVALID_POSTING_RULE",
            f"{rule.source} has no kind {rule.source_kind!r}; use one of {', '.join(kinds)}",
            f"{rule.source} n'a pas de type {rule.source_kind!r} ; utilisez {', '.join(kinds)}",
        )
    code = rule.code.strip()
    if not code:
        return Err(
            "INVALID_POSTING_RULE",
            "a rule needs a code, or '*' for every code of its kind",
            "une règle doit avoir un code, ou « * » pour tous les codes de son type",
        )
    if (rule.source, rule.source_kind) == ("payroll", "payment") and code not in PAYMENT_METHODS + (WILDCARD,):
        return Err(
            "INVALID_POSTING_RULE",
            f"a payment rule's code is a payment method: {', '.join(PAYMENT_METHODS)} or '*'",
            f"le code d'une règle de paiement est un mode de paiement : {', '.join(PAYMENT_METHODS)} ou « * »",
        )
    if rule.source == "treasury":
        from modules.finance.domain.treasury_posting import valid_rule_code

        if not valid_rule_code(rule.source_kind, code):
            return Err(
                "INVALID_POSTING_RULE",
                f"a {rule.source_kind} rule's code is a payment method (or in/out for instruments), or '*'",
                f"le code d'une règle {rule.source_kind} est un mode de paiement (ou in/out pour les effets), ou « * »",
            )
    if rule.source in ("invoice", "purchase_invoice") and code != WILDCARD:
        return Err(
            "INVALID_POSTING_RULE",
            "invoice rules use the code '*'",
            "les règles de facture utilisent le code « * »",
        )
    # A collection rule may name only its journal: both sides come from elsewhere (the slip's account and
    # the payment rule's holding account).
    journal_only = (rule.source, rule.source_kind) == ("treasury", "instrument_collected")
    if not rule.debit_account_code and not rule.credit_account_code and not journal_only:
        return Err(
            "INVALID_POSTING_RULE",
            "a rule posts to at least one account",
            "une règle impute au moins un compte",
        )
    for account_code in (rule.debit_account_code, rule.credit_account_code):
        if account_code:
            account = accounts.get(account_code)
            if account is None or not account.is_postable:
                return Err(
                    "ACCOUNT_NOT_POSTABLE",
                    f"account {account_code} does not exist or cannot be posted to",
                    f"le compte {account_code} n'existe pas ou n'est pas imputable",
                )
    if rule.journal_code and rule.journal_code not in journal_codes:
        return Err(
            "INVALID_POSTING_RULE",
            f"journal {rule.journal_code} does not exist",
            f"le journal {rule.journal_code} n'existe pas",
        )
    if (rule.source, rule.source_kind) in SELF_CONTAINED_KINDS:
        complete = _complete(rule, code=code)
        if isinstance(complete, Err):
            return Err("INVALID_POSTING_RULE", complete.message, complete.message_fr)
    return Ok(replace(rule, code=code))
