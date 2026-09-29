"""Declarations are built from approved or paid payslips only."""
from __future__ import annotations

import datetime

import pytest

from core.domain.result import Err
from modules.payroll.api.declaration_service import DeclarationService
from modules.payroll.api.run_service import RunService
from modules.payroll.api.testing_support import (
    FakePresence, FakeSnapshots, approved_run, make_user, set_country, snapshot, store_rule_set,
)
from modules.payroll.domain.declarations import to_csv

TENANT = "payroll-declarations-test"
SEPT, OCT = datetime.date(2031, 9, 1), datetime.date(2031, 10, 1)
EMPLOYEES = [snapshot("E1", employee_no="M-001", full_name="Awa Traoré", hire_date=datetime.date(2020, 1, 1)),
             snapshot("E2", employee_no="M-002", full_name="Moussa Keita", hire_date=datetime.date(2020, 1, 1))]
SUMMARIES = {"E1": {"scheduled_days": 22, "worked_days": 22}, "E2": {"scheduled_days": 22, "worked_days": 22}}


@pytest.fixture
def world(db):
    a, b = make_user(db, TENANT), make_user(db, TENANT)
    set_country(db, tenant_id=TENANT, actor_id=a)
    store_rule_set(db, tenant_id=TENANT, actor_id=a, valid_from=datetime.date(2031, 1, 1))
    snapshots, presence = FakeSnapshots(EMPLOYEES), FakePresence(SUMMARIES)
    september = approved_run(db, tenant_id=TENANT, calculator=a, approver=b, period=SEPT, snapshots=snapshots, presence=presence)
    runs = RunService(db, snapshots=snapshots, presence=presence)
    october = runs.create_run(tenant_id=TENANT, actor_id=a, period=OCT, run_type="regular").value["id"]
    runs.calculate(tenant_id=TENANT, actor_id=a, run_id=october)  # calculated, not approved: not declared
    return {"db": db, "september": september, "service": DeclarationService(db)}


def test_the_codes_of_the_month_come_from_the_rule_set_lines(world):
    assert world["service"].codes(tenant_id=TENANT, period=SEPT) == ["EMPLOYER_TAXES", "HEALTH", "SOCIAL", "TAX"]
    assert world["service"].codes(tenant_id=TENANT, period=OCT) == []


def test_a_contribution_declaration_lists_each_employee_with_base_and_shares(world):
    declaration = world["service"].declaration(tenant_id=TENANT, period=SEPT, code="SOCIAL").value
    assert declaration.columns == ("employee_no", "full_name", "identifier", "base", "PENSION_employee", "PENSION_employer", "total")
    assert [row["employee_no"] for row in declaration.rows] == ["M-001", "M-002"]
    first = declaration.rows[0]
    assert first["total"] == first["PENSION_employee"] + first["PENSION_employer"]


def test_an_unknown_code_is_not_found(world):
    refused = world["service"].declaration(tenant_id=TENANT, period=SEPT, code="CNSS")
    assert isinstance(refused, Err) and refused.code == "NOT_FOUND" and refused.message_fr


def test_a_reversed_run_is_not_declared(world):
    world["db"].execute("UPDATE payroll.runs SET status = 'reversed' WHERE id = %s", (world["september"],))
    assert world["service"].codes(tenant_id=TENANT, period=SEPT) == []


def test_the_annual_recap_counts_the_approved_months(world):
    recap = world["service"].annual(tenant_id=TENANT, year=2031)
    assert [(row["employee_no"], row["months"]) for row in recap.rows] == [("M-001", 1), ("M-002", 1)]
    assert to_csv(recap).splitlines()[0] == "employee_no;full_name;months;gross;employee_contrib;employer_contrib;its;net"
