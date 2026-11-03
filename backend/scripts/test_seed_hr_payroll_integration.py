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


def _payroll_counts(db) -> dict[str, int]:
    queries = {
        "rule_sets": ("SELECT count(*) FROM payroll.rule_sets WHERE tenant_id = %s AND country = 'ML'", (TENANT,)),
        "runs": ("SELECT count(*) FROM payroll.runs WHERE tenant_id = %s AND period = %s AND run_type = 'regular'",
                 (TENANT, seed_hr_payroll.PAYROLL_PERIOD)),
        "inputs": ("SELECT count(*) FROM payroll.run_inputs r JOIN payroll.runs run ON run.id = r.run_id WHERE run.tenant_id = %s", (TENANT,)),
        "advances": ("SELECT count(*) FROM payroll.advances WHERE tenant_id = %s", (TENANT,)),
        "loans": ("SELECT count(*) FROM payroll.loans WHERE tenant_id = %s", (TENANT,)),
    }
    return {name: db.execute(sql, params).fetchone()[0] for name, (sql, params) in queries.items()}


def test_the_seed_adds_a_draft_mali_rule_set_and_one_calculated_run(db):
    if db.execute("SELECT 1 FROM core.users WHERE email = %s", (ACTOR_EMAIL,)).fetchone() is None:
        pytest.skip("the demo user is missing: run scripts.seed_dev first")
    seed_hr_payroll.seed(db, None)
    rule_set = db.execute("SELECT status FROM payroll.rule_sets WHERE tenant_id = %s AND country = 'ML'", (TENANT,)).fetchone()
    assert rule_set == ("draft",)
    run = db.execute(
        "SELECT status, run_type, rule_set_id IS NOT NULL FROM payroll.runs WHERE tenant_id = %s AND period = %s AND run_type = 'regular'",
        (TENANT, seed_hr_payroll.PAYROLL_PERIOD),
    ).fetchone()
    assert run == ("calculated", "regular", True)
    payslips = db.execute(
        "SELECT count(*) FROM payroll.payslips p JOIN payroll.runs r ON r.id = p.run_id "
        "WHERE r.tenant_id = %s AND r.period = %s AND r.run_type = 'regular'",
        (TENANT, seed_hr_payroll.PAYROLL_PERIOD),
    ).fetchone()[0]
    assert payslips >= 50  # the 60 demo employees, less anyone not under contract in August
    counts = _payroll_counts(db)
    assert counts["rule_sets"] == 1 and counts["runs"] == 1
    assert counts["inputs"] >= 1 and counts["advances"] >= 1 and counts["loans"] >= 1
    seed_hr_payroll.seed(db, None)  # idempotent: no duplicate rule set, run, input, advance or loan
    assert _payroll_counts(db) == counts
