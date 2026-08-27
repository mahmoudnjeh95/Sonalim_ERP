from __future__ import annotations

from dataclasses import dataclass

from core.domain.result import Err, Ok, Result

OPPORTUNITY_VALID_TRANSITIONS = {
    "prospecting": {"qualification", "lost"},
    "qualification": {"proposal", "lost"},
    "proposal": {"negotiation", "lost"},
    "negotiation": {"won", "lost"},
    "won": set(),
    "lost": set(),
}


@dataclass(frozen=True)
class Opportunity:
    id: str
    partner_id: str
    name: str
    stage: str
    amount: float
    expected_close_date: str | None = None


def validate_amount(amount: float) -> Result[None]:
    if amount < 0:
        return Err("INVALID_AMOUNT", "amount cannot be negative")
    return Ok(None)


def transition_opportunity(opportunity: Opportunity, new_stage: str) -> Result[Opportunity]:
    if new_stage not in OPPORTUNITY_VALID_TRANSITIONS.get(opportunity.stage, set()):
        return Err("INVALID_TRANSITION", f"cannot move opportunity from {opportunity.stage} to {new_stage}")
    return Ok(
        Opportunity(
            id=opportunity.id,
            partner_id=opportunity.partner_id,
            name=opportunity.name,
            stage=new_stage,
            amount=opportunity.amount,
            expected_close_date=opportunity.expected_close_date,
        )
    )
