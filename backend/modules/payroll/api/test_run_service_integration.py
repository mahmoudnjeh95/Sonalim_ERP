"""Runs against a real database: one regular run per month, edits while open, reopening rules."""
from __future__ import annotations

import datetime

import pytest

from core.domain.result import Err, Ok
from modules.payroll.api.rule_set_service import RuleSetService
from modules.payroll.api.run_service import RunService
from modules.payroll.api.testing_support import (
    FakePresence, FakeSnapshots, insert_run, make_user, set_country, store_rule_set,
)

TENANT = "payroll-runs-test"
SEPT = datetime.date(2031, 9, 1)


@pytest.fixture
def world(db):
    actor = make_user(db, TENANT)
    set_country(db, tenant_id=TENANT, actor_id=actor)
    rule_set_id = store_rule_set(db, tenant_id=TENANT, actor_id=actor, valid_from=datetime.date(2031, 1, 1))
    service = RunService(db, snapshots=FakeSnapshots([]), presence=FakePresence(closed=True))
    return {"db": db, "actor": actor, "service": service, "rule_set_id": rule_set_id}


def _create(world, **changes):
    values = {"period": SEPT, "run_type": "regular"} | changes
    return world["service"].create_run(tenant_id=TENANT, actor_id=world["actor"], **values)


def test_a_regular_run_starts_as_a_draft_and_shows_what_it_will_use(world):
    created = _create(world)
    assert isinstance(created, Ok)
    run = created.value
    assert (run["status"], run["run_type"], run["payslip_count"], run["presence_closed"]) == ("draft", "regular", 0, True)
    assert run["rule_set_in_force"] == {"id": world["rule_set_id"], "name": "Synthetic test rules", "status": "confirmed"}


def test_one_regular_run_per_month_but_any_number_of_off_cycle_runs(world):
    _create(world)
    again = _create(world)
    assert isinstance(again, Err) and again.code == "DUPLICATE_RUN" and "09/2031" in again.message_fr
    assert isinstance(_create(world, run_type="off_cycle", employee_ids=["E1"]), Ok)
    assert isinstance(_create(world, run_type="off_cycle", employee_ids=["E2"]), Ok)
    assert len(world["service"].list_runs(tenant_id=TENANT)) == 3


def test_a_reversed_regular_run_frees_its_month(world):
    insert_run(world["db"], tenant_id=TENANT, actor_id=world["actor"], period=SEPT, status="reversed", rule_set_id=world["rule_set_id"])
    assert isinstance(_create(world), Ok)


def test_bad_runs_are_refused_in_both_languages(world):
    for changes in ({"period": datetime.date(2031, 9, 15)}, {"run_type": "bonus"}, {"employee_ids": ["E1"]}):
        refused = _create(world, **changes)
        assert isinstance(refused, Err) and refused.code == "RUN_INVALID" and refused.message_fr


def test_an_open_run_can_be_relabelled_and_deleted_with_an_audit_trail(world):
    run_id = _create(world, run_type="off_cycle", employee_ids=["E1"]).value["id"]
    service = world["service"]
    updated = service.update_run(tenant_id=TENANT, actor_id=world["actor"], run_id=run_id, changes={"label": "Correction", "employee_ids": ["E2", "E1"]})
    assert isinstance(updated, Ok) and updated.value["label"] == "Correction" and updated.value["employee_ids"] == ["E1", "E2"]
    assert isinstance(service.delete_run(tenant_id=TENANT, actor_id=world["actor"], run_id=run_id), Ok)
    actions = [row[0] for row in world["db"].execute(
        "SELECT action FROM core.audit_log WHERE entity_id = %s ORDER BY occurred_at, action", (run_id,)).fetchall()]
    assert set(actions) == {"payroll_run.created", "payroll_run.updated", "payroll_run.deleted"}


def test_an_approved_run_cannot_be_edited_or_deleted(world):
    run_id = insert_run(world["db"], tenant_id=TENANT, actor_id=world["actor"], period=SEPT, status="approved", rule_set_id=world["rule_set_id"])
    service = world["service"]
    assert service.update_run(tenant_id=TENANT, actor_id=world["actor"], run_id=run_id, changes={"label": "x"}).code == "RUN_LOCKED"
    assert service.delete_run(tenant_id=TENANT, actor_id=world["actor"], run_id=run_id).code == "RUN_LOCKED"


def test_reopening_a_rule_set_is_refused_once_an_approved_run_used_it(world):
    rules = RuleSetService(world["db"])
    reopened = rules.reopen_rule_set(tenant_id=TENANT, actor_id=world["actor"], rule_set_id=world["rule_set_id"])
    assert isinstance(reopened, Ok) and reopened.value["status"] == "draft" and reopened.value["confirmed_at"] is None
    assert isinstance(rules.confirm_rule_set(tenant_id=TENANT, actor_id=world["actor"], rule_set_id=world["rule_set_id"]), Ok)
    insert_run(world["db"], tenant_id=TENANT, actor_id=world["actor"], period=SEPT, status="approved", rule_set_id=world["rule_set_id"])
    refused = rules.reopen_rule_set(tenant_id=TENANT, actor_id=world["actor"], rule_set_id=world["rule_set_id"])
    assert isinstance(refused, Err) and refused.code == "RULESET_IN_USE" and "09/2031" in refused.message_fr
