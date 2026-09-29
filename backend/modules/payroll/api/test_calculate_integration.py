"""Calculating runs against a real database, with hr replaced by contract-shaped fakes.

Rules are the synthetic test set (plan 3a, domain/synthetic.py); the first employee reproduces the
golden full-month payslip, so its net is the hand-computed 376 035.
"""
from __future__ import annotations

import datetime
from decimal import Decimal

import pytest

from core.domain.result import Err, Ok
from modules.payroll.api.input_service import InputService
from modules.payroll.api.run_service import RunService
from modules.payroll.api.testing_support import (
    FakePresence, FakeSnapshots, make_user, set_country, snapshot, store_rule_set,
)

TENANT = "payroll-calculate-test"
SEPT = datetime.date(2031, 9, 1)
OCT = datetime.date(2031, 10, 1)
D = Decimal

EMPLOYEES = [
    snapshot("E1", employee_no="M-001", full_name="Awa Traoré", hire_date=datetime.date(2026, 9, 1), tax_dependants=2,
             components=({"component_code": "HOUSING", "amount": D(30000), "rate": None},
                         {"component_code": "TRANSPORT", "amount": D(10000), "rate": None})),
    snapshot("E3", employee_no="M-003", full_name="Oumar Diarra", base_salary=D(100000), hire_date=datetime.date(2031, 1, 1)),
]
SUMMARIES = {"E1": {"scheduled_days": 22, "worked_days": 22, "ot_minutes_day": 600},
             "E3": {"scheduled_days": 22, "worked_days": 22}}


@pytest.fixture
def world(db):
    actor = make_user(db, TENANT)
    set_country(db, tenant_id=TENANT, actor_id=actor)
    rule_set_id = store_rule_set(db, tenant_id=TENANT, actor_id=actor, valid_from=datetime.date(2031, 1, 1))
    snapshots, presence = FakeSnapshots(EMPLOYEES), FakePresence(SUMMARIES, closed=True)
    runs = RunService(db, snapshots=snapshots, presence=presence)
    inputs = InputService(db, snapshots=snapshots)
    return {"db": db, "actor": actor, "rule_set_id": rule_set_id, "runs": runs, "inputs": inputs, "presence": presence}


def _regular(world, period=SEPT):
    return world["runs"].create_run(tenant_id=TENANT, actor_id=world["actor"], period=period, run_type="regular").value["id"]


def _approved_advance(world, employee_id, amount, period=SEPT):
    advance = world["inputs"].create_advance(tenant_id=TENANT, actor_id=world["actor"], employee_id=employee_id, amount=D(amount),
                                             requested_on=period, deduct_period=period).value
    world["inputs"].approve_advance(tenant_id=TENANT, actor_id=world["actor"], advance_id=advance["id"])
    return advance["id"]


def _calculate(world, run_id):
    return world["runs"].calculate(tenant_id=TENANT, actor_id=world["actor"], run_id=run_id)


def _payslip(world, run_id, employee_id):
    return world["db"].execute(
        "SELECT id, gross, net, deductions, warnings, rule_set_status, snapshot FROM payroll.payslips WHERE run_id = %s AND employee_id = %s",
        (run_id, employee_id)).fetchone()


def test_calculation_waits_for_the_presence_month_to_be_closed(world):
    world["presence"].closed = False
    refused = _calculate(world, _regular(world))
    assert isinstance(refused, Err) and refused.code == "PRESENCE_NOT_CLOSED" and "09/2031" in refused.message_fr


def test_no_rule_set_no_calculation(world):
    refused = _calculate(world, _regular(world, period=datetime.date(2030, 12, 1)))
    assert isinstance(refused, Err) and refused.code == "RULESET_MISSING"


