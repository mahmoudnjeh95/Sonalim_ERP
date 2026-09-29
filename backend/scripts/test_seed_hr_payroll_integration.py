"""The seed runs on the dev database (inside the rolled-back test transaction) and twice gives the same."""
from __future__ import annotations

import pytest

from scripts import seed_hr_payroll
from scripts.seed_common import ACTOR_EMAIL, TENANT


def _count(db) -> int:
    return db.execute("SELECT count(*) FROM hr.employees WHERE tenant_id = %s AND employee_no LIKE 'HRP-%%'", (TENANT,)).fetchone()[0]


def test_the_seed_creates_the_plant_once(db):
    if db.execute("SELECT 1 FROM core.users WHERE email = %s", (ACTOR_EMAIL,)).fetchone() is None:
        pytest.skip("the demo user is missing: run scripts.seed_dev first")
    seed_hr_payroll.seed(db, None)
    assert _count(db) == 60
    contracts = db.execute(
        "SELECT count(*) FROM hr.contracts c JOIN hr.employees e ON e.id = c.employee_id "
        "WHERE e.tenant_id = %s AND e.employee_no LIKE 'HRP-%%' AND c.status <> 'draft'",
        (TENANT,),
    ).fetchone()[0]
    assert contracts == 65  # 60 hires + 5 amendments
    seed_hr_payroll.seed(db, None)
    assert _count(db) == 60
