"""The seed's plan is deterministic and every person in it is valid for the hr rules."""
from __future__ import annotations

import datetime

from scripts.seed_hr_payroll import TODAY, _add_years, plans


def test_the_plan_is_sixty_distinct_people_and_the_same_every_run():
    first, second = plans(), plans()
    assert first == second
    assert len(first) == 60
    assert len({p.employee_no for p in first}) == 60
    assert len({p.badge_no for p in first}) == 60


def test_every_person_is_an_adult_when_hired_and_every_contract_holds_together():
    for plan in plans():
        assert plan.birth_date.replace(year=plan.birth_date.year + 18) <= plan.hire_date, plan.employee_no
        assert plan.contract_end is None or plan.contract_end >= plan.hire_date, plan.employee_no
        assert plan.trial_end is None or plan.hire_date <= plan.trial_end, plan.employee_no


def test_the_plan_exercises_the_alerts_amendments_and_exits():
    everyone = plans()
    horizon = TODAY + datetime.timedelta(days=30)
    assert sum(1 for p in everyone if p.contract_type == "cdd" and p.contract_end and TODAY <= p.contract_end <= horizon) >= 3
    assert sum(1 for p in everyone if p.trial_end and TODAY <= p.trial_end <= TODAY + datetime.timedelta(days=15)) >= 2
    assert {p.contract_type for p in everyone} == {"cdi", "cdd", "apprentice", "daily", "intern"}
    assert sum(1 for p in everyone if p.raise_from) == 5
    assert sum(1 for p in everyone if p.leaves_on) == 2
    assert {p.payment for p in everyone} == {"bank", "mobile", "cash", "split"}


def test_the_plan_still_works_for_a_day_in_2030():
    # Before the fix, the hardcoded upper bound (2024/2025) made randint's range empty once
    # birth.year + 19 passed it, and 2030 is well past that for the youngest ages (22).
    everyone = plans(today=datetime.date(2030, 6, 15))
    assert len(everyone) == 60
    for plan in everyone:
        assert plan.birth_date.replace(year=plan.birth_date.year + 18) <= plan.hire_date, plan.employee_no


def test_the_plan_is_the_same_every_run_for_a_29_february_today():
    # today.year feeds birth/hire year arithmetic (never date.replace), so a leap-day today by
    # itself doesn't hit the bug; this just confirms plans() stays deterministic and crash-free
    # on that date too. The actual 29 Feb trap (a birth date landing on it, then +N years) is
    # _add_years, covered directly below.
    leap_day = datetime.date(2028, 2, 29)
    first, second = plans(today=leap_day), plans(today=leap_day)
    assert first == second
    assert len(first) == 60


def test_add_years_falls_back_to_28_february_instead_of_raising():
    born_on_leap_day = datetime.date(2024, 2, 29)
    assert _add_years(born_on_leap_day, 1) == datetime.date(2025, 2, 28)  # 2025 is not a leap year
    assert _add_years(born_on_leap_day, 4) == datetime.date(2028, 2, 29)  # 2028 is a leap year: stays 29 Feb
    assert _add_years(datetime.date(2023, 6, 15), 25) == datetime.date(2048, 6, 15)  # ordinary date: unaffected
