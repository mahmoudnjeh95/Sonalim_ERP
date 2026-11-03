"""The SYSCOHADA seed obeys the ledger's own rules, and the manifest declares the ledger."""
import json
import pathlib

from core.domain.result import Ok
from modules.finance.domain.ledger import validate_account
from modules.finance.domain.posting import PAYMENT_METHODS, PAYROLL_LINE_KINDS, WILDCARD, validate_rule
from modules.finance.domain.syscohada_chart import CHART, DEFAULT_POSTING_RULES, JOURNALS

BY_CODE = {account.code: account for account in CHART}


def test_every_account_is_valid_and_comes_after_its_parent():
    seen: set[str] = set()
    for account in CHART:
        parent = BY_CODE.get(account.parent_code) if account.parent_code else None
        assert isinstance(validate_account(account, parent), Ok), account.code
        if account.parent_code:
            assert account.parent_code in seen, f"{account.code} is listed before its parent"
            assert not BY_CODE[account.parent_code].is_postable, f"the parent of {account.code} is a posting account"
        seen.add(account.code)
    assert len(seen) == len(CHART)


def test_the_nine_classes_are_headings():
    for class_no in range(1, 10):
        account = BY_CODE[str(class_no)]
        assert account.class_no == class_no and not account.is_postable


def test_the_accounts_the_plant_posts_to_are_postable():
    for code in (
        "401", "411", "421", "422", "431", "433", "441", "442", "443", "444", "445", "446", "447",
        "521", "552", "571", "585", "641", "661", "663", "664", "701", "702",
    ):
        assert BY_CODE[code].is_postable, code


def test_the_six_journals():
    assert [code for code, _, _ in JOURNALS] == ["PAIE", "VTE", "ACH", "BNQ", "CAI", "OD"]


def test_every_default_rule_is_valid_against_the_seed_and_awaits_confirmation():
    journals = {code for code, _, _ in JOURNALS}
    for rule in DEFAULT_POSTING_RULES:
        assert isinstance(validate_rule(rule, BY_CODE, journals), Ok), rule
        assert rule.status == "to_confirm"


def test_every_payroll_line_kind_and_payment_method_has_a_default():
    keys = {(rule.source, rule.source_kind, rule.code) for rule in DEFAULT_POSTING_RULES}
    for kind in PAYROLL_LINE_KINDS:
        assert ("payroll", kind, WILDCARD) in keys, kind
    for method in PAYMENT_METHODS:
        assert ("payroll", "payment", method) in keys, method
    assert ("invoice", "issued", WILDCARD) in keys
    assert ("invoice", "paid", WILDCARD) in keys


def test_the_manifest_declares_the_ledger():
    manifest_path = pathlib.Path(__file__).resolve().parents[1] / "module.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for permission in (
        "finance.view_ledger",
        "finance.manage_entries",
        "finance.admin_entries",
        "finance.manage_accounts",
        "finance.admin_accounts",
        "finance.admin_periods",
        "finance.manage_posting_rules",
    ):
        assert permission in manifest["permissions"], permission
    assert "payroll" in manifest["optional_depends"]
    assert "finance.journal_entry.posted" in manifest["publishes_events"]
    for event in ("payroll.run.approved", "payroll.run.paid", "payroll.run.reversed", "finance.invoice.issued", "finance.invoice.paid"):
        assert event in manifest["subscribes_events"], event
