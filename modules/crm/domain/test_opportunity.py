from core.domain.result import Err, Ok
from modules.crm.domain.opportunity import Opportunity, WonLine, transition_opportunity, validate_amount, validate_won_lines


def test_prospecting_can_advance_to_qualification():
    opportunity = Opportunity(id="1", partner_id="a1", name="Deal", stage="prospecting", amount=1000)
    result = transition_opportunity(opportunity, "qualification")
    assert isinstance(result, Ok)
    assert result.value.stage == "qualification"


def test_won_is_terminal():
    opportunity = Opportunity(id="1", partner_id="a1", name="Deal", stage="won", amount=1000)
    result = transition_opportunity(opportunity, "negotiation")
    assert isinstance(result, Err)
    assert result.code == "INVALID_TRANSITION"


def test_negotiation_can_be_lost():
    opportunity = Opportunity(id="1", partner_id="a1", name="Deal", stage="negotiation", amount=1000)
    result = transition_opportunity(opportunity, "lost")
    assert isinstance(result, Ok)
    assert result.value.stage == "lost"


def test_negative_amount_is_invalid():
    result = validate_amount(-1)
    assert isinstance(result, Err)
    assert result.code == "INVALID_AMOUNT"


def test_won_lines_requires_at_least_one_line():
    result = validate_won_lines([])
    assert isinstance(result, Err)
    assert result.code == "EMPTY_LINES"


def test_won_lines_requires_at_least_one_line_when_none():
    result = validate_won_lines(None)
    assert isinstance(result, Err)
    assert result.code == "EMPTY_LINES"


def test_won_lines_rejects_non_positive_quantity():
    result = validate_won_lines([WonLine(product_id="p1", quantity=0)])
    assert isinstance(result, Err)
    assert result.code == "INVALID_QUANTITY"


def test_won_lines_accepts_valid_lines():
    result = validate_won_lines([WonLine(product_id="p1", quantity=2), WonLine(product_id="p2", quantity=5)])
    assert isinstance(result, Ok)