def test_one_payslip_per_employee_with_lines_and_the_inputs_it_used(world):
    advance_id = _approved_advance(world, "E1", 50000)
    run_id = _regular(world)
    calculated = _calculate(world, run_id)
    assert isinstance(calculated, Ok)
    assert (calculated.value["status"], calculated.value["payslip_count"], calculated.value["calculated_by"]) == ("calculated", 2, world["actor"])
    payslip_id, gross, net, deductions, warnings, rule_set_status, document = _payslip(world, run_id, "E1")
    assert (gross, net, deductions, warnings, rule_set_status) == (D(497500), D(376035), D(50000), [], "confirmed")
    assert document["employee"]["employee_no"] == "M-001" and document["presence"]["ot_minutes_day"] == 600
    assert document["rule_set"]["status"] == "confirmed" and document["payment_methods"][0]["bank_name"] == "BDM"
    assert [item["source_kind"] for item in document["inputs"]] == ["advance"]
    lines = world["db"].execute("SELECT count(*) FROM payroll.payslip_lines WHERE payslip_id = %s", (payslip_id,)).fetchone()[0]
    assert lines > 5
    taken = world["db"].execute("SELECT deducted_payslip_id FROM payroll.advances WHERE id = %s", (advance_id,)).fetchone()[0]
    assert taken == payslip_id


def test_calculating_again_gives_the_same_payslips(world):
    advance_id = _approved_advance(world, "E1", 50000)
    run_id = _regular(world)
    _calculate(world, run_id)
    _calculate(world, run_id)
    assert world["db"].execute("SELECT count(*) FROM payroll.payslips WHERE run_id = %s", (run_id,)).fetchone()[0] == 2
    payslip_id, _, net, *_ = _payslip(world, run_id, "E1")
    assert net == D(376035)
    assert world["db"].execute("SELECT deducted_payslip_id FROM payroll.advances WHERE id = %s", (advance_id,)).fetchone()[0] == payslip_id


def test_a_draft_rule_set_can_be_calculated_and_the_payslip_says_so(world):
    world["db"].execute("UPDATE payroll.rule_sets SET status = 'draft', confirmed_by = NULL, confirmed_at = NULL WHERE id = %s", (world["rule_set_id"],))
    run_id = _regular(world)
    assert isinstance(_calculate(world, run_id), Ok)
    assert _payslip(world, run_id, "E1")[5] == "draft"


def test_what_the_net_cannot_cover_is_carried_to_a_later_run_once_approved(world):
    _approved_advance(world, "E3", 120000)
    september = _regular(world)
    _calculate(world, september)
    payslip_id, _, net, deductions, warnings, *_ = _payslip(world, september, "E3")
    assert (net, deductions, warnings) == (D(0), D(93000), ["NET_NEGATIVE"])
    carry = world["db"].execute("SELECT id, component_code, amount, source_kind FROM payroll.carry_forwards WHERE source_payslip_id = %s", (payslip_id,)).fetchone()
    assert carry[1:] == ("ADVANCE", D(27000), "advance")

    october = _regular(world, period=OCT)
    _calculate(world, october)
    assert _payslip(world, october, "E3")[3] == D(0)  # September is not approved yet: nothing is owed

    world["db"].execute("UPDATE payroll.runs SET status = 'approved', approved_by = 'someone', approved_at = NOW() WHERE id = %s", (september,))
    _calculate(world, october)
    october_payslip, _, _, deductions, *_ = _payslip(world, october, "E3")
    assert deductions == D(27000)
    assert world["db"].execute("SELECT consumed_by_payslip_id FROM payroll.carry_forwards WHERE id = %s", (carry[0],)).fetchone()[0] == october_payslip


def test_an_off_cycle_run_pays_only_its_typed_inputs(world):
    run_id = world["runs"].create_run(tenant_id=TENANT, actor_id=world["actor"], period=SEPT, run_type="off_cycle", employee_ids=["E1"]).value["id"]
    world["inputs"].add_run_input(tenant_id=TENANT, actor_id=world["actor"], run_id=run_id, employee_id="E1", component_code="BONUS", amount=D(25000))
    assert isinstance(_calculate(world, run_id), Ok)
    rows = world["db"].execute("SELECT employee_id, gross, net FROM payroll.payslips WHERE run_id = %s", (run_id,)).fetchall()
    assert rows == [("E1", D(25000), D(23250))]


def test_an_approved_run_is_not_recalculated(world):
    run_id = _regular(world)
    _calculate(world, run_id)
    world["db"].execute("UPDATE payroll.runs SET status = 'approved' WHERE id = %s", (run_id,))
    assert _calculate(world, run_id).code == "RUN_LOCKED"
