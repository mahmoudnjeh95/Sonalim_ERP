"""Receivables rules: what is overdue, how late, which dunning level that reaches, and whether a customer
may be sold more on credit. Pure functions, no database."""
from __future__ import annotations

import datetime
from dataclasses import dataclass
from decimal import Decimal

# (key, first day late, last day late) -- "not_due" covers everything not yet late.
BUCKETS = (("not_due", None, 0), ("1_30", 1, 30), ("31_60", 31, 60), ("61_90", 61, 90), ("over_90", 91, None))

# The defaults a tenant starts with: (level, days after the due date, French name, English name, blocks orders,
# French letter, English letter).
DEFAULT_LEVELS = (
    (1, 7, "Rappel amiable", "Friendly reminder", False,
     "Sauf erreur de notre part, les factures ci-dessus restent impayées à ce jour. Nous vous remercions de bien vouloir "
     "procéder à leur règlement dans les meilleurs délais. Si votre paiement a été effectué entre-temps, merci de ne pas "
     "tenir compte de ce courrier.",
     "Unless we are mistaken, the invoices above are still unpaid. We would be grateful if you could settle them at your "
     "earliest convenience. If you have paid them in the meantime, please disregard this letter."),
    (2, 15, "Relance", "Second reminder", False,
     "Malgré notre précédent rappel, les factures ci-dessus restent impayées. Nous vous prions de régulariser votre "
     "situation sous huit jours.",
     "Despite our previous reminder, the invoices above remain unpaid. Please settle them within eight days."),
    (3, 30, "Mise en demeure", "Formal notice", False,
     "Par la présente, nous vous mettons en demeure de régler sous huit jours les sommes ci-dessus. À défaut, nous "
     "suspendrons nos livraisons et engagerons les procédures de recouvrement prévues par la loi.",
     "We hereby give you formal notice to pay the amounts above within eight days. Failing that, we will suspend deliveries "
     "and start the recovery proceedings provided for by law."),
    (4, 45, "Blocage du compte", "Account on hold", True,
     "Faute de règlement, votre compte est bloqué : aucune nouvelle commande ne sera acceptée jusqu'au paiement intégral des "
     "sommes ci-dessus.",
     "As payment has not been received, your account is on hold: no new order will be accepted until the amounts above are "
     "paid in full."),
)


@dataclass(frozen=True)
class InvoicePosition:
    remaining: Decimal       # what is still to be paid, all installments
    overdue: Decimal         # what is past its due date and unpaid
    oldest_due: datetime.date | None   # due date of the oldest unpaid installment that is late
    days_overdue: int        # 0 when nothing is late
    next_due: datetime.date | None     # the next installment not yet late


def invoice_position(*, total: Decimal, credited: Decimal, paid: Decimal, installments: list[tuple[datetime.date, Decimal]],
                     today: datetime.date) -> InvoicePosition:
    """Payments settle installments oldest first. A credit note shrinks every installment in proportion, so a
    half-credited invoice owes half of each. Under one franc counts as settled, as everywhere in finance."""
    due = max(total - credited, Decimal("0"))
    remaining = due - paid
    if remaining < 1:
        return InvoicePosition(Decimal("0"), Decimal("0"), None, 0, None)
    # Against the installments' own sum, so a schedule made before the amount changed still spreads what is due.
    scheduled = sum((amount for _, amount in installments), Decimal("0"))
    scale = due / scheduled if scheduled else Decimal("0")
    covered = paid
    overdue = Decimal("0")
    oldest_due = None
    next_due = None
    for due_on, amount in sorted(installments):
        share = amount * scale
        unpaid = max(share - covered, Decimal("0"))
        covered = max(covered - share, Decimal("0"))
        if unpaid < 1:
            continue
        if due_on < today:
            overdue += unpaid
            oldest_due = oldest_due or due_on
        elif next_due is None:
            next_due = due_on
    overdue = overdue.quantize(Decimal("1")) if overdue >= 1 else Decimal("0")
    days = (today - oldest_due).days if oldest_due and overdue else 0
    return InvoicePosition(remaining, overdue, oldest_due if overdue else None, days, next_due)


def bucket_for(days_overdue: int) -> str:
    for key, low, high in BUCKETS:
        if (low is None or days_overdue >= low) and (high is None or days_overdue <= high):
            return key
    return "over_90"


def level_reached(levels: list[dict], days_overdue: int) -> dict | None:
    """The highest dunning level whose delay a customer's oldest late invoice has passed."""
    reached = None
    for level in sorted(levels, key=lambda l: l["level"]):
        if days_overdue >= max(level["days_after_due"], 1):
            reached = level
    return reached


@dataclass(frozen=True)
class CreditCheck:
    blocking: list[tuple[str, str, str]]   # (code, English, French)
    warnings: list[tuple[str, str, str]]


def credit_check(*, credit_limit: Decimal | None, exposure: Decimal, order_amount: Decimal, max_days_overdue: int,
                 block_overdue_days: int | None, blocking_level: dict | None, warn_ratio: Decimal) -> CreditCheck:
    blocking: list[tuple[str, str, str]] = []
    warnings: list[tuple[str, str, str]] = []
    after = exposure + order_amount
    if credit_limit is not None:
        if after > credit_limit:
            blocking.append(("OVER_CREDIT_LIMIT",
                             f"this order brings the customer's exposure to {after:.0f}, above its credit limit of {credit_limit:.0f}",
                             f"cette commande porte l'encours du client à {after:.0f}, au-delà de sa limite de crédit de {credit_limit:.0f}"))
        elif after > credit_limit * warn_ratio:
            warnings.append(("NEAR_CREDIT_LIMIT",
                             f"the customer's exposure will be {after:.0f} of a {credit_limit:.0f} limit",
                             f"l'encours du client atteindra {after:.0f} pour une limite de {credit_limit:.0f}"))
    if block_overdue_days is not None and max_days_overdue > block_overdue_days:
        blocking.append(("OVERDUE_INVOICES",
                         f"the customer has an invoice {max_days_overdue} days overdue (limit {block_overdue_days})",
                         f"le client a une facture en retard de {max_days_overdue} jours (limite {block_overdue_days})"))
    if blocking_level is not None:
        blocking.append(("DUNNING_BLOCK",
                         f"the customer reached dunning level {blocking_level['level']} ({blocking_level['name_en']}), which stops new orders",
                         f"le client a atteint le niveau de relance {blocking_level['level']} ({blocking_level['name_fr']}), qui bloque les commandes"))
    return CreditCheck(blocking, warnings)
