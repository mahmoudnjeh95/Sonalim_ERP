from datetime import date

from core.domain.result import Ok
from modules.hr.domain.dependant import Dependant, count_tax_dependants, validate_dependant


def test_a_dependant_needs_a_known_kind_and_a_name():
    assert validate_dependant(Dependant(kind="cousin", name="Issa", valid_from=date(2020, 1, 1))).code == "INVALID_CHOICE"
    assert validate_dependant(Dependant(kind="child", name=" ", valid_from=date(2020, 1, 1))).code == "INVALID_DEPENDANT"
    assert validate_dependant(Dependant(kind="child", name="Issa", valid_from=None)).code == "INVALID_DEPENDANT"


def test_the_name_is_trimmed():
    result = validate_dependant(Dependant(kind="child", name="  Issa ", valid_from=date(2020, 1, 1)))
    assert isinstance(result, Ok) and result.value.name == "Issa"


def test_validity_cannot_end_before_it_starts():
    refused = validate_dependant(Dependant(kind="child", name="Issa", valid_from=date(2020, 1, 1), valid_to=date(2019, 12, 31)))
    assert refused.code == "INVALID_DATES"


def test_a_dependant_cannot_count_before_being_born():
    refused = validate_dependant(Dependant(kind="child", name="Issa", birth_date=date(2021, 5, 1), valid_from=date(2021, 1, 1)))
    assert refused.code == "INVALID_DATES"


def test_the_tax_count_is_taken_on_the_given_day():
    spouse = Dependant(kind="spouse", name="Mariam", valid_from=date(2015, 6, 1), dependent_for_tax=True)
    child = Dependant(kind="child", name="Issa", birth_date=date(2019, 2, 1), valid_from=date(2019, 2, 1), dependent_for_tax=True, valid_to=date(2026, 9, 15))
    not_for_tax = Dependant(kind="child", name="Awa", valid_from=date(2010, 1, 1), dependent_for_tax=False)
    everyone = [spouse, child, not_for_tax]
    assert count_tax_dependants(everyone, date(2026, 9, 15)) == 2  # the last day of validity still counts
    assert count_tax_dependants(everyone, date(2026, 9, 30)) == 1
    assert count_tax_dependants(everyone, date(2015, 5, 31)) == 0
