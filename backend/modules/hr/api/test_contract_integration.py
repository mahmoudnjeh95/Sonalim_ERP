"""Contracts against a real database (rolled back after each test)."""
from __future__ import annotations

import datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from ulid import ULID

from core.domain.result import Err, Ok
from modules.hr.api.contract_service import ContractService
from modules.hr.api.service import EmployeeService
from modules.hr.domain.contract import ContractComponent, ContractTerms
from modules.hr.domain.employee import EmployeeFile

TENANT = "hr-contract-test"
D = datetime.date


@pytest.fixture
def world(db):
    actor = str(ULID())
    db.execute(
        "INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')",
        (actor, TENANT, f"{actor}@test.local"),
    )
    employee = EmployeeService(db).create_employee(
        tenant_id=TENANT, actor_id=actor,
        employee=EmployeeFile(employee_no="C-001", first_name="Awa", last_name="Traoré", hire_date=D(2024, 1, 1)),
    ).value
    return SimpleNamespace(actor=actor, employee_id=employee["id"])


def _terms(world, **overrides) -> ContractTerms:
    return ContractTerms(
        **{"employee_id": world.employee_id, "contract_type": "cdi", "start_date": D(2024, 1, 1), "base_salary": Decimal("150000"), **overrides}
    )


def _create(db, world, **overrides):
    return ContractService(db).create_contract(tenant_id=TENANT, actor_id=world.actor, terms=_terms(world, **overrides))


def test_a_created_contract_reads_back_in_xof_with_its_components(db, world):
    created = _create(db, world, components=(ContractComponent(component_code="TRANSPORT", amount=Decimal("15000")),))
    assert isinstance(created, Ok)
    contract = created.value
    assert (contract["contract_type"], contract["base_salary"], contract["currency"], contract["weekly_hours"], contract["pay_frequency"]) == (
        "cdi", Decimal("150000"), "XOF", Decimal("40.00"), "monthly",
    )
    assert contract["components"] == [{"component_code": "TRANSPORT", "amount": Decimal("15000"), "rate": None}]
    # The legacy payroll screen still reads salary until phase 3 retires it.
    assert db.execute("SELECT salary FROM hr.contracts WHERE id = %s", (contract["id"],)).fetchone()[0] == Decimal("150000")


def test_a_second_signed_contract_on_the_same_days_is_refused_but_a_draft_is_not(db, world):
    assert isinstance(_create(db, world), Ok)
    refused = _create(db, world, start_date=D(2025, 1, 1))
    assert isinstance(refused, Err) and refused.code == "CONTRACT_OVERLAP" and "2024-01-01" in refused.message
    assert isinstance(_create(db, world, start_date=D(2025, 1, 1), status="draft"), Ok)


def test_a_new_contract_is_draft_or_active_and_amends_nothing(db, world):
    assert _create(db, world, status="expired").code == "INVALID_STATUS"
    assert _create(db, world, end_date=D(2024, 6, 30), end_reason="resignation").code == "INVALID_CONTRACT"


def test_activating_a_draft_checks_overlap(db, world):
    service = ContractService(db)
    assert isinstance(_create(db, world), Ok)
    draft = _create(db, world, start_date=D(2025, 1, 1), status="draft").value
    refused = service.activate_contract(tenant_id=TENANT, actor_id=world.actor, contract_id=draft["id"])
    assert isinstance(refused, Err) and refused.code == "CONTRACT_OVERLAP"


def test_activating_a_draft_that_fits_signs_it(db, world):
    draft = _create(db, world, status="draft").value
    activated = ContractService(db).activate_contract(tenant_id=TENANT, actor_id=world.actor, contract_id=draft["id"])
    assert activated.value["status"] == "active"
    again = ContractService(db).activate_contract(tenant_id=TENANT, actor_id=world.actor, contract_id=draft["id"])
    assert isinstance(again, Err) and again.code == "INVALID_TRANSITION"


def test_ending_early_terminates_and_cannot_run_past_the_agreed_end(db, world):
    service = ContractService(db)
    cdd = _create(db, world, contract_type="cdd", end_date=D(2024, 12, 31)).value
    late = service.end_contract(tenant_id=TENANT, actor_id=world.actor, contract_id=cdd["id"], end_date=D(2025, 1, 31), end_reason="resignation")
    assert isinstance(late, Err) and late.code == "INVALID_DATES"
    ended = service.end_contract(tenant_id=TENANT, actor_id=world.actor, contract_id=cdd["id"], end_date=D(2024, 6, 30), end_reason="resignation")
    assert (ended.value["status"], ended.value["end_date"], ended.value["end_reason"]) == ("terminated", "2024-06-30", "resignation")


def test_a_contract_that_reaches_its_term_expires(db, world):
    cdd = _create(db, world, contract_type="cdd", end_date=D(2024, 12, 31)).value
    ended = ContractService(db).end_contract(
        tenant_id=TENANT, actor_id=world.actor, contract_id=cdd["id"], end_date=D(2024, 12, 31), end_reason="term_reached"
    )
    assert ended.value["status"] == "expired"


