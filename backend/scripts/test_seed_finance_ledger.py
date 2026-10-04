"""The seed's one decision: which contribution codes get an AMO rule (433), from the codes a run uses."""
from decimal import Decimal

from scripts.seed_finance_ledger import amo_rules


def test_amo_contribution_codes_get_a_433_rule_once():
    # Mali's real AMO code (payroll_mali_rules.py) is the bare string "AMO", shared by the
    # employee and employer contribution lines — only source_kind tells them apart, so a rule
    # keyed on code alone would wrongly merge them into one.
    lines = [
        {"source_kind": "employee_contribution", "code": "AMO", "amount": Decimal(100), "employee_id": "e1"},
        {"source_kind": "employee_contribution", "code": "AMO", "amount": Decimal(100), "employee_id": "e2"},
        {"source_kind": "employer_contribution", "code": "AMO", "amount": Decimal(150), "employee_id": "e1"},
        {"source_kind": "employee_contribution", "code": "INPS_EE", "amount": Decimal(300), "employee_id": "e1"},
        {"source_kind": "earning", "code": "AMO_BONUS", "amount": Decimal(5), "employee_id": "e1"},
    ]
    assert amo_rules(lines) == [
        ("employee_contribution", "AMO", None, "433"),
        ("employer_contribution", "AMO", "664", "433"),
    ]
