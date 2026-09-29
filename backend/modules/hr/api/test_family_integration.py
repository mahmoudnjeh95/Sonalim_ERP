"""Dependants and payment arrangements against a real database (rolled back after each test)."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from ulid import ULID

from core.domain.result import Err, Ok
from modules.hr.api.dependant_service import DependantService
from modules.hr.api.payment_method_service import PaymentMethodService
from modules.hr.api.service import EmployeeService
from modules.hr.domain.dependant import Dependant
from modules.hr.domain.employee import EmployeeFile
from modules.hr.domain.payment import PaymentMethod

TENANT = "hr-family-test"


@pytest.fixture
def world(db):
    actor = str(ULID())
    db.execute(
        "INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')",
        (actor, TENANT, f"{actor}@test.local"),
    )
    employee = EmployeeService(db).create_employee(
        tenant_id=TENANT, actor_id=actor, employee=EmployeeFile(employee_no="F-001", first_name="Moussa", last_name="Keïta", hire_date=date(2015, 1, 5))
    ).value
    return SimpleNamespace(actor=actor, employee_id=employee["id"])


def bank(share: str = "100", primary: bool = True) -> PaymentMethod:
    return PaymentMethod(method="bank", share_percent=Decimal(share), is_primary=primary, bank_name="BDM-SA", account_no="ML-1")


def mobile(share: str = "100", primary: bool = False) -> PaymentMethod:
    return PaymentMethod(method="mobile_money", share_percent=Decimal(share), is_primary=primary, mobile_operator="orange_money", mobile_number="76 00 00 00")


def test_dependants_list_whether_they_count_for_tax_today(db, world):
    service = DependantService(db)
    service.create_dependant(
        tenant_id=TENANT, actor_id=world.actor, employee_id=world.employee_id,
        dependant=Dependant(kind="spouse", name="Mariam", valid_from=date(2015, 6, 1), dependent_for_tax=True),
    )
    service.create_dependant(
        tenant_id=TENANT, actor_id=world.actor, employee_id=world.employee_id,
        dependant=Dependant(kind="child", name="Issa", valid_from=date(2019, 2, 1), dependent_for_tax=True, valid_to=date(2020, 1, 1)),
    )
    listed = service.list_dependants(tenant_id=TENANT, employee_id=world.employee_id, today=date(2026, 9, 25))
    assert [(d["name"], d["counts_for_tax_today"]) for d in listed] == [("Mariam", True), ("Issa", False)]


def test_a_dependant_edit_is_validated_and_audited(db, world):
    service = DependantService(db)
    created = service.create_dependant(
        tenant_id=TENANT, actor_id=world.actor, employee_id=world.employee_id,
        dependant=Dependant(kind="child", name="Issa", valid_from=date(2019, 2, 1), dependent_for_tax=True),
    ).value
    refused = service.update_dependant(tenant_id=TENANT, actor_id=world.actor, dependant_id=created["id"], changes={"valid_to": date(2000, 1, 1)})
    assert isinstance(refused, Err) and refused.code == "INVALID_DATES"
    edited = service.update_dependant(tenant_id=TENANT, actor_id=world.actor, dependant_id=created["id"], changes={"dependent_for_tax": False})
    assert edited.value["dependent_for_tax"] is False
    actions = sorted(row[0] for row in db.execute("SELECT action FROM core.audit_log WHERE entity_id = %s", (created["id"],)).fetchall())
    assert actions == ["dependant.created", "dependant.updated"]


def test_a_dependant_of_an_unknown_employee_is_refused(db, world):
    refused = DependantService(db).create_dependant(
        tenant_id=TENANT, actor_id=world.actor, employee_id="nobody", dependant=Dependant(kind="child", name="Issa", valid_from=date(2019, 2, 1))
    )
    assert isinstance(refused, Err) and refused.code == "NOT_FOUND"


def test_an_arrangement_is_replaced_as_a_whole(db, world):
    service = PaymentMethodService(db)
    assert isinstance(service.replace_set(tenant_id=TENANT, actor_id=world.actor, employee_id=world.employee_id, valid_from=date(2025, 1, 1), methods=[bank()]), Ok)
    replaced = service.replace_set(
        tenant_id=TENANT, actor_id=world.actor, employee_id=world.employee_id, valid_from=date(2025, 1, 1), methods=[bank("60"), mobile("40")]
    )
    [only] = replaced.value
    assert [(m["method"], m["share_percent"], m["is_primary"]) for m in only["methods"]] == [
        ("bank", Decimal("60.00"), True),
        ("mobile_money", Decimal("40.00"), False),
    ]


def test_a_later_arrangement_takes_over_on_its_date(db, world):
    service = PaymentMethodService(db)
    service.replace_set(tenant_id=TENANT, actor_id=world.actor, employee_id=world.employee_id, valid_from=date(2025, 1, 1), methods=[bank()])
    service.replace_set(tenant_id=TENANT, actor_id=world.actor, employee_id=world.employee_id, valid_from=date(2026, 10, 1), methods=[mobile(primary=True)])
    sets = service.list_sets(tenant_id=TENANT, employee_id=world.employee_id, today=date(2026, 9, 25))
    assert [(s["valid_from"], s["in_force"]) for s in sets] == [("2026-10-01", False), ("2025-01-01", True)]


def test_an_invalid_split_writes_nothing(db, world):
    service = PaymentMethodService(db)
    refused = service.replace_set(
        tenant_id=TENANT, actor_id=world.actor, employee_id=world.employee_id, valid_from=date(2025, 1, 1), methods=[bank("70"), mobile("20")]
    )
    assert isinstance(refused, Err) and refused.code == "PAYOUT_SPLIT_INVALID"
    assert service.list_sets(tenant_id=TENANT, employee_id=world.employee_id) == []


def test_an_empty_list_removes_the_arrangement_and_the_audit_keeps_no_account_number(db, world):
    service = PaymentMethodService(db)
    service.replace_set(tenant_id=TENANT, actor_id=world.actor, employee_id=world.employee_id, valid_from=date(2025, 1, 1), methods=[bank()])
    assert service.replace_set(tenant_id=TENANT, actor_id=world.actor, employee_id=world.employee_id, valid_from=date(2025, 1, 1), methods=[]).value == []
    again = service.replace_set(tenant_id=TENANT, actor_id=world.actor, employee_id=world.employee_id, valid_from=date(2025, 1, 1), methods=[])
    assert isinstance(again, Err) and again.code == "NOT_FOUND"
    payloads = [row[0] for row in db.execute("SELECT payload FROM core.audit_log WHERE entity_id = %s", (world.employee_id,)).fetchall()]
    assert all("ML-1" not in str(payload) for payload in payloads)
