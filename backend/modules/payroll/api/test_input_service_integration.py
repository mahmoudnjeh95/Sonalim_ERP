"""Inputs, advances and loans against a real database."""
from __future__ import annotations

import datetime
from decimal import Decimal

import pytest

from core.domain.result import Err, Ok
from modules.payroll.api.input_service import InputService
from modules.payroll.api.testing_support import (
    FakeSnapshots, insert_payslip, insert_run, make_user, set_country, snapshot, store_rule_set,
)

TENANT = "payroll-inputs-test"
SEPT = datetime.date(2031, 9, 1)
OCT = datetime.date(2031, 10, 1)
D = Decimal


@pytest.fixture
def world(db):
    actor = make_user(db, TENANT)
    set_country(db, tenant_id=TENANT, actor_id=actor)
    rule_set_id = store_rule_set(db, tenant_id=TENANT, actor_id=actor, valid_from=datetime.date(2031, 1, 1))
    employees = [snapshot("E1", employee_no="M-001", full_name="Awa Traoré"), snapshot("E2", employee_no="M-002", full_name="Moussa Keita")]
    service = InputService(db, snapshots=FakeSnapshots(employees))
    return {"db": db, "actor": actor, "rule_set_id": rule_set_id, "service": service}


def _run(world, status="draft"):
    return insert_run(world["db"], tenant_id=TENANT, actor_id=world["actor"], period=SEPT, status=status,
                      rule_set_id=None if status == "draft" else world["rule_set_id"])


def test_a_monthly_input_is_stored_with_the_employee_name(world):
    run_id = _run(world)
    added = world["service"].add_run_input(tenant_id=TENANT, actor_id=world["actor"], run_id=run_id, employee_id="E1",
                                           component_code="bonus", amount=D(25000), note="Prime qualité")
    assert isinstance(added, Ok) and added.value["component_code"] == "BONUS" and added.value["full_name"] == "Awa Traoré"
    grouped = world["service"].run_inputs_by_employee(tenant_id=TENANT, run_id=run_id)
    assert [(item.component_code, item.amount, item.source_kind) for item in grouped["E1"]] == [("BONUS", D(25000), "input")]


def test_only_typed_components_can_be_inputs(world):
    run_id = _run(world)
    offered = world["service"].input_components(tenant_id=TENANT, run_id=run_id).value
    assert {item["code"] for item in offered} == {"HOUSING", "TRANSPORT", "MEAL", "BONUS", "CANTEEN"}
    for code in ("BASE", "SENIORITY", "NOPE"):
        refused = world["service"].add_run_input(tenant_id=TENANT, actor_id=world["actor"], run_id=run_id, employee_id="E1", component_code=code, amount=D(1))
        assert isinstance(refused, Err) and refused.code == "INPUT_INVALID", code


def test_an_input_needs_an_amount_or_a_quantity_and_a_contract(world):
    run_id = _run(world)
    service = world["service"]
    assert service.add_run_input(tenant_id=TENANT, actor_id=world["actor"], run_id=run_id, employee_id="E1", component_code="BONUS").code == "INPUT_INVALID"
    assert service.add_run_input(tenant_id=TENANT, actor_id=world["actor"], run_id=run_id, employee_id="E9", component_code="BONUS", amount=D(1)).code == "NOT_FOUND"


def test_changing_an_input_sends_a_calculated_run_back_to_draft(world):
    run_id = _run(world, status="calculated")
    insert_payslip(world["db"], tenant_id=TENANT, run_id=run_id, employee_id="E1", rule_set_id=world["rule_set_id"])
    world["service"].add_run_input(tenant_id=TENANT, actor_id=world["actor"], run_id=run_id, employee_id="E1", component_code="BONUS", amount=D(5000))
    status, payslips = world["db"].execute(
        "SELECT r.status, (SELECT count(*) FROM payroll.payslips WHERE run_id = r.id) FROM payroll.runs r WHERE r.id = %s", (run_id,)).fetchone()
    assert (status, payslips) == ("draft", 0)


def test_an_approved_run_takes_no_more_inputs(world):
    run_id = _run(world, status="approved")
    refused = world["service"].add_run_input(tenant_id=TENANT, actor_id=world["actor"], run_id=run_id, employee_id="E1", component_code="BONUS", amount=D(1))
    assert isinstance(refused, Err) and refused.code == "RUN_LOCKED"


