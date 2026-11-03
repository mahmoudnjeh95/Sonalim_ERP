"""Final settlements: off-cycle only, only for someone leaving that month, never paid twice."""
from __future__ import annotations

import datetime
from decimal import Decimal

import pytest

from core.domain.result import Err, Ok
from modules.payroll.api.run_service import RunService
from modules.payroll.api.testing_support import (
    FakePresence, FakeSnapshots, insert_payslip, insert_run, make_user, set_country, snapshot, store_rule_set,
)

TENANT = "payroll-settlement-test"
SEPT = datetime.date(2031, 9, 1)
D = Decimal
EMPLOYEES = [
    snapshot("E1", employee_no="M-001", full_name="Awa Traoré"),
    snapshot("E9", employee_no="M-009", full_name="Seydou Coulibaly", base_salary=D(300000), hire_date=datetime.date(2019, 9, 15),
             termination_date=datetime.date(2031, 9, 15), termination_reason="resignation"),
]
SUMMARIES = {"E1": {"scheduled_days": 22, "worked_days": 22}, "E9": {"scheduled_days": 10, "worked_days": 10}}


@pytest.fixture
def world(db):
    actor = make_user(db, TENANT)
    set_country(db, tenant_id=TENANT, actor_id=actor)
    rule_set_id = store_rule_set(db, tenant_id=TENANT, actor_id=actor, valid_from=datetime.date(2019, 1, 1))
    runs = RunService(db, snapshots=FakeSnapshots(EMPLOYEES), presence=FakePresence(SUMMARIES))
    return {"db": db, "actor": actor, "rule_set_id": rule_set_id, "runs": runs}


def _run(world, run_type="off_cycle"):
    return world["runs"].create_run(tenant_id=TENANT, actor_id=world["actor"], period=SEPT, run_type=run_type).value["id"]


def _settle(world, run_id, employee_id="E9", leave=D(10), notice=D(1)):
    return world["runs"].add_final_settlement(tenant_id=TENANT, actor_id=world["actor"], run_id=run_id, employee_id=employee_id,
                                              unused_leave_days=leave, notice_months=notice)


def _payslip_employees(world, run_id):
    return sorted(row[0] for row in world["db"].execute("SELECT employee_id FROM payroll.payslips WHERE run_id = %s", (run_id,)).fetchall())


def test_a_final_settlement_goes_on_an_off_cycle_run(world):
    refused = _settle(world, _run(world, run_type="regular"))
    assert isinstance(refused, Err) and refused.code == "SETTLEMENT_INVALID" and refused.message_fr


def test_only_someone_leaving_that_month_can_be_settled(world):
    refused = _settle(world, _run(world), employee_id="E1")
    assert isinstance(refused, Err) and refused.code == "SETTLEMENT_INVALID" and "Awa Traoré" in refused.message


def test_the_settlement_payslip_pays_the_month_to_the_exit_date_and_the_indemnities(world):
    run_id = _run(world)
    settled = _settle(world, run_id)
    assert isinstance(settled, Ok) and settled.value["full_name"] == "Seydou Coulibaly"
    assert isinstance(world["runs"].calculate(tenant_id=TENANT, actor_id=world["actor"], run_id=run_id), Ok)
    gross, net, document = world["db"].execute(
        "SELECT gross, net, snapshot FROM payroll.payslips WHERE run_id = %s AND employee_id = 'E9'", (run_id,)).fetchone()
    # the golden final settlement of plan 3a Task 9: 12 years, 10 of 20 days, 10 leave days, 1 month notice
    assert (gross, net) == (D(1462500), D(1355280))
    assert document["settlement"] == {"reference_salary": 300000, "years_of_service": 12, "unused_leave_days": 10, "notice_months": 1}
    assert _payslip_employees(world, run_id) == ["E9"]


def test_the_regular_run_leaves_out_an_employee_settled_off_cycle(world):
    off_cycle = _run(world)
    _settle(world, off_cycle)
    regular = _run(world, run_type="regular")
    world["runs"].calculate(tenant_id=TENANT, actor_id=world["actor"], run_id=regular)
    assert _payslip_employees(world, regular) == ["E1"]
    world["db"].execute("UPDATE payroll.runs SET status = 'reversed' WHERE id = %s", (off_cycle,))
    world["runs"].calculate(tenant_id=TENANT, actor_id=world["actor"], run_id=regular)
    assert _payslip_employees(world, regular) == ["E1", "E9"]


def test_the_reference_salary_averages_the_approved_regular_months(world):
    for month in (7, 8):
        history = insert_run(world["db"], tenant_id=TENANT, actor_id=world["actor"], period=datetime.date(2031, month, 1),
                             status="approved", rule_set_id=world["rule_set_id"])
        insert_payslip(world["db"], tenant_id=TENANT, run_id=history, employee_id="E9", rule_set_id=world["rule_set_id"], gross=D(330000))
    run_id = _run(world)
    _settle(world, run_id)
    world["runs"].calculate(tenant_id=TENANT, actor_id=world["actor"], run_id=run_id)
    document = world["db"].execute("SELECT snapshot FROM payroll.payslips WHERE run_id = %s", (run_id,)).fetchone()[0]
    assert document["settlement"]["reference_salary"] == 330000


def test_changing_or_removing_a_settlement_sends_a_calculated_run_back_to_draft(world):
    run_id = _run(world)
    settlement_id = _settle(world, run_id).value["id"]
    world["runs"].calculate(tenant_id=TENANT, actor_id=world["actor"], run_id=run_id)
    updated = world["runs"].update_final_settlement(tenant_id=TENANT, actor_id=world["actor"], run_id=run_id,
                                                    settlement_id=settlement_id, changes={"notice_months": D(2)})
    assert isinstance(updated, Ok) and updated.value["notice_months"] == 2
    assert world["runs"].get_run(tenant_id=TENANT, run_id=run_id)["status"] == "draft"
    assert isinstance(world["runs"].remove_final_settlement(tenant_id=TENANT, actor_id=world["actor"], run_id=run_id, settlement_id=settlement_id), Ok)
    assert world["runs"].list_final_settlements(tenant_id=TENANT, run_id=run_id) == []


def test_one_settlement_per_employee_and_run(world):
    run_id = _run(world)
    _settle(world, run_id)
    again = _settle(world, run_id)
    assert isinstance(again, Err) and again.code == "DUPLICATE_SETTLEMENT"
