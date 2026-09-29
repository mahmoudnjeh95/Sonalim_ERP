"""Editing the chart of accounts and the posting rules."""
from __future__ import annotations

from core.domain.result import Err, Ok
from modules.finance.api.account_service import AccountService
from modules.finance.api.posting_rule_service import PostingRuleService


def _audited(ledger, entity_id: str, action: str) -> int:
    return ledger["db"].execute(
        "SELECT count(*) FROM core.audit_log WHERE tenant_id = %s AND entity_id = %s AND action = %s",
        (ledger["tenant"], entity_id, action),
    ).fetchone()[0]


def _rule(ledger, source_kind: str) -> dict:
    rules = PostingRuleService(ledger["db"]).list_rules(tenant_id=ledger["tenant"])
    return next(rule for rule in rules if rule["source_kind"] == source_kind and rule["code"] == "*")


def test_a_sub_account_extends_its_heading(ledger):
    accounts = AccountService(ledger["db"])
    created = accounts.create_account(
        tenant_id=ledger["tenant"], actor_id=ledger["actor"], code="5211", name="BDM-SA compte courant",
        account_type="asset", parent_code="52",
    )
    assert isinstance(created, Ok), created
    assert created.value == {
        "code": "5211", "name": "BDM-SA compte courant", "class_no": 5,
        "account_type": "asset", "is_postable": True, "parent_code": "52",
    }
    assert _audited(ledger, "5211", "account.created") == 1
    duplicate = accounts.create_account(
        tenant_id=ledger["tenant"], actor_id=ledger["actor"], code="5211", name="Autre",
        account_type="asset", parent_code="52",
    )
    assert isinstance(duplicate, Err) and duplicate.code == "ACCOUNT_EXISTS"
    wrong_parent = accounts.create_account(
        tenant_id=ledger["tenant"], actor_id=ledger["actor"], code="5711", name="Caisse usine",
        account_type="asset", parent_code="52",
    )
    assert isinstance(wrong_parent, Err) and wrong_parent.code == "INVALID_ACCOUNT"


def test_editing_an_account_keeps_its_number_and_audits_the_change(ledger):
    accounts = AccountService(ledger["db"])
    updated = accounts.update_account(tenant_id=ledger["tenant"], actor_id=ledger["actor"], code="571", name="Caisse usine")
    assert isinstance(updated, Ok), updated
    assert updated.value["name"] == "Caisse usine" and updated.value["is_postable"] is True
    payload = ledger["db"].execute(
        "SELECT payload FROM core.audit_log WHERE tenant_id = %s AND entity_id = '571' AND action = 'account.updated'",
        (ledger["tenant"],),
    ).fetchone()[0]
    assert payload == {"name": "Caisse usine"}
    missing = accounts.update_account(tenant_id=ledger["tenant"], actor_id=ledger["actor"], code="999", name="x")
    assert isinstance(missing, Err) and missing.code == "NOT_FOUND"
    bad_type = accounts.update_account(tenant_id=ledger["tenant"], actor_id=ledger["actor"], code="571", account_type="cash")
    assert isinstance(bad_type, Err) and bad_type.code == "INVALID_ACCOUNT"


def test_the_six_journals_are_listed(ledger):
    codes = [journal["code"] for journal in AccountService(ledger["db"]).list_journals(tenant_id=ledger["tenant"])]
    assert sorted(codes) == ["ACH", "BNQ", "CAI", "OD", "PAIE", "VTE"]


def test_a_code_specific_rule_is_created_to_confirm(ledger):
    rules = PostingRuleService(ledger["db"])
    created = rules.create_rule(
        tenant_id=ledger["tenant"], actor_id=ledger["actor"], source="payroll",
        source_kind="employee_contribution", code="AMO_EE", credit_account_code="433",
    )
    assert isinstance(created, Ok), created
    assert created.value["status"] == "to_confirm" and created.value["credit_account_code"] == "433"
    assert _audited(ledger, created.value["id"], "posting_rule.created") == 1
    duplicate = rules.create_rule(
        tenant_id=ledger["tenant"], actor_id=ledger["actor"], source="payroll",
        source_kind="employee_contribution", code="AMO_EE", credit_account_code="431",
    )
    assert isinstance(duplicate, Err) and duplicate.code == "POSTING_RULE_EXISTS"
    heading = rules.create_rule(
        tenant_id=ledger["tenant"], actor_id=ledger["actor"], source="payroll",
        source_kind="employer_contribution", code="AMO_ER", debit_account_code="66", credit_account_code="433",
    )
    assert isinstance(heading, Err) and heading.code == "ACCOUNT_NOT_POSTABLE"


def test_confirming_then_editing_sends_a_rule_back_to_confirmation(ledger):
    rules = PostingRuleService(ledger["db"])
    net = _rule(ledger, "net")
    confirmed = rules.confirm_rule(tenant_id=ledger["tenant"], actor_id=ledger["actor"], rule_id=net["id"])
    assert isinstance(confirmed, Ok), confirmed
    assert confirmed.value["status"] == "confirmed" and confirmed.value["confirmed_by"] == ledger["actor"]
    twice = rules.confirm_rule(tenant_id=ledger["tenant"], actor_id=ledger["actor"], rule_id=net["id"])
    assert isinstance(twice, Err) and twice.code == "INVALID_TRANSITION"
    AccountService(ledger["db"]).create_account(
        tenant_id=ledger["tenant"], actor_id=ledger["actor"], code="4221", name="Rémunérations dues, usine",
        account_type="liability", parent_code="42",
    )
    edited = rules.update_rule(tenant_id=ledger["tenant"], actor_id=ledger["actor"], rule_id=net["id"], credit_account_code="4221")
    assert isinstance(edited, Ok), edited
    assert edited.value["credit_account_code"] == "4221"
    assert edited.value["status"] == "to_confirm" and edited.value["confirmed_by"] is None


def test_a_rule_cannot_lose_both_accounts(ledger):
    rules = PostingRuleService(ledger["db"])
    earning = _rule(ledger, "earning")
    cleared = rules.update_rule(tenant_id=ledger["tenant"], actor_id=ledger["actor"], rule_id=earning["id"], debit_account_code="")
    assert isinstance(cleared, Err) and cleared.code == "INVALID_POSTING_RULE"
    missing = rules.update_rule(tenant_id=ledger["tenant"], actor_id=ledger["actor"], rule_id="nope", debit_account_code="661")
    assert isinstance(missing, Err) and missing.code == "NOT_FOUND"
