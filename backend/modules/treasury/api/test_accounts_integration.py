"""Integration tests for the treasury master data: banks, accounts of the three kinds, the
single balance writer, and tenant settings."""
from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from ulid import ULID

from core.domain.result import Err, Ok
from modules.treasury.api.service import AccountMovementService, AccountService, BankService, SettingsService

TENANT = "integration-test-treasury-accounts"
D = Decimal
TODAY = datetime.date(2026, 3, 1)


@pytest.fixture
def env(db):
    actor = str(ULID())
    db.execute(
        "INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')",
        (actor, TENANT, f"{actor}@test.local"),
    )
    bank = BankService(db).create_bank(tenant_id=TENANT, actor_id=actor, name="BDM")
    branch = BankService(db).add_branch(tenant_id=TENANT, actor_id=actor, bank_id=bank.value["id"], name="Bamako centre")
    return {"actor": actor, "bank": bank.value["id"], "branch": branch.value["id"]}


def _bank_account(db, env, number="0001", **extra):
    return AccountService(db).create_account(
        tenant_id=TENANT, actor_id=env["actor"], kind="bank",
        fields={"name": "BDM XOF", "currency": "XOF", "branch_id": env["branch"], "account_number": number, **extra},
    )


def test_duplicate_bank_name_refused(db, env):
    again = BankService(db).create_bank(tenant_id=TENANT, actor_id=env["actor"], name="bdm")
    assert isinstance(again, Err) and again.code == "BANK_DUPLICATE"
    banks = BankService(db).list_banks(tenant_id=TENANT)
    assert banks[0]["branches"][0]["name"] == "Bamako centre"


def test_create_each_kind(db, env):
    assert isinstance(_bank_account(db, env), Ok)
    cash = AccountService(db).create_account(
        tenant_id=TENANT, actor_id=env["actor"], kind="cash", fields={"name": "Caisse", "currency": "XOF", "opening_balance": 5000})
    assert cash.value["balance"] == D("5000")
    mobile = AccountService(db).create_account(
        tenant_id=TENANT, actor_id=env["actor"], kind="mobile_money",
        fields={"name": "Orange Money", "currency": "XOF", "operator": "orange_money", "phone": "70000000", "ledger_account_code": "552"})
    assert mobile.value["ledger_account_code"] == "552"
    bad = AccountService(db).create_account(tenant_id=TENANT, actor_id=env["actor"], kind="mobile_money", fields={"name": "x", "currency": "XOF"})
    assert isinstance(bad, Err) and bad.code == "ACCOUNT_FIELD_REQUIRED"


def test_duplicate_number_and_iban_refused(db, env):
    assert isinstance(_bank_account(db, env, "0001", iban="ML12 3456"), Ok)
    dup_number = _bank_account(db, env, "0001")
    assert isinstance(dup_number, Err) and dup_number.code == "ACCOUNT_NUMBER_DUPLICATE"
    dup_iban = _bank_account(db, env, "0002", iban="ml123456")
    assert isinstance(dup_iban, Err) and dup_iban.code == "ACCOUNT_NUMBER_DUPLICATE"


def test_opening_balance_editable_until_first_movement(db, env):
    service = AccountService(db)
    account = _bank_account(db, env, opening_balance=1000).value
    edited = service.update_account(tenant_id=TENANT, actor_id=env["actor"], account_id=account["id"], changes={"opening_balance": 2000})
    assert edited.value["balance"] == D("2000")
    AccountMovementService(db).post(tenant_id=TENANT, actor_id=env["actor"], account_id=account["id"], signed_amount=D("500"),
                                    source_type="test", source_id=None, occurred_on=TODAY)
    locked = service.update_account(tenant_id=TENANT, actor_id=env["actor"], account_id=account["id"], changes={"opening_balance": 9})
    assert isinstance(locked, Err) and locked.code == "ACCOUNT_LOCKED"
    renamed = service.update_account(tenant_id=TENANT, actor_id=env["actor"], account_id=account["id"], changes={"name": "Renamed"})
    assert renamed.value["name"] == "Renamed" and renamed.value["balance"] == D("2500")


