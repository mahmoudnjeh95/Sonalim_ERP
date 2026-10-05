"""Payouts from an approved run: one batch per method and bank/operator, files, cash sheet, paid."""
from __future__ import annotations

import datetime
from decimal import Decimal

import pytest

from core.domain.result import Err, Ok
from modules.payroll.api.payout_service import PayoutService
from modules.payroll.api.run_service import RunService
from modules.payroll.api.testing_support import (
    FakePresence, FakeSnapshots, approved_run, make_user, set_country, snapshot, store_rule_set,
)

TENANT = "payroll-payouts-test"
SEPT = datetime.date(2031, 9, 1)
D = Decimal


def _methods(*items):
    return [dict(zip(("method", "bank_name", "account_no", "mobile_operator", "mobile_number", "share_percent", "is_primary"), item)) for item in items]


EMPLOYEES = [
    snapshot("E1", employee_no="M-001", full_name="Awa Traoré"),
    snapshot("E2", employee_no="M-002", full_name="Moussa Keita", payment_methods=_methods(
        ("bank", "Ecobank", "EC-2", None, None, D(60), True), ("mobile_money", None, None, "Orange Money", "+22370000002", D(40), False))),
    snapshot("E4", employee_no="M-004", full_name="Fanta Sidibé", payment_methods=_methods(("cash", None, None, None, None, D(100), True))),
]
SUMMARIES = {key: {"scheduled_days": 22, "worked_days": 22} for key in ("E1", "E2", "E4", "E5")}


@pytest.fixture
def world(db):
    calculator, approver = make_user(db, TENANT), make_user(db, TENANT)
    set_country(db, tenant_id=TENANT, actor_id=calculator)
    store_rule_set(db, tenant_id=TENANT, actor_id=calculator, valid_from=datetime.date(2031, 1, 1))
    return {"db": db, "a": calculator, "b": approver, "payouts": PayoutService(db)}


def _approved(world, employees=EMPLOYEES):
    snapshots, presence = FakeSnapshots(employees), FakePresence(SUMMARIES)
    run_id = approved_run(world["db"], tenant_id=TENANT, calculator=world["a"], approver=world["b"], period=SEPT,
                          snapshots=snapshots, presence=presence)
    return run_id, RunService(world["db"], snapshots=snapshots, presence=presence)


def _net(world, run_id, employee_id):
    return world["db"].execute("SELECT net FROM payroll.payslips WHERE run_id = %s AND employee_id = %s", (run_id, employee_id)).fetchone()[0]


def test_payouts_wait_for_an_approved_run(world):
    snapshots, presence = FakeSnapshots(EMPLOYEES), FakePresence(SUMMARIES)
    runs = RunService(world["db"], snapshots=snapshots, presence=presence)
    run_id = runs.create_run(tenant_id=TENANT, actor_id=world["a"], period=SEPT, run_type="regular").value["id"]
    runs.calculate(tenant_id=TENANT, actor_id=world["a"], run_id=run_id)
    assert world["payouts"].generate(tenant_id=TENANT, actor_id=world["a"], run_id=run_id).code == "RUN_NOT_APPROVED"


