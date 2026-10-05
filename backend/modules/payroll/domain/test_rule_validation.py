import datetime
from dataclasses import replace
from decimal import Decimal

from core.domain.result import Err, Ok
from modules.payroll.domain.rule_validation import (
    check_complete,
    relief_from_parameters,
    relief_parameters,
    validate_component,
    validate_contribution,
    validate_rule_set_header,
    validate_tax_bracket,
    validate_tax_relief,
)
from modules.payroll.domain.rules import ComponentRule, TaxBracket
from modules.payroll.domain.synthetic import synthetic_rule_set

D = Decimal


def _component(**changes):
    values = {"code": "housing", "name_en": "Housing", "name_fr": "Logement", "kind": "earning", "formula_type": "fixed",
              "taxable": True, "contributable": True}
    values.update(changes)
    return values


def test_a_header_gets_its_defaults():
    result = validate_rule_set_header({"country": "ml", "name": "Mali 2026", "valid_from": datetime.date(2026, 1, 1),
                                       "working_days_per_month": "26", "working_hours_per_month": 173.33})
    assert isinstance(result, Ok)
    assert result.value["country"] == "ML"
    assert (result.value["round_to"], result.value["round_mode"]) == (1, "half_up")
    assert result.value["settlement_reference_months"] == 12
    assert result.value["daily_rest_day_pay"] == "overtime_only"
    assert result.value["working_hours_per_month"] == D("173.33")


def test_a_header_refuses_an_unknown_rest_day_pay_mode_in_both_languages():
    result = validate_rule_set_header({"country": "ML", "name": "x", "valid_from": datetime.date(2026, 1, 1),
                                       "working_days_per_month": 26, "working_hours_per_month": 173,
                                       "daily_rest_day_pay": "double"})
    assert isinstance(result, Err) and result.code == "RULE_INVALID" and result.message_fr


def test_a_header_starting_mid_month_is_refused_in_both_languages():
    result = validate_rule_set_header({"country": "ML", "name": "x", "valid_from": datetime.date(2026, 1, 15),
                                       "working_days_per_month": 26, "working_hours_per_month": 173})
    assert isinstance(result, Err) and result.code == "RULE_INVALID"
    assert "first day" in result.message and "premier jour" in result.message_fr


def test_a_component_code_is_normalised_to_upper_case():
    result = validate_component(_component())
    assert isinstance(result, Ok) and result.value["code"] == "HOUSING"
    assert result.value["payslip_section"] == "earnings"


def test_a_rate_x_base_component_needs_its_base():
    result = validate_component(_component(formula_type="rate_x_base"))
    assert isinstance(result, Err) and "base" in result.message


def test_an_earning_cannot_be_computed_on_the_gross():
    result = validate_component(_component(formula_type="rate_x_base", base_ref="gross"))
    assert isinstance(result, Err)


def test_a_system_code_keeps_the_kind_the_engine_expects():
    result = validate_component(_component(code="ADVANCE"))
    assert isinstance(result, Err) and "ADVANCE" in result.message


def test_only_earnings_carry_tax_and_contribution_flags():
    result = validate_component(_component(code="CANTEEN", kind="deduction"))
    assert isinstance(result, Ok)
    assert (result.value["taxable"], result.value["contributable"]) == (False, False)


def test_a_contribution_rate_is_a_percent_and_a_ceiling_is_whole_francs():
    base = {"code": "PENSION", "name_en": "Pension", "name_fr": "Retraite", "base": "contributable",
            "employee_rate": "5", "employer_rate": "10", "declaration_code": "social"}
    assert isinstance(validate_contribution(base), Ok)
    assert isinstance(validate_contribution({**base, "employee_rate": 120}), Err)
    refused = validate_contribution({**base, "ceiling_monthly": "1000.5"})
    assert isinstance(refused, Err) and "francs entiers" in refused.message_fr


def test_a_bracket_upper_bound_is_above_its_lower_bound():
    assert isinstance(validate_tax_bracket({"tax_code": "its", "lower_bound": 0, "upper_bound": 100, "rate": 5}), Ok)
    assert isinstance(validate_tax_bracket({"tax_code": "ITS", "lower_bound": 100, "upper_bound": 100, "rate": 5}), Err)


def test_relief_parameters_are_parsed_and_normalised():
    result = validate_tax_relief({"tax_code": "TAX", "kind": "family", "parameters": {
        "mode": "percent_of_tax", "steps": [{"dependants": 2, "value": 20}, {"dependants": 1, "value": "10"}]}})
    assert isinstance(result, Ok)
    assert result.value["parameters"] == {"mode": "percent_of_tax", "cap_monthly": None,
                                          "steps": [{"dependants": 1, "value": "10"}, {"dependants": 2, "value": "20"}]}
    assert isinstance(validate_tax_relief({"tax_code": "TAX", "kind": "family", "parameters": {"mode": "amount", "steps": []}}), Err)
    assert isinstance(validate_tax_relief({"tax_code": "TAX", "kind": "professional_expenses", "parameters": {"percent": 150}}), Err)


def test_relief_parameters_round_trip():
    relief = synthetic_rule_set().family_relief("TAX")
    assert relief_from_parameters("TAX", "family", relief_parameters(relief)) == relief


def test_the_synthetic_rule_set_is_complete():
    assert check_complete(synthetic_rule_set()) == []


def test_a_missing_system_component_or_band_blocks_confirmation():
    rules = synthetic_rule_set()
    problems = check_complete(replace(rules, components=tuple(c for c in rules.components if c.code != "SEVERANCE"),
                                      overtime_rates=rules.overtime_rates[:2]))
    assert ("component SEVERANCE is missing", "la rubrique SEVERANCE manque") in problems
    assert any("rest_holiday" in english for english, _ in problems)


def test_unpaid_absence_flags_mismatched_with_base_block_confirmation():
    # UNPAID_ABSENCE is deducted from earned_base to lower the taxable/contributable
    # base; if an accountant edits its flags off BASE's, the absence stops reducing
    # what it's meant to reduce and the engine can produce a silently wrong ITS.
    rules = synthetic_rule_set()
    base = next(c for c in rules.components if c.code == "BASE")
    mismatched = replace(base, code="UNPAID_ABSENCE", formula_type="per_day", contributable=not base.contributable)
    components = tuple(mismatched if c.code == "UNPAID_ABSENCE" else c for c in rules.components)
    problems = check_complete(replace(rules, components=components))
    assert any("UNPAID_ABSENCE" in english and "BASE" in english for english, _ in problems)


def test_bracket_gaps_overlaps_and_mixed_periods_block_confirmation():
    rules = synthetic_rule_set()
    gap = (TaxBracket("TAX", D(0), D(100000), D(0), False), TaxBracket("TAX", D(150000), None, D(10), False))
    assert any("gap or overlap" in english for english, _ in check_complete(replace(rules, tax_brackets=gap)))
    closed = (TaxBracket("TAX", D(0), D(100000), D(0), False),)
    assert any("open-ended" in english for english, _ in check_complete(replace(rules, tax_brackets=closed)))
    mixed = (TaxBracket("TAX", D(0), D(100000), D(0), False), TaxBracket("TAX", D(100000), None, D(10), True))
    assert any("annual and monthly" in english for english, _ in check_complete(replace(rules, tax_brackets=mixed)))
    late_start = (TaxBracket("TAX", D(10), None, D(10), False),)
    assert any("not 0" in english for english, _ in check_complete(replace(rules, tax_brackets=late_start)))
