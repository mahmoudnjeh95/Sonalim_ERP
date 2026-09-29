"""The rule tables refuse what the engine could not read.

The migration file is executed inside the test transaction (it is idempotent), so the test
holds whether or not the development database has applied it yet.
"""
from __future__ import annotations

import pathlib

import psycopg
import pytest
from ulid import ULID

MIGRATION = pathlib.Path(__file__).resolve().parents[1] / "migrations" / "0001_payroll_rules.sql"
TENANT = "payroll-schema-test"


def _migrate(db) -> None:
    db.execute(MIGRATION.read_text(encoding="utf-8"))


def _rule_set(db, valid_from: str = "2031-01-01") -> str:
    rule_set_id = str(ULID())
    db.execute(
        """
        INSERT INTO payroll.rule_sets
            (id, tenant_id, country, name, valid_from, working_days_per_month, working_hours_per_month, created_by)
        VALUES (%s, %s, 'ZZ', 'Schema test', %s, 20, 160, 'tester')
        """,
        (rule_set_id, TENANT, valid_from),
    )
    return rule_set_id


def test_a_new_rule_set_is_a_draft_rounded_to_the_franc(db):
    _migrate(db)
    rule_set_id = _rule_set(db)
    row = db.execute(
        "SELECT status, round_to, round_mode, tax_round_to, tax_round_mode, settlement_reference_months"
        " FROM payroll.rule_sets WHERE id = %s",
        (rule_set_id,),
    ).fetchone()
    assert row == ("draft", 1, "half_up", 1, "half_up", 12)


def test_a_rule_set_starts_on_the_first_of_a_month(db):
    _migrate(db)
    with pytest.raises(psycopg.errors.CheckViolation):
        _rule_set(db, valid_from="2031-01-15")


def test_confirmed_needs_who_and_when(db):
    _migrate(db)
    rule_set_id = _rule_set(db)
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute("UPDATE payroll.rule_sets SET status = 'confirmed' WHERE id = %s", (rule_set_id,))


def test_a_component_code_is_unique_within_its_rule_set(db):
    _migrate(db)
    rule_set_id = _rule_set(db)
    insert = """
        INSERT INTO payroll.components (id, tenant_id, rule_set_id, code, name_en, name_fr, kind, formula_type)
        VALUES (%s, %s, %s, 'BASE', 'Base salary', 'Salaire de base', 'earning', 'fixed')
    """
    db.execute(insert, (str(ULID()), TENANT, rule_set_id))
    with pytest.raises(psycopg.errors.UniqueViolation):
        db.execute(insert, (str(ULID()), TENANT, rule_set_id))