def test_one_batch_per_method_and_bank_or_operator_adding_up_to_the_nets(world):
    run_id, _ = _approved(world)
    batches = world["payouts"].generate(tenant_id=TENANT, actor_id=world["a"], run_id=run_id).value
    assert {(batch["method"], batch["group_key"]) for batch in batches} == {
        ("bank", "BDM"), ("bank", "ECOBANK"), ("mobile_money", "ORANGE MONEY"), ("cash", "CASH")}
    total_net = sum(_net(world, run_id, employee) for employee in ("E1", "E2", "E4"))
    assert sum(batch["total"] for batch in batches) == total_net
    mobile = next(batch for batch in batches if batch["method"] == "mobile_money")
    assert mobile["total"] == int(_net(world, run_id, "E2") * 40 // 100)


def test_the_bank_file_needs_its_template_and_follows_it(world):
    run_id, _ = _approved(world)
    batches = world["payouts"].generate(tenant_id=TENANT, actor_id=world["a"], run_id=run_id).value
    bdm = next(batch for batch in batches if batch["group_key"] == "BDM")
    missing = world["payouts"].batch_file(tenant_id=TENANT, batch_id=bdm["id"])
    assert isinstance(missing, Err) and missing.code == "TEMPLATE_MISSING" and "BDM" in missing.message_fr
    world["payouts"].create_template(tenant_id=TENANT, actor_id=world["a"], values={
        "bank_name": "bdm", "columns": [{"header": "Compte", "field": "account_no"}, {"header": "Montant", "field": "amount"}]})
    file_name, text = world["payouts"].batch_file(tenant_id=TENANT, batch_id=bdm["id"]).value
    assert file_name == "paie-2031-09-bank-bdm.csv"
    assert text.splitlines() == ["Compte;Montant", f"ML-M-001;{int(_net(world, run_id, 'E1'))}"]


def test_mobile_money_has_its_file_and_cash_its_sheet(world):
    run_id, _ = _approved(world)
    batches = {batch["method"]: batch for batch in world["payouts"].generate(tenant_id=TENANT, actor_id=world["a"], run_id=run_id).value}
    _, text = world["payouts"].batch_file(tenant_id=TENANT, batch_id=batches["mobile_money"]["id"]).value
    assert text.startswith("operator;number;name;amount\r\nOrange Money;+22370000002;Moussa Keita;")
    assert world["payouts"].batch_file(tenant_id=TENANT, batch_id=batches["cash"]["id"]).code == "PAYOUT_INVALID"
    sheet = world["payouts"].cash_sheet(tenant_id=TENANT, batch_id=batches["cash"]["id"]).value
    line = sheet["lines"][0]
    assert line["full_name"] == "Fanta Sidibé"
    assert sum(int(value) * count for value, count in line["counts"].items()) + line["remainder"] == line["amount"]
    assert sheet["totals"]["amount"] == line["amount"]


def test_a_run_is_paid_once_every_batch_is_confirmed(world):
    run_id, runs = _approved(world)
    batches = world["payouts"].generate(tenant_id=TENANT, actor_id=world["a"], run_id=run_id).value
    assert runs.mark_paid(tenant_id=TENANT, actor_id=world["a"], run_id=run_id).code == "PAYOUT_INCOMPLETE"
    for batch in batches:
        assert isinstance(world["payouts"].confirm_batch(tenant_id=TENANT, actor_id=world["a"], batch_id=batch["id"]), Ok)
    paid = runs.mark_paid(tenant_id=TENANT, actor_id=world["a"], run_id=run_id)
    assert isinstance(paid, Ok) and paid.value["status"] == "paid"
    envelope = world["db"].execute("SELECT payload FROM events.outbox WHERE event_type = 'payroll.run.paid' AND payload->'payload'->>'run_id' = %s",
                                   (run_id,)).fetchone()[0]
    assert envelope["payload"] == {"run_id": run_id, "period": "2031-09-01"}


def test_confirmed_payouts_are_not_regenerated(world):
    run_id, _ = _approved(world)
    first = world["payouts"].generate(tenant_id=TENANT, actor_id=world["a"], run_id=run_id).value[0]
    world["payouts"].confirm_batch(tenant_id=TENANT, actor_id=world["a"], batch_id=first["id"])
    assert world["payouts"].generate(tenant_id=TENANT, actor_id=world["a"], run_id=run_id).code == "PAYOUT_CONFIRMED"


def test_a_bad_split_names_the_employee(world):
    broken = snapshot("E5", employee_no="M-005", full_name="Kadiatou Sanogo",
                      payment_methods=_methods(("bank", "BDM", "ML-5", None, None, D(50), True)))
    run_id, _ = _approved(world, employees=[EMPLOYEES[0], broken])
    refused = world["payouts"].generate(tenant_id=TENANT, actor_id=world["a"], run_id=run_id)
    assert isinstance(refused, Err) and refused.code == "PAYOUT_SPLIT_INVALID" and "Kadiatou Sanogo" in refused.message_fr
