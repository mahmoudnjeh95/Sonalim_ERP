"""Comparing what was actually poured against the OF's recipe.

The plant's rule, settled with the user: **warn, never block.** A recipe is what
the formula says should go into the mix; the shift pours what the silo actually
had. When the two disagree the supervisor needs to see it, not be stopped by it —
a line that has already run cannot be un-run by refusing its report.

So every function here returns findings. Nothing returns an Err, and nothing a
caller does with these should prevent a report being filed or validated.
"""
from __future__ import annotations

from dataclasses import dataclass

# A component's share may drift this far from its limit before it is worth
# saying anything. Scales round, shifts pour by eye, and a warning that fires on
# every single report is a warning nobody reads.
TOLERANCE_PERCENTAGE_POINTS = 0.05


@dataclass(frozen=True)
class PouredComponent:
    """One product's total contribution to an OF's mix."""

    product_id: str
    quantity: float


@dataclass(frozen=True)
class RecipeLimit:
    component_product_id: str
    min_percentage: float
    max_percentage: float
    is_hard_limit: bool


@dataclass(frozen=True)
class RecipeFinding:
    """One thing worth telling the supervisor about the mix.

    `severity` is "hard" or "soft", taken from the recipe line. It says how far
    outside the formula the plant has gone — not whether anything is blocked,
    because nothing here blocks.
    """

    code: str
    component_product_id: str | None
    severity: str
    actual_percentage: float | None
    min_percentage: float | None
    max_percentage: float | None

    def as_dict(self) -> dict:
        return {
            "code": self.code,
            "component_product_id": self.component_product_id,
            "severity": self.severity,
            "actual_percentage": self.actual_percentage,
            "min_percentage": self.min_percentage,
            "max_percentage": self.max_percentage,
        }


def check_recipe_limits(
    poured: list[PouredComponent], limits: list[RecipeLimit]
) -> list[RecipeFinding]:
    """What the mix says about the formula it was supposed to follow.

    Four things can be worth reporting:

    * a component below its minimum share, or above its maximum;
    * a component the recipe names that was never poured at all;
    * a product poured that the recipe does not name.

    A mix with nothing in it produces no findings rather than six: an OF whose
    first shift has not reported yet has not violated anything.
    """
    totals: dict[str, float] = {}
    for component in poured:
        totals[component.product_id] = totals.get(component.product_id, 0.0) + component.quantity

    # A component that has been reversed more than it was poured leaves a
    # negative running total. There is no denominator that makes the remaining
    # shares meaningful — include it and the mix shrinks, drop it and every other
    # component's share inflates — so say the one true thing and stop. A wrong
    # percentage presented confidently is worse than none.
    negatives = sorted(product_id for product_id, quantity in totals.items() if quantity < 0)
    if negatives:
        return [
            RecipeFinding(
                code="NEGATIVE_QUANTITY",
                component_product_id=product_id,
                severity="soft",
                actual_percentage=None,
                min_percentage=None,
                max_percentage=None,
            )
            for product_id in negatives
        ]

    mix_total = sum(totals.values())
    if mix_total <= 0:
        return []

    findings: list[RecipeFinding] = []
    named_by_recipe = {limit.component_product_id for limit in limits}

    for limit in limits:
        quantity = totals.get(limit.component_product_id, 0.0)
        share = quantity / mix_total * 100

        if quantity <= 0:
            findings.append(
                RecipeFinding(
                    code="COMPONENT_NOT_POURED",
                    component_product_id=limit.component_product_id,
                    severity="hard" if limit.is_hard_limit else "soft",
                    actual_percentage=0.0,
                    min_percentage=limit.min_percentage,
                    max_percentage=limit.max_percentage,
                )
            )
            continue

        if share < limit.min_percentage - TOLERANCE_PERCENTAGE_POINTS:
            findings.append(
                RecipeFinding(
                    code="BELOW_MINIMUM",
                    component_product_id=limit.component_product_id,
                    severity="hard" if limit.is_hard_limit else "soft",
                    actual_percentage=share,
                    min_percentage=limit.min_percentage,
                    max_percentage=limit.max_percentage,
                )
            )
        elif share > limit.max_percentage + TOLERANCE_PERCENTAGE_POINTS:
            findings.append(
                RecipeFinding(
                    code="ABOVE_MAXIMUM",
                    component_product_id=limit.component_product_id,
                    severity="hard" if limit.is_hard_limit else "soft",
                    actual_percentage=share,
                    min_percentage=limit.min_percentage,
                    max_percentage=limit.max_percentage,
                )
            )

    for product_id, quantity in totals.items():
        if quantity > 0 and product_id not in named_by_recipe:
            findings.append(
                RecipeFinding(
                    code="NOT_IN_RECIPE",
                    component_product_id=product_id,
                    # The recipe says nothing about this product, so there is no
                    # limit to call hard. It is always a soft observation.
                    severity="soft",
                    actual_percentage=quantity / mix_total * 100,
                    min_percentage=None,
                    max_percentage=None,
                )
            )

    return findings