def test_movements_update_balance_and_history(db, env):
    account = AccountService(db).create_account(
        tenant_id=TENANT, actor_id=env["actor"], kind="cash", fields={"name": "Caisse", "currency": "XOF", "opening_balance": 100}).value
    movements = AccountMovementService(db)
    ok = movements.post(tenant_id=TENANT, actor_id=env["actor"], account_id=account["id"], signed_amount=D("-60"),
                        source_type="test", source_id="x", occurred_on=TODAY)
    assert ok == Ok(D("40"))
    refused = movements.post(tenant_id=TENANT, actor_id=env["actor"], account_id=account["id"], signed_amount=D("-41"),
                             source_type="test", source_id="y", occurred_on=TODAY)
    assert isinstance(refused, Err) and refused.code == "INSUFFICIENT_BALANCE"
    history = AccountService(db).list_movements(tenant_id=TENANT, account_id=account["id"])
    assert [m["balance_after"] for m in history] == [D("40")]


def test_bank_overdraft_only_when_allowed(db, env):
    strict = _bank_account(db, env, "S1").value
    flexible = _bank_account(db, env, "S2", allow_overdraft=True).value
    movements = AccountMovementService(db)
    args = dict(tenant_id=TENANT, actor_id=env["actor"], signed_amount=D("-10"), source_type="t", source_id=None, occurred_on=TODAY)
    assert isinstance(movements.post(account_id=strict["id"], **args), Err)
    assert movements.post(account_id=flexible["id"], **args) == Ok(D("-10"))


def test_delete_only_without_movements_and_deactivate(db, env):
    service = AccountService(db)
    used = _bank_account(db, env, "U1").value
    AccountMovementService(db).post(tenant_id=TENANT, actor_id=env["actor"], account_id=used["id"], signed_amount=D("10"),
                                    source_type="t", source_id=None, occurred_on=TODAY)
    refused = service.delete_account(tenant_id=TENANT, actor_id=env["actor"], account_id=used["id"])
    assert isinstance(refused, Err) and refused.code == "ACCOUNT_HAS_MOVEMENTS"
    service.update_account(tenant_id=TENANT, actor_id=env["actor"], account_id=used["id"], changes={"is_active": False})
    assert all(a["id"] != used["id"] for a in service.list_accounts(tenant_id=TENANT))
    assert any(a["id"] == used["id"] for a in service.list_accounts(tenant_id=TENANT, include_inactive=True))
    inactive_move = AccountMovementService(db).post(tenant_id=TENANT, actor_id=env["actor"], account_id=used["id"],
                                                    signed_amount=D("1"), source_type="t", source_id=None, occurred_on=TODAY)
    assert isinstance(inactive_move, Err) and inactive_move.code == "ACCOUNT_INACTIVE"
    fresh = _bank_account(db, env, "F1").value
    assert isinstance(service.delete_account(tenant_id=TENANT, actor_id=env["actor"], account_id=fresh["id"]), Ok)


def test_settings_and_alert_rules(db, env):
    settings = SettingsService(db)
    assert settings.get_settings(tenant_id=TENANT)["cash_payment_limit"] is None
    assert isinstance(settings.set_setting(tenant_id=TENANT, actor_id=env["actor"], key="cash_payment_limit", value=500000), Ok)
    assert settings.get_settings(tenant_id=TENANT)["cash_payment_limit"] == 500000
    bad = settings.set_setting(tenant_id=TENANT, actor_id=env["actor"], key="cash_payment_limit", value=-1)
    assert isinstance(bad, Err) and bad.code == "INVALID_SETTING"
    assert isinstance(settings.set_setting(tenant_id=TENANT, actor_id=env["actor"], key="nope", value=1), Err)

    rules = {(r["direction"], r["method"]): r for r in settings.list_alert_rules(tenant_id=TENANT)}
    assert rules[("in", "draft")]["offset_days"] == 15 and rules[("out", "cheque")]["offset_days"] == -1
    settings.set_alert_rule(tenant_id=TENANT, actor_id=env["actor"], direction="in", method="draft", offset_days=7)
    updated = {(r["direction"], r["method"]): r for r in settings.list_alert_rules(tenant_id=TENANT)}
    assert updated[("in", "draft")]["offset_days"] == 7 and not updated[("in", "draft")]["is_default"]
