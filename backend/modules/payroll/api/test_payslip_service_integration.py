"""Payslip reads, print data, certificate, admin edit and month-on-month variance."""
from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from ulid import ULID

from core.domain.result import Err, Ok
from modules.payroll.api.input_service import InputService
from modules.payroll.api.payout_service import PayoutService
from modules.payroll.api.payslip_service import PayslipService
from modules.payroll.api.run_service import RunService
from modules.payroll.api.testing_support import (
    FakePresence, FakeSnapshots, approved_run, make_user, set_country, snapshot, store_rule_set,
)

TENANT = "payroll-payslips-test"
AUG, SEPT = datetime.date(2031, 8, 1), datetime.date(2031, 9, 1)
D = Decimal
# hired long enough ago that August and September fall on the same seniority step
EMPLOYEES = [snapshot("E1", employee_no="M-001", full_name="Awa Traoré", hire_date=datetime.date(2020, 1, 1)),
             snapshot("E2", employee_no="M-002", full_name="Moussa Keita", hire_date=datetime.date(2020, 1, 1))]
SUMMARIES = {"E1": {"scheduled_days": 22, "worked_days": 22}, "E2": {"scheduled_days": 22, "worked_days": 22}}
NEW_BANK = [{"method": "bank", "bank_name": "Ecobank", "account_no": "EC-9", "mobile_operator": None, "mobile_number": None,
             "share_percent": 100, "is_primary": True}]


@pytest.fixture
def world(db):
    a, b = make_user(db, TENANT), make_user(db, TENANT)
    set_country(db, tenant_id=TENANT, actor_id=a)
    store_rule_set(db, tenant_id=TENANT, actor_id=a, valid_from=datetime.date(2031, 1, 1))
    db.execute("INSERT INTO core.companies (id, tenant_id, name) VALUES (%s, %s, 'Sonalim SA')", (str(ULID()), TENANT))
    snapshots, presence = FakeSnapshots(EMPLOYEES), FakePresence(SUMMARIES)
    return {"db": db, "a": a, "b": b, "snapshots": snapshots, "presence": presence, "payslips": PayslipService(db)}


def _approved(world, period=SEPT):
    return approved_run(world["db"], tenant_id=TENANT, calculator=world["a"], approver=world["b"], period=period,
                        snapshots=world["snapshots"], presence=world["presence"])


def _payslip_id(world, run_id, employee_id="E1"):
    return world["db"].execute("SELECT id FROM payroll.payslips WHERE run_id = %s AND employee_id = %s", (run_id, employee_id)).fetchone()[0]


def test_a_payslip_reads_with_its_lines_run_and_company(world):
    run_id = _approved(world)
    payslip = world["payslips"].get_payslip(tenant_id=TENANT, payslip_id=_payslip_id(world, run_id))
    assert (payslip["period"], payslip["run_status"], payslip["full_name"]) == ("2031-09-01", "approved", "Awa Traoré")
    assert payslip["company"]["name"] == "Sonalim SA"
    assert [line["line_no"] for line in payslip["lines"]] == sorted(line["line_no"] for line in payslip["lines"])
    assert payslip["lines"][0]["code"] == "BASE" and payslip["lines"][0]["amount"] == 400000


def test_the_whole_run_prints_in_name_order(world):
    document = world["payslips"].run_print(tenant_id=TENANT, run_id=_approved(world))
    assert [payslip["full_name"] for payslip in document["payslips"]] == ["Awa Traoré", "Moussa Keita"]
    assert all(payslip["lines"] for payslip in document["payslips"])


