"""Approval and reversal: four-eyes, confirmed rules, closed presence, events, release of deductions."""
from __future__ import annotations

import datetime
from decimal import Decimal

import pytest

from core.domain.result import Err, Ok
from modules.payroll.api.input_service import InputService
from modules.payroll.api.rule_set_service import RuleSetService
from modules.payroll.api.run_service import RunService
from modules.payroll.api.testing_support import (
    FakePresence, FakeSnapshots, make_user, set_country, snapshot, store_rule_set,
)

TENANT = "payroll-approval-test"
SEPT = datetime.date(2031, 9, 1)
OCT = datetime.date(2031, 10, 1)
D = Decimal
EMPLOYEES = [snapshot("E1", employee_no="M-001", full_name="Awa Traoré"),
             snapshot("E3", employee_no="M-003", full_name="Oumar Diarra", base_salary=D(100000), hire_date=datetime.date(2031, 1, 1))]
SUMMARIES = {"E1": {"scheduled_days": 22, "worked_days": 22}, "E3": {"scheduled_days": 22, "worked_days": 22}}


@pytest.fixture
def world(db):
    calculator, approver = make_user(db, TENANT), make_user(db, TENANT)
    set_country(db, tenant_id=TENANT, actor_id=calculator)
    rule_set_id = store_rule_set(db, tenant_id=TENANT, actor_id=calculator, valid_from=datetime.date(2031, 1, 1))
    snapshots, presence = FakeSnapshots(EMPLOYEES), FakePresence(SUMMARIES)
    return {"db": db, "a": calculator, "b": approver, "rule_set_id": rule_set_id, "presence": presence,
            "runs": RunService(db, snapshots=snapshots, presence=presence), "inputs": InputService(db, snapshots=snapshots)}


def _calculated(world, period=SEPT):
    run_id = world["runs"].create_run(tenant_id=TENANT, actor_id=world["a"], period=period, run_type="regular").value["id"]
    assert isinstance(world["runs"].calculate(tenant_id=TENANT, actor_id=world["a"], run_id=run_id), Ok)
    return run_id


def _approve(world, run_id, actor="b"):
    return world["runs"].approve(tenant_id=TENANT, actor_id=world[actor], run_id=run_id)


def _event(world, event_type, run_id):
    row = world["db"].execute(
        "SELECT payload FROM events.outbox WHERE event_type = %s AND payload->'payload'->>'run_id' = %s", (event_type, run_id)).fetchone()
    return None if row is None else row[0]


def _draft_rules(world):
    world["db"].execute("UPDATE payroll.rule_sets SET status = 'draft', confirmed_by = NULL, confirmed_at = NULL WHERE id = %s", (world["rule_set_id"],))


def test_the_person_who_calculated_cannot_approve(world):
    refused = _approve(world, _calculated(world), actor="a")
    assert isinstance(refused, Err) and refused.code == "SAME_USER_APPROVAL" and refused.message_fr


def test_a_draft_run_is_calculated_before_approval(world):
    run_id = world["runs"].create_run(tenant_id=TENANT, actor_id=world["a"], period=SEPT, run_type="regular").value["id"]
    assert _approve(world, run_id).code == "RUN_NOT_CALCULATED"


def test_a_draft_rule_set_blocks_approval(world):
    _draft_rules(world)
    refused = _approve(world, _calculated(world))
    assert isinstance(refused, Err) and refused.code == "RULESET_NOT_CONFIRMED"


def test_a_rule_set_confirmed_after_calculation_needs_a_recalculation(world):
    _draft_rules(world)
    run_id = _calculated(world)
    RuleSetService(world["db"]).confirm_rule_set(tenant_id=TENANT, actor_id=world["b"], rule_set_id=world["rule_set_id"])
    refused = _approve(world, run_id)
    assert isinstance(refused, Err) and refused.code == "RULESET_NOT_CONFIRMED" and "recalculate" in refused.message
    world["runs"].calculate(tenant_id=TENANT, actor_id=world["a"], run_id=run_id)
    assert isinstance(_approve(world, run_id), Ok)


def test_a_newer_rule_set_in_force_needs_a_recalculation(world):
    run_id = _calculated(world)
    store_rule_set(world["db"], tenant_id=TENANT, actor_id=world["a"], valid_from=SEPT, name="Newer")
    assert _approve(world, run_id).code == "RULESET_NOT_CONFIRMED"


