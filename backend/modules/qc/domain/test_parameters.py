from __future__ import annotations

import pytest

from core.domain.result import Err, Ok
from modules.qc.domain.parameters import PARAMETER_GROUPS, validate_parameter_entry


def test_every_declared_group_has_at_least_one_field():
    for group_key, fields in PARAMETER_GROUPS.items():
        assert len(fields) > 0, group_key


def test_unknown_group_is_rejected():
    result = validate_parameter_entry("not_a_group", {})
    assert isinstance(result, Err)
    assert result.code == "INVALID_GROUP"


def test_unknown_field_for_a_group_is_rejected():
    result = validate_parameter_entry("sechage", {"not_a_field": 1})
    assert isinstance(result, Err)
    assert result.code == "INVALID_FIELD"


def test_valid_fields_for_sechage_are_accepted():
    result = validate_parameter_entry("sechage", {"temperature_c": 78.4, "delta": 7.1})
    assert isinstance(result, Ok)


def test_percentage_field_out_of_range_is_rejected():
    result = validate_parameter_entry("presse", {"niveau_moulange_percent": 150})
    assert isinstance(result, Err)
    assert result.code == "INVALID_PERCENTAGE"


def test_percentage_field_in_range_is_accepted():
    result = validate_parameter_entry("presse", {"niveau_moulange_percent": 48.9})
    assert isinstance(result, Ok)


@pytest.mark.parametrize("group_key", list(PARAMETER_GROUPS))
def test_empty_fields_is_always_valid(group_key):
    """A row can be saved with only its entry_label typed so far; fields fill in as the inspector reads the gauge."""
    result = validate_parameter_entry(group_key, {})
    assert isinstance(result, Ok)
