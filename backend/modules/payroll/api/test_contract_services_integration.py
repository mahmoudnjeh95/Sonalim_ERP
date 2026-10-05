"""The services finance (phase 4) and the HR dashboard / self-service (phase 5) call."""
from __future__ import annotations

import datetime
from collections import defaultdict
from decimal import Decimal

import pytest

from modules.payroll.api.payout_service import PayoutService
from modules.payroll.api.posting_service import PayrollPostingService
from modules.payroll.api.report_service import PayrollReportService
from modules.payroll.api.run_service import RunService
from modules.payroll.api.testing_support import (
    FakePresence, FakeSnapshots, approved_run, make_user, set_country, snapshot, store_rule_set,
)

TENANT = "payroll-contract-services-test"
SEPT, OCT = datetime.date(2031, 9, 1), datetime.date(2031, 10, 1)
D = Decimal
EMPLOYEES = [
    snapshot("E1", employee_no="M-001", full_name="Awa Traoré", department_id="dept-a", tax_dependants=2,
             components=({"component_code": "HOUSING", "amount": D(30000), "rate": None},)),
    snapshot("E2", employee_no="M-002", full_name="Moussa Keita", department_id="dept-b"),
]
SUMMARIES = {"E1": {"scheduled_days": 22, "worked_days": 22, "ot_minutes_day": 600},
             "E2": {"scheduled_days": 22, "worked_days": 20, "unpaid_absence_days": 2}}


@pytest.fixture
def world(db):
    a, b = make_user(db, TENANT), make_user(db, TENANT)
    set_country(db, tenant_id=TENANT, actor_id=a)
    store_rule_set(db, tenant_id=TENANT, actor_id=a, valid_from=datetime.date(2031, 1, 1))
    snapshots, presence = FakeSnapshots(EMPLOYEES), FakePresence(SUMMARIES)
    september = approved_run(db, tenant_id=TENANT, calculator=a, approver=b, period=SEPT, snapshots=snapshots, presence=presence)
    runs = RunService(db, snapshots=snapshots, presence=presence)
    october = runs.create_run(tenant_id=TENANT, actor_id=a, period=OCT, run_type="regular").value["id"]
    runs.calculate(tenant_id=TENANT, actor_id=a, run_id=october)
    return {"db": db, "a": a, "september": september, "october": october}


def test_posting_lines_are_positive_and_balance_per_employee(world):
    lines = PayrollPostingService(world["db"]).posting_lines(tenant_id=TENANT, run_id=world["september"])
    assert lines and all(line["amount"] > 0 for line in lines)
    assert {line["source_kind"] for line in lines} == {"earning", "employee_contribution", "employer_contribution", "employer_charge", "tax", "net"}
    sums: dict[tuple[str, str], Decimal] = defaultdict(Decimal)
    for line in lines:
        sums[(line["employee_id"], line["source_kind"])] += line["amount"]
    for employee in ("E1", "E2"):
        credit = sum(sums[(employee, kind)] for kind in ("deduction", "employee_contribution", "tax", "net"))
        assert sums[(employee, "earning")] == credit, employee


def test_unpaid_absence_is_folded_into_the_base_row(world):
    lines = PayrollPostingService(world["db"]).posting_lines(tenant_id=TENANT, run_id=world["september"])
    earnings = {line["code"]: line["amount"] for line in lines if line["employee_id"] == "E2" and line["source_kind"] == "earning"}
    assert "UNPAID_ABSENCE" not in earnings and earnings["BASE"] == D(360000)
    net = world["db"].execute("SELECT net FROM payroll.payslips WHERE run_id = %s AND employee_id = 'E1'", (world["september"],)).fetchone()[0]
    assert {"source_kind": "net", "code": "NET", "amount": net, "employee_id": "E1"} in lines


def test_payment_lines_follow_the_payout_batches(world):
    PayoutService(world["db"]).generate(tenant_id=TENANT, actor_id=world["a"], run_id=world["september"])
    lines = PayrollPostingService(world["db"]).payment_lines(tenant_id=TENANT, run_id=world["september"])
    nets = world["db"].execute("SELECT SUM(net) FROM payroll.payslips WHERE run_id = %s", (world["september"],)).fetchone()[0]
    assert {line["method"] for line in lines} == {"bank"} and sum(line["amount"] for line in lines) == nets


def test_cost_by_department_counts_only_final_runs(world):
    rows = PayrollReportService(world["db"]).cost_by_department(tenant_id=TENANT, period_from=SEPT, period_to=OCT)
    assert [(row["period"], row["department_id"], row["headcount"]) for row in rows] == [(SEPT, "dept-a", 1), (SEPT, "dept-b", 1)]
    assert all(row["employer_cost"] > row["gross"] > 0 for row in rows)


def test_an_employee_sees_only_final_payslips(world):
    payslips = PayrollReportService(world["db"]).payslips_for_employee(tenant_id=TENANT, employee_id="E1")
    assert [(item["run_id"], item["period"], item["run_status"]) for item in payslips] == [(world["september"], SEPT, "approved")]
