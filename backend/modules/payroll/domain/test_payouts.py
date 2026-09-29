from datetime import date
from decimal import Decimal

from core.domain.result import Err, Ok
from modules.payroll.domain.payouts import billetage, render_bank_csv, render_mobile_csv, split_net, validate_bank_template

D = Decimal
BANK = {"method": "bank", "bank_name": "BDM", "account_no": "ML-0123", "mobile_operator": None,
        "mobile_number": None, "share_percent": 100, "is_primary": True}
MOBILE = {"method": "mobile_money", "bank_name": None, "account_no": None, "mobile_operator": "Orange Money",
          "mobile_number": "+22370000000", "share_percent": 40, "is_primary": False}
LINE = {"employee_no": "M-001", "full_name": "Awa Traoré", "amount": D(376035),
        "details": {"bank_name": "BDM", "account_no": "ML-0123", "mobile_operator": "Orange Money", "mobile_number": "+22370000000"}}


def test_one_method_takes_the_whole_net():
    result = split_net(D(376035), [BANK])
    assert isinstance(result, Ok)
    assert [(share.method, share.group_key, share.amount) for share in result.value] == [("bank", "BDM", D(376035))]


def test_other_methods_round_down_and_the_primary_takes_the_rest():
    result = split_net(D(100001), [{**BANK, "bank_name": "Ecobank", "share_percent": 60}, MOBILE])
    assert [(share.method, share.group_key, share.amount) for share in result.value] == [
        ("mobile_money", "ORANGE MONEY", D(40000)), ("bank", "ECOBANK", D(60001)),
    ]


def test_shares_must_add_up_to_one_hundred():
    result = split_net(D(1000), [{**BANK, "share_percent": 50}])
    assert isinstance(result, Err) and result.code == "PAYOUT_SPLIT_INVALID" and "100" in result.message_fr


def test_a_bank_payment_needs_an_account_and_a_payslip_needs_a_method():
    assert isinstance(split_net(D(1000), [{**BANK, "account_no": None}]), Err)
    assert isinstance(split_net(D(1000), []), Err)


def test_nothing_to_pay_gives_no_share():
    assert split_net(D(0), [BANK]).value == []


def test_billetage_counts_notes_and_coins():
    counts, remainder = billetage(D(37340))
    assert {value: count for value, count in counts.items() if count} == {10000: 3, 5000: 1, 2000: 1, 250: 1, 50: 1, 25: 1, 10: 1, 5: 1}
    assert remainder == 0 and sum(value * count for value, count in counts.items()) == 37340


def test_the_bank_file_follows_its_template():
    template = {"bank_name": "BDM", "delimiter": ";", "include_header": True, "columns": [
        {"header": "Compte", "field": "account_no"}, {"header": "Montant", "field": "amount"}, {"header": "Libellé", "field": "reference"},
    ]}
    assert render_bank_csv(template, [LINE], date(2026, 9, 1)) == "Compte;Montant;Libellé\r\nML-0123;376035;PAIE 2026-09 M-001\r\n"


def test_the_mobile_money_file_has_operator_number_name_amount():
    assert render_mobile_csv([{**LINE, "amount": D(50000)}]) == "operator;number;name;amount\r\nOrange Money;+22370000000;Awa Traoré;50000\r\n"


def test_a_template_names_known_fields_only():
    ok = validate_bank_template({"bank_name": " bdm ", "columns": [{"header": "Compte", "field": "account_no"}]})
    assert isinstance(ok, Ok)
    assert ok.value == {"bank_name": "BDM", "delimiter": ";", "include_header": True, "columns": [{"header": "Compte", "field": "account_no"}]}
    assert isinstance(validate_bank_template({"bank_name": "BDM", "columns": [{"header": "x", "field": "salary"}]}), Err)
    assert isinstance(validate_bank_template({"bank_name": "BDM", "columns": []}), Err)
