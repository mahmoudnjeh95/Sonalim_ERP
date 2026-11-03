"""Integration tests for payment orders and the in-app notices that ask a colleague to execute them."""
from __future__ import annotations

import datetime

import pytest
from ulid import ULID

from core.domain.result import Err, Ok
from modules.treasury.api.document_service import DocumentService
from modules.treasury.api.payment_order_service import PaymentOrderService
from modules.treasury.api.service import AccountService, BankService

TENANT = "integration-test-treasury-payment-orders"
TODAY = datetime.date(2026, 3, 1)


@pytest.fixture
def env(db):
    actor, other, supplier = (str(ULID()) for _ in range(3))
    for uid in (actor, other):
        db.execute("INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')", (uid, TENANT, f"{uid}@test.local"))
    db.execute("INSERT INTO core.partners (id, tenant_id, name, kind, status) VALUES (%s, %s, 'Supplier', 'supplier', 'active')", (supplier, TENANT))
    bank = BankService(db).create_bank(tenant_id=TENANT, actor_id=actor, name="BDM").value
    branch = BankService(db).add_branch(tenant_id=TENANT, actor_id=actor, bank_id=bank["id"], name="Centre").value
    account = AccountService(db).create_account(
        tenant_id=TENANT, actor_id=actor, kind="bank",
        fields={"name": "BDM XOF", "currency": "XOF", "branch_id": branch["id"], "account_number": "001", "opening_balance": 10000}).value
    cash = AccountService(db).create_account(tenant_id=TENANT, actor_id=actor, kind="cash",
                                             fields={"name": "Caisse", "currency": "XOF", "opening_balance": 500}).value
    return {"actor": actor, "other": other, "supplier": supplier, "bank": account["id"], "cash": cash["id"]}


def _disbursement(db, env, method="transfer", account_key="bank"):
    doc = DocumentService(db).create_and_post(
        tenant_id=TENANT, actor_id=env["actor"], direction="out", partner_id=env["supplier"], doc_date=TODAY, currency="XOF",
        payments=[{"method": method, "amount": 300, "account_id": env[account_key]}], with_details=False, correlation_id="c")
    assert isinstance(doc, Ok), doc
    return doc.value["id"]


def test_order_lists_the_transfers_and_is_unique_per_disbursement(db, env):
    disbursement = _disbursement(db, env)
    service = PaymentOrderService(db)
    created = service.create_for_disbursement(tenant_id=TENANT, actor_id=env["actor"], disbursement_id=disbursement)
    assert isinstance(created, Ok) and created.value["number"].startswith("OV-")
    assert created.value["total"] == 300 and created.value["transfers"][0]["account_number"] == "001"
    again = service.create_for_disbursement(tenant_id=TENANT, actor_id=env["actor"], disbursement_id=disbursement)
    assert isinstance(again, Err) and again.code == "PAYMENT_ORDER_EXISTS"
    assert [o["number"] for o in service.list(tenant_id=TENANT)] == [created.value["number"]]


def test_order_needs_a_posted_disbursement_with_a_transfer(db, env):
    service = PaymentOrderService(db)
    cash_only = _disbursement(db, env, method="cash", account_key="cash")
    refused = service.create_for_disbursement(tenant_id=TENANT, actor_id=env["actor"], disbursement_id=cash_only)
    assert isinstance(refused, Err) and refused.code == "NO_TRANSFER"
    cancelled = _disbursement(db, env)
    DocumentService(db).cancel(tenant_id=TENANT, actor_id=env["actor"], document_id=cancelled, direction="out", correlation_id="c")
    assert service.create_for_disbursement(tenant_id=TENANT, actor_id=env["actor"], disbursement_id=cancelled).code == "DOCUMENT_NOT_POSTED"
    assert service.create_for_disbursement(tenant_id=TENANT, actor_id=env["actor"], disbursement_id="nope").code == "NOT_FOUND"


def test_notification_reaches_only_the_chosen_user_and_can_be_read(db, env):
    disbursement = _disbursement(db, env)
    service = PaymentOrderService(db)
    order = service.create_for_disbursement(tenant_id=TENANT, actor_id=env["actor"], disbursement_id=disbursement).value
    assert isinstance(service.notify(tenant_id=TENANT, actor_id=env["actor"], order_id=order["id"], user_id=env["other"]), Ok)
    mine = service.notifications(tenant_id=TENANT, user_id=env["actor"])
    theirs = service.notifications(tenant_id=TENANT, user_id=env["other"])
    assert mine == [] and len(theirs) == 1 and order["number"] in theirs[0]["message_en"]
    assert isinstance(service.mark_read(tenant_id=TENANT, user_id=env["other"], notification_id=theirs[0]["id"]), Ok)
    assert service.notifications(tenant_id=TENANT, user_id=env["other"]) == []
    assert len(service.notifications(tenant_id=TENANT, user_id=env["other"], include_read=True)) == 1
    stranger = service.mark_read(tenant_id=TENANT, user_id=env["actor"], notification_id=theirs[0]["id"])
    assert isinstance(stranger, Err) and stranger.code == "NOT_FOUND"
    unknown_user = service.notify(tenant_id=TENANT, actor_id=env["actor"], order_id=order["id"], user_id="ghost")
    assert isinstance(unknown_user, Err)
    assert {u["id"] for u in service.notifiable_users(tenant_id=TENANT)} == {env["actor"], env["other"]}
