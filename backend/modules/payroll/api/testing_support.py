"""Helpers the payroll integration tests share. Not imported by production code."""
from __future__ import annotations

import datetime
from dataclasses import asdict
from typing import Any

from ulid import ULID

from core.domain.result import Ok
from modules.payroll.api.rule_set_service import RuleSetService
from modules.payroll.domain.rule_validation import relief_parameters
from modules.payroll.domain.rules import RuleSet
from modules.payroll.domain.synthetic import synthetic_rule_set

TEST_COUNTRY = "ZZ"  # ISO "user-assigned" code: never a real payroll country


def make_user(connection, tenant_id: str) -> str:
    user_id = str(ULID())
    connection.execute(
        "INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')",
        (user_id, tenant_id, f"{user_id}@test.local"),
    )
    return user_id


def rule_rows(rules: RuleSet) -> dict[str, list[dict[str, Any]]]:
    """The domain rule set as the values an admin would type, table by table."""
    return {
        "components": [asdict(component) for component in rules.components],
        "contributions": [asdict(contribution) for contribution in rules.contributions],
        "tax_brackets": [{"tax_code": b.tax_code, "lower_bound": b.lower, "upper_bound": b.upper, "rate": b.rate,
                          "annualised": b.annualised} for b in rules.tax_brackets],
        "tax_reliefs": [{"tax_code": r.tax_code, "kind": "family", "parameters": relief_parameters(r)} for r in rules.family_reliefs]
        + [{"tax_code": r.tax_code, "kind": "professional_expenses", "parameters": relief_parameters(r)} for r in rules.professional_reliefs],
        "seniority_scale": [asdict(step) for step in rules.seniority_scale],
        "overtime_rates": [asdict(rate) for rate in rules.overtime_rates],
        "severance_scale": [asdict(step) for step in rules.severance_scale],
    }


def store_rule_set(connection, *, tenant_id: str, actor_id: str, valid_from: datetime.date, rules: RuleSet | None = None,
                   confirm: bool = True, country: str = TEST_COUNTRY, name: str = "Synthetic test rules") -> str:
    rules = rules or synthetic_rule_set()
    service = RuleSetService(connection)
    created = service.create_rule_set(
        tenant_id=tenant_id, actor_id=actor_id, country=country, name=name, valid_from=valid_from,
        working_days_per_month=rules.working_days_per_month, working_hours_per_month=rules.working_hours_per_month,
        round_to=rules.round_to, round_mode=rules.round_mode, tax_round_to=rules.tax_round_to,
        tax_round_mode=rules.tax_round_mode, settlement_reference_months=rules.settlement_reference_months,
    )
    assert isinstance(created, Ok), created
    rule_set_id = created.value["id"]
    for kind, rows in rule_rows(rules).items():
        for values in rows:
            added = service.add_child(tenant_id=tenant_id, actor_id=actor_id, rule_set_id=rule_set_id, kind=kind, values=values)
            assert isinstance(added, Ok), added
    if confirm:
        confirmed = service.confirm_rule_set(tenant_id=tenant_id, actor_id=actor_id, rule_set_id=rule_set_id)
        assert isinstance(confirmed, Ok), confirmed
    return rule_set_id


def set_country(connection, *, tenant_id: str, actor_id: str, country: str = TEST_COUNTRY) -> None:
    saved = RuleSetService(connection).save_settings(tenant_id=tenant_id, actor_id=actor_id, country=country)
    assert isinstance(saved, Ok), saved