def test_amended_is_not_a_reason_to_end_a_contract_by_hand(db, world):
    contract = _create(db, world).value
    refused = ContractService(db).end_contract(
        tenant_id=TENANT, actor_id=world.actor, contract_id=contract["id"], end_date=D(2024, 6, 30), end_reason="amended"
    )
    assert isinstance(refused, Err) and refused.code == "INVALID_END_REASON"


def test_an_amendment_closes_the_old_terms_and_carries_them_on(db, world):
    service = ContractService(db)
    old = _create(db, world, trial_end_date=D(2024, 3, 31), components=(ContractComponent(component_code="TRANSPORT", amount=Decimal("15000")),)).value
    new = service.amend_contract(
        tenant_id=TENANT, actor_id=world.actor, contract_id=old["id"], effective_date=D(2025, 1, 1), changes={"base_salary": Decimal("175000")}
    ).value
    assert (new["start_date"], new["base_salary"], new["amends_contract_id"], new["trial_end_date"], new["status"]) == (
        "2025-01-01", Decimal("175000"), old["id"], None, "active",
    )
    assert new["components"] == [{"component_code": "TRANSPORT", "amount": Decimal("15000"), "rate": None}]
    closed = service.get_contract(tenant_id=TENANT, contract_id=old["id"])
    assert (closed["end_date"], closed["end_reason"], closed["status"]) == ("2024-12-31", "amended", "expired")


def test_an_amendment_takes_effect_after_the_start_and_only_on_an_active_contract(db, world):
    service = ContractService(db)
    contract = _create(db, world).value
    same_day = service.amend_contract(tenant_id=TENANT, actor_id=world.actor, contract_id=contract["id"], effective_date=D(2024, 1, 1), changes={})
    assert isinstance(same_day, Err) and same_day.code == "INVALID_DATES"
    draft = _create(db, world, start_date=D(2030, 1, 1), status="draft").value
    not_signed = service.amend_contract(tenant_id=TENANT, actor_id=world.actor, contract_id=draft["id"], effective_date=D(2030, 6, 1), changes={})
    assert isinstance(not_signed, Err) and not_signed.code == "INVALID_TRANSITION"


def test_amending_a_non_xof_contract_is_refused_and_inserts_nothing(db, world):
    # Every new contract is XOF; a non-XOF row is a legacy one the old screen created. Simulate
    # it directly, since create_contract itself always writes 'XOF'.
    contract = _create(db, world, base_salary=Decimal("1800")).value
    db.execute("UPDATE hr.contracts SET currency = 'USD' WHERE id = %s", (contract["id"],))
    before = db.execute("SELECT COUNT(*) FROM hr.contracts WHERE employee_id = %s", (world.employee_id,)).fetchone()[0]
    refused = ContractService(db).amend_contract(
        tenant_id=TENANT, actor_id=world.actor, contract_id=contract["id"], effective_date=D(2024, 6, 1), changes={"base_salary": Decimal("2000")}
    )
    assert isinstance(refused, Err) and refused.code == "CONTRACT_NOT_XOF"
    assert refused.message_fr
    after = db.execute("SELECT COUNT(*) FROM hr.contracts WHERE employee_id = %s", (world.employee_id,)).fetchone()[0]
    assert after == before
    unchanged = db.execute("SELECT currency, salary, status FROM hr.contracts WHERE id = %s", (contract["id"],)).fetchone()
    assert unchanged == ("USD", Decimal("1800"), "active")


def test_an_edit_can_replace_components_and_audits_pay_by_name_only(db, world):
    contract = _create(db, world).value
    edited = ContractService(db).update_contract(
        tenant_id=TENANT, actor_id=world.actor, contract_id=contract["id"],
        changes={"base_salary": Decimal("160000"), "components": [{"component_code": "HOUSING", "amount": Decimal("25000")}]},
    ).value
    assert edited["components"] == [{"component_code": "HOUSING", "amount": Decimal("25000"), "rate": None}]
    assert db.execute("SELECT salary FROM hr.contracts WHERE id = %s", (contract["id"],)).fetchone()[0] == Decimal("160000")
    payload = db.execute(
        "SELECT payload FROM core.audit_log WHERE entity_id = %s AND action = 'contract.updated'", (contract["id"],)
    ).fetchone()[0]
    assert payload == {"changed": {}, "sensitive_changed": ["base_salary", "components"]}


def test_the_employee_list_shows_the_contract_in_force_today(db, world):
    _create(db, world, contract_type="cdd", end_date=D(2026, 12, 31))
    [row] = EmployeeService(db).list_employees(TENANT, today=D(2026, 9, 25))
    assert (row["contract_type"], row["contract_end_date"]) == ("cdd", "2026-12-31")
    [later] = EmployeeService(db).list_employees(TENANT, today=D(2027, 1, 1))
    assert later["contract_type"] is None
