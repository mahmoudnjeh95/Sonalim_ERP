"""Rule sets against a real database: validation, duplicates, confirmation lock, loading, in force."""
from __future__ import annotations

import datetime
from decimal import Decimal

import pytest

from core.domain.result import Err, Ok
from modules.payroll.api.rule_set_service import CHILD_KINDS, RuleSetService
from modules.payroll.api.testing_support import TEST_COUNTRY, make_user, set_country, store_rule_set
from modules.payroll.domain.synthetic import synthetic_rule_set

TENANT = "payroll-rules-test"
D = Decimal
JAN = datetime.date(2031, 1, 1)


@pytest.fixture
def actor(db):
    return make_user(db, TENANT)


def _create(db, actor, valid_from=JAN):
    return RuleSetService(db).create_rule_set(
        tenant_id=TENANT, actor_id=actor, country=TEST_COUNTRY, name="Test", valid_from=valid_from,
        working_days_per_month=D(20), working_hours_per_month=D(160),
    )


def test_a_new_rule_set_is_an_empty_draft(db, actor):
    created = _create(db, actor)
    assert isinstance(created, Ok)
    assert created.value["status"] == "draft" and created.value["components"] == []
    assert (created.value["working_hours_per_month"], created.value["settlement_reference_months"]) == (160, 12)


def test_two_rule_sets_cannot_start_the_same_month_in_one_country(db, actor):
    _create(db, actor)
    again = _create(db, actor)
    assert isinstance(again, Err) and again.code == "DUPLICATE_RULESET" and again.message_fr


def test_a_row_is_validated_before_it_is_stored(db, actor):
    rule_set_id = _create(db, actor).value["id"]
    refused = RuleSetService(db).add_child(
        tenant_id=TENANT, actor_id=actor, rule_set_id=rule_set_id, kind="components",
        values={"code": "SEN2", "name_en": "x", "name_fr": "x", "kind": "earning", "formula_type": "rate_x_base"},
    )
    assert isinstance(refused, Err) and refused.code == "RULE_INVALID" and "base" in refused.message_fr


def test_a_duplicate_row_is_refused_and_the_transaction_goes_on(db, actor):
    service = RuleSetService(db)
    rule_set_id = _create(db, actor).value["id"]
    values = {"band_code": "day", "multiplier": "1.5"}
    assert isinstance(service.add_child(tenant_id=TENANT, actor_id=actor, rule_set_id=rule_set_id, kind="overtime_rates", values=values), Ok)
    again = service.add_child(tenant_id=TENANT, actor_id=actor, rule_set_id=rule_set_id, kind="overtime_rates", values=values)
    assert isinstance(again, Err) and again.code == "DUPLICATE_RULE"
    assert len(service.list_children(tenant_id=TENANT, rule_set_id=rule_set_id, kind="overtime_rates")) == 1


def test_confirming_an_incomplete_rule_set_says_what_is_missing(db, actor):
    rule_set_id = _create(db, actor).value["id"]
    refused = RuleSetService(db).confirm_rule_set(tenant_id=TENANT, actor_id=actor, rule_set_id=rule_set_id)
    assert isinstance(refused, Err) and refused.code == "RULESET_INCOMPLETE"
    assert "component BASE is missing" in refused.message and "la rubrique BASE manque" in refused.message_fr


def test_confirmation_is_stamped_and_audited(db, actor):
    rule_set_id = store_rule_set(db, tenant_id=TENANT, actor_id=actor, valid_from=JAN)
    document = RuleSetService(db).get_rule_set(tenant_id=TENANT, rule_set_id=rule_set_id)
    assert document["status"] == "confirmed" and document["confirmed_by"] == actor and document["confirmed_at"]
    audit = db.execute(
        "SELECT payload FROM core.audit_log WHERE entity_id = %s AND action = 'rule_set.confirmed'", (rule_set_id,)
    ).fetchone()
    assert audit == ({"from_status": "draft", "to_status": "confirmed"},)