def test_an_advance_is_due_from_its_month_once_approved(world):
    service = world["service"]
    advance = service.create_advance(tenant_id=TENANT, actor_id=world["actor"], employee_id="E1", amount=D(50000),
                                     requested_on=datetime.date(2031, 9, 3), deduct_period=OCT).value
    assert advance["status"] == "requested"
    assert service.due_deductions(tenant_id=TENANT, period=OCT, employee_ids=["E1"], settle_ids=set()) == {}
    assert service.approve_advance(tenant_id=TENANT, actor_id=world["actor"], advance_id=advance["id"]).value["status"] == "approved"
    assert service.due_deductions(tenant_id=TENANT, period=SEPT, employee_ids=["E1"], settle_ids=set()) == {}
    due = service.due_deductions(tenant_id=TENANT, period=OCT, employee_ids=["E1"], settle_ids=set())
    assert [(item.component_code, item.amount, item.source_kind, item.source_id) for item in due["E1"]] == [
        ("ADVANCE", D(50000), "advance", advance["id"])]
    settling = service.due_deductions(tenant_id=TENANT, period=SEPT, employee_ids=["E1"], settle_ids={"E1"})
    assert [item.source_id for item in settling["E1"]] == [advance["id"]]


def test_an_advance_deducted_by_an_approved_run_is_frozen(world):
    service = world["service"]
    advance = service.create_advance(tenant_id=TENANT, actor_id=world["actor"], employee_id="E1", amount=D(50000),
                                     requested_on=datetime.date(2031, 9, 3), deduct_period=SEPT).value
    run_id = _run(world, status="approved")
    payslip_id = insert_payslip(world["db"], tenant_id=TENANT, run_id=run_id, employee_id="E1", rule_set_id=world["rule_set_id"])
    world["db"].execute("UPDATE payroll.advances SET status = 'approved', deducted_payslip_id = %s WHERE id = %s", (payslip_id, advance["id"]))
    assert service.update_advance(tenant_id=TENANT, actor_id=world["actor"], advance_id=advance["id"], changes={"amount": D(1)}).code == "RUN_LOCKED"
    assert service.cancel_advance(tenant_id=TENANT, actor_id=world["actor"], advance_id=advance["id"]).code == "RUN_LOCKED"
    listed = service.list_advances(tenant_id=TENANT)[0]
    assert (listed["deducted_run_id"], listed["deducted_run_status"]) == (run_id, "approved")


def test_a_loan_is_split_into_monthly_instalments(world):
    service = world["service"]
    loan = service.create_loan(tenant_id=TENANT, actor_id=world["actor"], employee_id="E2", principal=D(100000),
                               instalment_count=3, first_period=SEPT).value
    assert [(item["seq"], item["amount"]) for item in loan["instalments"]] == [(1, 33333), (2, 33333), (3, 33334)]
    assert loan["remaining"] == 100000
    due = service.due_deductions(tenant_id=TENANT, period=SEPT, employee_ids=["E2"], settle_ids=set())
    assert [(item.component_code, item.amount) for item in due["E2"]] == [("LOAN", D(33333))]
    settling = service.due_deductions(tenant_id=TENANT, period=SEPT, employee_ids=["E2"], settle_ids={"E2"})
    assert len(settling["E2"]) == 3


def test_a_cancelled_loan_drops_its_open_instalments(world):
    service = world["service"]
    loan = service.create_loan(tenant_id=TENANT, actor_id=world["actor"], employee_id="E2", principal=D(90000), instalment_count=3, first_period=SEPT).value
    cancelled = service.cancel_loan(tenant_id=TENANT, actor_id=world["actor"], loan_id=loan["id"])
    assert isinstance(cancelled, Ok) and cancelled.value["status"] == "cancelled" and cancelled.value["instalments"] == []
    assert service.due_deductions(tenant_id=TENANT, period=SEPT, employee_ids=["E2"], settle_ids=set()) == {}


def test_a_loan_needs_a_franc_per_instalment(world):
    refused = world["service"].create_loan(tenant_id=TENANT, actor_id=world["actor"], employee_id="E2", principal=D(2), instalment_count=3, first_period=SEPT)
    assert isinstance(refused, Err) and refused.code == "INPUT_INVALID" and refused.message_fr