def test_approval_is_refused_when_presence_was_reopened(world):
    run_id = _calculated(world)
    world["presence"].closed = False
    assert _approve(world, run_id).code == "PRESENCE_NOT_CLOSED"


def test_approval_locks_the_run_publishes_the_event_and_is_audited(world):
    run_id = _calculated(world)
    approved = _approve(world, run_id)
    assert isinstance(approved, Ok) and approved.value["status"] == "approved" and approved.value["approved_by"] == world["b"]
    envelope = _event(world, "payroll.run.approved", run_id)
    assert envelope["payload"] == {"run_id": run_id, "period": "2031-09-01", "run_type": "regular"}
    assert envelope["producer"] == "payroll" and envelope["correlation_id"] == run_id
    assert world["db"].execute("SELECT count(*) FROM core.audit_log WHERE entity_id = %s AND action = 'payroll_run.approved'", (run_id,)).fetchone()[0] == 1
    assert world["runs"].calculate(tenant_id=TENANT, actor_id=world["a"], run_id=run_id).code == "RUN_LOCKED"


def test_reversal_needs_a_reason_and_an_approved_run(world):
    run_id = _calculated(world)
    assert world["runs"].reverse(tenant_id=TENANT, actor_id=world["b"], run_id=run_id, reason="Erreur").code == "RUN_NOT_REVERSIBLE"
    _approve(world, run_id)
    assert world["runs"].reverse(tenant_id=TENANT, actor_id=world["b"], run_id=run_id, reason="  ").code == "RUN_INVALID"


def test_reversal_releases_deductions_frees_the_month_and_publishes_the_event(world):
    advance = world["inputs"].create_advance(tenant_id=TENANT, actor_id=world["a"], employee_id="E1", amount=D(50000),
                                             requested_on=SEPT, deduct_period=SEPT).value
    world["inputs"].approve_advance(tenant_id=TENANT, actor_id=world["a"], advance_id=advance["id"])
    run_id = _calculated(world)
    _approve(world, run_id)
    reversed_run = world["runs"].reverse(tenant_id=TENANT, actor_id=world["b"], run_id=run_id, reason="Wrong month")
    assert isinstance(reversed_run, Ok) and reversed_run.value["status"] == "reversed" and reversed_run.value["reversal_reason"] == "Wrong month"
    assert world["db"].execute("SELECT deducted_payslip_id FROM payroll.advances WHERE id = %s", (advance["id"],)).fetchone()[0] is None
    assert _event(world, "payroll.run.reversed", run_id)["payload"] == {"run_id": run_id, "period": "2031-09-01"}
    assert isinstance(world["runs"].create_run(tenant_id=TENANT, actor_id=world["a"], period=SEPT, run_type="regular"), Ok)


def _carry_then_october(world):
    advance = world["inputs"].create_advance(tenant_id=TENANT, actor_id=world["a"], employee_id="E3", amount=D(120000),
                                             requested_on=SEPT, deduct_period=SEPT).value
    world["inputs"].approve_advance(tenant_id=TENANT, actor_id=world["a"], advance_id=advance["id"])
    september = _calculated(world)
    _approve(world, september)
    return september, _calculated(world, period=OCT)


def test_a_run_whose_carry_a_later_approved_run_took_cannot_be_reversed(world):
    september, october = _carry_then_october(world)
    _approve(world, october)
    refused = world["runs"].reverse(tenant_id=TENANT, actor_id=world["b"], run_id=september, reason="x")
    assert isinstance(refused, Err) and refused.code == "RUN_LOCKED" and "10/2031" in refused.message_fr


def test_reversing_sends_a_later_calculated_run_that_took_its_carry_back_to_draft(world):
    september, october = _carry_then_october(world)
    assert isinstance(world["runs"].reverse(tenant_id=TENANT, actor_id=world["b"], run_id=september, reason="x"), Ok)
    assert world["runs"].get_run(tenant_id=TENANT, run_id=october)["status"] == "draft"
    assert world["db"].execute("SELECT count(*) FROM payroll.carry_forwards WHERE tenant_id = %s", (TENANT,)).fetchone()[0] == 0
