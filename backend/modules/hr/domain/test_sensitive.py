from decimal import Decimal

from modules.hr.domain.sensitive import (
    CONTRACT_WRITE_FIELDS,
    EMPLOYEE_FIELDS,
    PAYMENT_FIELDS,
    filled,
    mask,
    mask_contract,
    written,
)


def test_a_caller_without_the_right_sees_the_fields_emptied_and_flagged():
    record = {"id": "e1", "first_name": "Awa", "national_id": "NINA-1", "inps_no": "INPS-1", "amo_no": None}
    shown = mask(record, EMPLOYEE_FIELDS, visible=False)
    assert shown == {
        "id": "e1",
        "first_name": "Awa",
        "national_id": None,
        "inps_no": None,
        "amo_no": None,
        "sensitive_hidden": True,
    }
    assert record["national_id"] == "NINA-1"  # the service's own record is left untouched


def test_a_caller_with_the_right_sees_everything():
    record = {"account_no": "ML-0001", "mobile_number": None}
    assert mask(record, PAYMENT_FIELDS, visible=True) == {"account_no": "ML-0001", "mobile_number": None, "sensitive_hidden": False}


def test_a_field_the_record_does_not_carry_is_not_invented():
    assert "inps_no" not in mask({"id": "e1"}, EMPLOYEE_FIELDS, visible=False)


def test_a_hidden_contract_keeps_its_component_codes_but_not_their_values():
    contract = {
        "base_salary": Decimal("150000"),
        "components": [{"component_code": "TRANSPORT", "amount": Decimal("15000"), "rate": None}],
    }
    shown = mask_contract(contract, visible=False)
    assert shown["base_salary"] is None
    assert shown["components"] == [{"component_code": "TRANSPORT", "amount": None, "rate": None}]
    assert shown["sensitive_hidden"] is True


def test_written_lists_the_sensitive_fields_a_patch_mentions_even_to_clear_them():
    assert written({"first_name": "Awa", "national_id": None}, EMPLOYEE_FIELDS) == ["national_id"]


def test_filled_ignores_blank_values_and_empty_lists_but_not_zero():
    assert filled({"base_salary": Decimal("0"), "components": []}, CONTRACT_WRITE_FIELDS) == ["base_salary"]
    assert filled({"account_no": "", "mobile_number": None}, PAYMENT_FIELDS) == []
