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

DEFAULT_PROBABILITY_BY_STAGE = {
    "prospecting": 10,
    "qualification": 30,
    "proposal": 60,
    "negotiation": 80,
    "won": 100,
    "lost": 0,
}


@dataclass(frozen=True)
class Opportunity:
    id: str
    partner_id: str
    name: str
    stage: str
    amount: float
    expected_close_date: str | None = None
    probability: int = 10
    owner_id: str | None = None
    priority: str = "medium"
    lost_reason: str | None = None
    created_at: str | None = None
    sales_order_id: str | None = None


@dataclass(frozen=True)
class WonLine:
    product_id: str
    quantity: float


def validate_amount(amount: float) -> Result[None]:
    if amount < 0:
        return Err("INVALID_AMOUNT", "amount cannot be negative")
    return Ok(None)


def validate_lost_reason(reason: str | None) -> Result[None]:
    if reason is None or not reason.strip():
        return Err("EMPTY_REASON", "a reason is required to mark an opportunity lost")
    return Ok(None)


def validate_won_lines(lines: list[WonLine] | None) -> Result[None]:
    if not lines:
        return Err("EMPTY_LINES", "at least one product line is required to mark an opportunity won")
    for line in lines:
        if line.quantity <= 0:
            return Err("INVALID_QUANTITY", "quantity must be greater than zero")
    return Ok(None)


def transition_opportunity(
    opportunity: Opportunity, new_stage: str, *, probability: int | None = None
) -> Result[Opportunity]:
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
            probability=probability if probability is not None else DEFAULT_PROBABILITY_BY_STAGE.get(new_stage, opportunity.probability),
            owner_id=opportunity.owner_id,
            priority=opportunity.priority,
            lost_reason=opportunity.lost_reason,
            created_at=opportunity.created_at,
            sales_order_id=opportunity.sales_order_id,
        )
    )
