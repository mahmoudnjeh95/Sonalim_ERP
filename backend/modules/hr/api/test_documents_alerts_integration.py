"""Documents, the alert horizons and the expiry alerts against a real database."""
from __future__ import annotations

import datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from ulid import ULID

from core.domain.result import Err
from modules.hr.api.alert_service import HrAlertService
from modules.hr.api.contract_service import ContractService
from modules.hr.api.document_service import DocumentService
from modules.hr.api.service import EmployeeService
from modules.hr.api.settings_service import HrSettingsService
from modules.hr.domain.contract import ContractTerms
from modules.hr.domain.document import EmployeeDocument
from modules.hr.domain.employee import EmployeeFile

TENANT = "hr-alerts-test"
TODAY = datetime.date(2026, 9, 25)
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
        employee=EmployeeFile(employee_no="A-001", first_name="Hawa", last_name="Sangaré", hire_date=D(2024, 1, 1)),
    ).value
    return SimpleNamespace(actor=actor, employee_id=employee["id"])


def _horizons(db, world, contract=30, trial=15, document=30):
    return HrSettingsService(db).save(
        tenant_id=TENANT, actor_id=world.actor,
        contract_expiry_horizon_days=contract, trial_end_horizon_days=trial, document_expiry_horizon_days=document,
    )


def _contract(db, world, **overrides):
    terms = ContractTerms(**{"employee_id": world.employee_id, "contract_type": "cdd", "start_date": D(2026, 1, 1), "base_salary": Decimal("90000"), **overrides})
    return ContractService(db).create_contract(tenant_id=TENANT, actor_id=world.actor, terms=terms).value


def _alerts(db):
    return HrAlertService(db).expiry_alerts(tenant_id=TENANT, today=TODAY)


def test_settings_start_empty_and_nothing_is_listed_without_a_horizon(db, world):
    assert HrSettingsService(db).get(TENANT) == {
        "contract_expiry_horizon_days": None, "trial_end_horizon_days": None, "document_expiry_horizon_days": None,
    }
    _contract(db, world, end_date=D(2026, 10, 1))
    alerts = _alerts(db)
    assert (alerts["contract_expiry_horizon_days"], alerts["contracts_ending"]) == (None, [])


def test_saving_horizons_is_audited_and_validated(db, world):
    assert isinstance(_horizons(db, world, trial=0), Err)
    saved = _horizons(db, world, document=None).value
    assert saved == {"contract_expiry_horizon_days": 30, "trial_end_horizon_days": 15, "document_expiry_horizon_days": None}
    payload = db.execute("SELECT payload FROM core.audit_log WHERE entity_id = %s AND action = 'hr_settings.updated'", (TENANT,)).fetchone()[0]
    assert payload["changed"] == {"contract_expiry_horizon_days": 30, "trial_end_horizon_days": 15}


def test_a_cdd_ending_inside_the_horizon_is_listed_until_it_is_renewed(db, world):
    _horizons(db, world)
    _contract(db, world, end_date=D(2026, 10, 10))
    assert [(a["employee_no"], a["contract_type"], a["date"]) for a in _alerts(db)["contracts_ending"]] == [("A-001", "cdd", "2026-10-10")]
    _contract(db, world, start_date=D(2026, 10, 11), end_date=D(2027, 4, 10))
    assert _alerts(db)["contracts_ending"] == []


def test_an_unrenewed_cdd_past_its_end_date_stays_listed_as_expired(db, world):
    _horizons(db, world)
    _contract(db, world, end_date=D(2026, 8, 1))  # 55 days before TODAY, well outside the 30-day horizon
    [listed] = _alerts(db)["contracts_ending"]
    assert (listed["employee_no"], listed["date"], listed["state"]) == ("A-001", "2026-08-01", "expired")


def test_a_cdd_ending_soon_is_listed_as_expiring_not_expired(db, world):
    _horizons(db, world)
    _contract(db, world, end_date=D(2026, 10, 10))
    [listed] = _alerts(db)["contracts_ending"]
    assert listed["state"] == "expiring"