def test_a_confirmed_rule_set_is_locked(db, actor):
    service = RuleSetService(db)
    rule_set_id = store_rule_set(db, tenant_id=TENANT, actor_id=actor, valid_from=JAN)
    component_id = service.list_children(tenant_id=TENANT, rule_set_id=rule_set_id, kind="components")[0]["id"]
    attempts = [
        service.update_rule_set(tenant_id=TENANT, actor_id=actor, rule_set_id=rule_set_id, changes={"name": "Changed"}),
        service.add_child(tenant_id=TENANT, actor_id=actor, rule_set_id=rule_set_id, kind="seniority_scale", values={"years_from": 20, "percent": 9}),
        service.update_child(tenant_id=TENANT, actor_id=actor, rule_set_id=rule_set_id, kind="components", row_id=component_id, changes={"taxable": False}),
        service.delete_child(tenant_id=TENANT, actor_id=actor, rule_set_id=rule_set_id, kind="components", row_id=component_id),
        service.delete_rule_set(tenant_id=TENANT, actor_id=actor, rule_set_id=rule_set_id),
    ]
    assert [getattr(result, "code", None) for result in attempts] == ["RULESET_LOCKED"] * 5


def test_load_gives_back_the_rules_that_were_stored(db, actor):
    expected = synthetic_rule_set()
    rule_set_id = store_rule_set(db, tenant_id=TENANT, actor_id=actor, valid_from=JAN)
    loaded = RuleSetService(db).load(tenant_id=TENANT, rule_set_id=rule_set_id)
    assert loaded.require("HOUSING") == expected.require("HOUSING")
    assert loaded.brackets_for("TAX") == expected.brackets_for("TAX")
    assert loaded.family_relief("TAX") == expected.family_relief("TAX")
    assert loaded.professional_relief("TAX") == expected.professional_relief("TAX")
    assert sorted(loaded.contributions, key=lambda c: c.code) == sorted(expected.contributions, key=lambda c: c.code)
    assert (loaded.round_to, loaded.tax_round_to, loaded.tax_round_mode, loaded.status) == (1, 10, "down", "confirmed")


def test_the_rule_set_in_force_is_the_latest_started_by_the_period(db, actor):
    set_country(db, tenant_id=TENANT, actor_id=actor)
    first = _create(db, actor, valid_from=JAN).value["id"]
    second = _create(db, actor, valid_from=datetime.date(2031, 10, 1)).value["id"]
    service = RuleSetService(db)
    assert service.in_force(tenant_id=TENANT, period=datetime.date(2031, 9, 1)).value["id"] == first
    assert service.in_force(tenant_id=TENANT, period=datetime.date(2031, 10, 1)).value["id"] == second
    missing = service.in_force(tenant_id=TENANT, period=datetime.date(2030, 12, 1))
    assert isinstance(missing, Err) and missing.code == "RULESET_MISSING" and "12/2030" in missing.message_fr


def test_without_a_payroll_country_no_rule_set_applies(db, actor):
    _create(db, actor)
    missing = RuleSetService(db).in_force(tenant_id=TENANT, period=JAN)
    assert isinstance(missing, Err) and missing.code == "RULESET_MISSING"


def test_copy_makes_an_editable_draft_with_every_row(db, actor):
    service = RuleSetService(db)
    source = store_rule_set(db, tenant_id=TENANT, actor_id=actor, valid_from=JAN)
    copied = service.copy_rule_set(tenant_id=TENANT, actor_id=actor, rule_set_id=source, valid_from=datetime.date(2032, 1, 1), name="2032 draft")
    assert isinstance(copied, Ok) and copied.value["status"] == "draft"
    original = service.get_rule_set(tenant_id=TENANT, rule_set_id=source)
    for kind in CHILD_KINDS:
        assert len(copied.value[kind]) == len(original[kind]), kind


def test_an_edit_keeps_unsent_fields_and_can_clear_a_nullable_one(db, actor):
    service = RuleSetService(db)
    rule_set_id = store_rule_set(db, tenant_id=TENANT, actor_id=actor, valid_from=JAN, confirm=False)
    pension = next(row for row in service.list_children(tenant_id=TENANT, rule_set_id=rule_set_id, kind="contributions") if row["code"] == "PENSION")
    updated = service.update_child(tenant_id=TENANT, actor_id=actor, rule_set_id=rule_set_id, kind="contributions",
                                   row_id=pension["id"], changes={"ceiling_monthly": None})
    assert isinstance(updated, Ok)
    assert updated.value["ceiling_monthly"] is None and updated.value["employee_rate"] == 5
