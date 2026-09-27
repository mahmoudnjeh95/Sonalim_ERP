"""The seed's plan is deterministic and every person in it is valid for the hr rules."""
from __future__ import annotations

import datetime

from scripts.seed_hr_payroll import TODAY, plans


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