def test_payment_details_can_be_corrected_until_a_batch_is_confirmed(world):
    run_id = _approved(world)
    payslip_id = _payslip_id(world, run_id)
    payouts = PayoutService(world["db"])
    payouts.generate(tenant_id=TENANT, actor_id=world["a"], run_id=run_id)
    bad = world["payslips"].admin_update_payslip(tenant_id=TENANT, actor_id=world["a"], payslip_id=payslip_id,
                                                 changes={"payment_methods": [{**NEW_BANK[0], "share_percent": 50}]})
    assert isinstance(bad, Err) and bad.code == "PAYOUT_SPLIT_INVALID"
    fixed = world["payslips"].admin_update_payslip(tenant_id=TENANT, actor_id=world["a"], payslip_id=payslip_id,
                                                   changes={"payment_methods": NEW_BANK, "note": "New account from 15 Sept"})
    assert isinstance(fixed, Ok) and fixed.value["snapshot"]["payment_methods"][0]["bank_name"] == "Ecobank"
    assert payouts.list_batches(tenant_id=TENANT, run_id=run_id) == []  # stale batches dropped
    batches = payouts.generate(tenant_id=TENANT, actor_id=world["a"], run_id=run_id).value
    assert "ECOBANK" in {batch["group_key"] for batch in batches}
    payouts.confirm_batch(tenant_id=TENANT, actor_id=world["a"], batch_id=batches[0]["id"])
    frozen = world["payslips"].admin_update_payslip(tenant_id=TENANT, actor_id=world["a"], payslip_id=payslip_id, changes={"payment_methods": NEW_BANK})
    assert isinstance(frozen, Err) and frozen.code == "PAYOUT_CONFIRMED"
    audit = world["db"].execute("SELECT count(*) FROM core.audit_log WHERE entity_id = %s AND action = 'payslip.updated'", (payslip_id,)).fetchone()[0]
    assert audit == 1


def test_a_paid_run_payslip_cannot_be_edited(world):
    run_id = _approved(world)
    world["db"].execute("UPDATE payroll.runs SET status = 'paid' WHERE id = %s", (run_id,))
    refused = world["payslips"].admin_update_payslip(tenant_id=TENANT, actor_id=world["a"], payslip_id=_payslip_id(world, run_id), changes={"note": "x"})
    assert isinstance(refused, Err) and refused.code == "RUN_LOCKED"


def test_only_a_final_settlement_has_a_work_certificate(world):
    run_id = _approved(world)
    refused = world["payslips"].certificate(tenant_id=TENANT, payslip_id=_payslip_id(world, run_id))
    assert isinstance(refused, Err) and refused.code == "NOT_FOUND"
    leaving = snapshot("E9", employee_no="M-009", full_name="Seydou Coulibaly", hire_date=datetime.date(2019, 9, 15),
                       termination_date=datetime.date(2031, 9, 15), termination_reason="resignation")
    runs = RunService(world["db"], snapshots=FakeSnapshots([leaving]), presence=FakePresence({"E9": {"scheduled_days": 10, "worked_days": 10}}))
    off_cycle = runs.create_run(tenant_id=TENANT, actor_id=world["a"], period=SEPT, run_type="off_cycle").value["id"]
    runs.add_final_settlement(tenant_id=TENANT, actor_id=world["a"], run_id=off_cycle, employee_id="E9")
    runs.calculate(tenant_id=TENANT, actor_id=world["a"], run_id=off_cycle)
    certificate = world["payslips"].certificate(tenant_id=TENANT, payslip_id=_payslip_id(world, off_cycle, "E9")).value
    assert (certificate["full_name"], certificate["hire_date"], certificate["termination_date"], certificate["termination_reason"]) == (
        "Seydou Coulibaly", "2019-09-15", "2031-09-15", "resignation")


def test_variance_compares_with_last_months_approved_run(world):
    august = _approved(world, period=AUG)
    runs = RunService(world["db"], snapshots=world["snapshots"], presence=world["presence"])
    september = runs.create_run(tenant_id=TENANT, actor_id=world["a"], period=SEPT, run_type="regular").value["id"]
    InputService(world["db"], snapshots=world["snapshots"]).add_run_input(
        tenant_id=TENANT, actor_id=world["a"], run_id=september, employee_id="E1", component_code="BONUS", amount=D(25000))
    runs.calculate(tenant_id=TENANT, actor_id=world["a"], run_id=september)
    variance = world["payslips"].variance(tenant_id=TENANT, run_id=september)
    assert (variance["previous_run_id"], variance["previous_period"]) == (august, "2031-08-01")
    rows = {row["employee_id"]: row for row in variance["rows"]}
    assert (rows["E1"]["change"], rows["E1"]["delta_gross"]) == ("changed", 25000)
    assert rows["E2"]["change"] == "same" and variance["rows"][0]["employee_id"] == "E1"
