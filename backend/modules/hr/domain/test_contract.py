import datetime
from decimal import Decimal

from core.domain.result import Ok
from modules.hr.domain.contract import (
    ContractComponent,
    ContractPeriod,
    ContractTerms,
    end_status,
    overlapping,
    validate_components,
    validate_terms,
)

D = datetime.date


def _terms(**overrides) -> ContractTerms:
    return ContractTerms(**{"employee_id": "e1", "contract_type": "cdd", "start_date": D(2026, 1, 1), "base_salary": Decimal("150000"), **overrides})


def test_valid_terms_come_back_with_their_components_cleaned():
    result = validate_terms(_terms(components=(ContractComponent(component_code=" transport ", amount=Decimal("15000")),)))
    assert isinstance(result, Ok)
    assert result.value.components == (ContractComponent(component_code="TRANSPORT", amount=Decimal("15000")),)


def test_an_unknown_contract_type_is_refused():
    assert validate_terms(_terms(contract_type="permanent")).code == "INVALID_CONTRACT_TYPE"


def test_pay_is_whole_francs():
    assert validate_terms(_terms(base_salary=Decimal("150000.50"))).code == "INVALID_AMOUNT"
    assert validate_terms(_terms(base_salary=None)).code == "INVALID_AMOUNT"


def test_weekly_hours_stay_within_a_week():
    assert validate_terms(_terms(weekly_hours=Decimal("0"))).code == "INVALID_CONTRACT"
    assert validate_terms(_terms(weekly_hours=Decimal("169"))).code == "INVALID_CONTRACT"
    assert validate_terms(_terms(weekly_hours=None)).code == "INVALID_CONTRACT"
    assert isinstance(validate_terms(_terms(weekly_hours=Decimal("48"))), Ok)


def test_weekly_hours_allow_two_decimals_but_not_three():
    assert isinstance(validate_terms(_terms(weekly_hours=Decimal("37.75"))), Ok)
    assert validate_terms(_terms(weekly_hours=Decimal("37.755"))).code == "INVALID_CONTRACT"


def test_base_salary_stays_below_the_numeric_18_0_column():
    assert isinstance(validate_terms(_terms(base_salary=Decimal(10) ** 18 - 1)), Ok)
    assert validate_terms(_terms(base_salary=Decimal(10) ** 18)).code == "INVALID_AMOUNT"


def test_dates_hold_together():
    assert validate_terms(_terms(start_date=None)).code == "INVALID_DATES"
    assert validate_terms(_terms(end_date=D(2025, 12, 31))).code == "INVALID_DATES"
    assert validate_terms(_terms(end_date=D(2026, 6, 30), trial_end_date=D(2026, 7, 1))).code == "INVALID_DATES"
    assert validate_terms(_terms(trial_end_date=D(2025, 12, 31))).code == "INVALID_DATES"


def test_an_end_reason_is_known_and_needs_an_end_date():
    assert validate_terms(_terms(end_reason="resignation")).code == "INVALID_END_REASON"
    assert validate_terms(_terms(end_date=D(2026, 6, 30), end_reason="bored")).code == "INVALID_END_REASON"


def test_a_component_has_an_amount_or_a_rate_never_both_or_neither():
    both = ContractComponent(component_code="HOUSING", amount=Decimal("1"), rate=Decimal("1"))
    neither = ContractComponent(component_code="HOUSING")
    assert validate_components([both]).code == "INVALID_COMPONENT"
    assert validate_components([neither]).code == "INVALID_COMPONENT"
    assert validate_components([ContractComponent(component_code="HOUSING", rate=Decimal("-1"))]).code == "INVALID_COMPONENT"
    assert validate_components([ContractComponent(component_code="9X", amount=Decimal("1"))]).code == "INVALID_COMPONENT"


def test_a_component_rate_stays_below_the_numeric_9_4_column_with_at_most_four_decimals():
    assert isinstance(validate_components([ContractComponent(component_code="HOUSING", rate=Decimal("12.3456"))]), Ok)
    assert validate_components([ContractComponent(component_code="HOUSING", rate=Decimal("100000"))]).code == "INVALID_COMPONENT"
    assert validate_components([ContractComponent(component_code="HOUSING", rate=Decimal("12.34567"))]).code == "INVALID_COMPONENT"


def test_a_component_amount_stays_below_the_numeric_18_0_column():
    assert validate_components([ContractComponent(component_code="HOUSING", amount=Decimal(10) ** 18)]).code == "INVALID_AMOUNT"


def test_a_component_appears_once():
    twice = [ContractComponent(component_code="TRANSPORT", amount=Decimal("1")), ContractComponent(component_code="transport", amount=Decimal("2"))]
    assert validate_components(twice).code == "INVALID_COMPONENT"


def test_contracts_that_share_a_day_overlap():
    signed = ContractPeriod(id="a", start_date=D(2026, 1, 1), end_date=D(2026, 6, 30), status="active")
    assert overlapping(ContractPeriod(id="b", start_date=D(2026, 6, 30), end_date=None, status="active"), [signed]) == signed
    assert overlapping(ContractPeriod(id="b", start_date=D(2026, 7, 1), end_date=None, status="active"), [signed]) is None


def test_an_open_ended_contract_overlaps_everything_after_it():
    open_ended = ContractPeriod(id="a", start_date=D(2020, 1, 1), end_date=None, status="active")
    later = ContractPeriod(id="b", start_date=D(2030, 1, 1), end_date=D(2030, 2, 1), status="active")
    assert overlapping(later, [open_ended]) == open_ended


def test_drafts_never_conflict():
    signed = ContractPeriod(id="a", start_date=D(2026, 1, 1), end_date=None, status="active")
    draft = ContractPeriod(id="b", start_date=D(2026, 3, 1), end_date=None, status="draft")
    assert overlapping(draft, [signed]) is None
    assert overlapping(ContractPeriod(id="c", start_date=D(2026, 3, 1), end_date=None, status="active"), [draft]) is None


def test_a_contract_does_not_overlap_itself_and_ended_ones_keep_their_days():
    signed = ContractPeriod(id="a", start_date=D(2026, 1, 1), end_date=None, status="active")
    assert overlapping(signed, [signed]) is None
    ended = ContractPeriod(id="x", start_date=D(2025, 1, 1), end_date=D(2025, 12, 31), status="terminated")
    assert overlapping(ContractPeriod(id="b", start_date=D(2025, 6, 1), end_date=None, status="active"), [ended]) == ended


def test_a_term_or_an_amendment_expires_a_contract_anything_else_terminates_it():
    assert [end_status(reason) for reason in ("term_reached", "amended", "resignation", "dismissal")] == [
        "expired", "expired", "terminated", "terminated",
    ]