def test_a_renewed_cdd_past_its_end_date_is_not_listed(db, world):
    _horizons(db, world)
    _contract(db, world, end_date=D(2026, 8, 1))
    _contract(db, world, start_date=D(2026, 8, 2), end_date=D(2027, 2, 1))
    assert _alerts(db)["contracts_ending"] == []


def test_a_cdd_ended_via_the_end_action_past_its_agreed_end_date_is_not_listed(db, world):
    _horizons(db, world)
    contract = _contract(db, world, end_date=D(2026, 12, 1))
    ContractService(db).end_contract(
        tenant_id=TENANT, actor_id=world.actor, contract_id=contract["id"], end_date=D(2026, 8, 1), end_reason="resignation"
    )
    assert _alerts(db)["contracts_ending"] == []


def test_an_unrenewed_cdd_of_someone_who_left_is_not_listed(db, world):
    _horizons(db, world)
    _contract(db, world, end_date=D(2026, 8, 1))
    EmployeeService(db).terminate_employee(
        tenant_id=TENANT, actor_id=world.actor, employee_id=world.employee_id, termination_date=D(2026, 8, 1), termination_reason="resignation"
    )
    assert _alerts(db)["contracts_ending"] == []


def test_a_trial_is_listed_only_inside_its_own_horizon(db, world):
    _horizons(db, world)
    _contract(db, world, contract_type="cdi", start_date=D(2026, 8, 1), trial_end_date=D(2026, 10, 5))
    assert [a["date"] for a in _alerts(db)["trials_ending"]] == ["2026-10-05"]


def test_a_trial_ending_after_the_horizon_is_not_listed(db, world):
    _horizons(db, world)
    _contract(db, world, contract_type="cdi", start_date=D(2026, 8, 1), trial_end_date=D(2026, 10, 20))
    assert _alerts(db)["trials_ending"] == []


def test_someone_who_left_raises_no_alert(db, world):
    _horizons(db, world)
    _contract(db, world, end_date=D(2026, 10, 10))
    DocumentService(db).create_document(
        tenant_id=TENANT, actor_id=world.actor, employee_id=world.employee_id,
        document=EmployeeDocument(kind="medical_certificate", expires_on=D(2026, 9, 1)),
    )
    EmployeeService(db).terminate_employee(
        tenant_id=TENANT, actor_id=world.actor, employee_id=world.employee_id, termination_date=D(2026, 9, 20), termination_reason="resignation"
    )
    alerts = _alerts(db)
    assert (alerts["contracts_ending"], alerts["documents_expiring"]) == ([], [])


def test_an_expired_document_is_listed_until_a_newer_one_of_the_same_kind_replaces_it(db, world):
    _horizons(db, world)
    documents = DocumentService(db)
    documents.create_document(
        tenant_id=TENANT, actor_id=world.actor, employee_id=world.employee_id,
        document=EmployeeDocument(kind="medical_certificate", expires_on=D(2026, 9, 1)),
    )
    assert [(a["kind"], a["state"]) for a in _alerts(db)["documents_expiring"]] == [("medical_certificate", "expired")]
    documents.create_document(
        tenant_id=TENANT, actor_id=world.actor, employee_id=world.employee_id,
        document=EmployeeDocument(kind="medical_certificate", issued_on=D(2026, 9, 20), expires_on=D(2027, 9, 20)),
    )
    assert _alerts(db)["documents_expiring"] == []


def test_the_document_list_carries_each_state_and_edits_are_audited(db, world):
    _horizons(db, world)
    documents = DocumentService(db)
    created = documents.create_document(
        tenant_id=TENANT, actor_id=world.actor, employee_id=world.employee_id,
        document=EmployeeDocument(kind="passport", expires_on=D(2026, 10, 10)),
    ).value
    assert created["state"] is not None
    [listed] = documents.list_documents(tenant_id=TENANT, employee_id=world.employee_id, today=TODAY)
    assert listed["state"] == "expiring"
    edited = documents.update_document(tenant_id=TENANT, actor_id=world.actor, document_id=created["id"], changes={"expires_on": D(2031, 1, 1)})
    assert edited.value["expires_on"] == "2031-01-01"
    actions = sorted(r[0] for r in db.execute("SELECT action FROM core.audit_log WHERE entity_id = %s", (created["id"],)).fetchall())
    assert actions == ["document.created", "document.updated"]
