"""0007 closes legacy overlaps before adding the exclusion constraint, so it runs on any database,
and from then on the database itself refuses a second signed contract on the same day."""
from __future__ import annotations

import datetime
from pathlib import Path

import psycopg
import pytest
from ulid import ULID

MIGRATION = Path(__file__).resolve().parents[1] / "migrations" / "0007_hr_contract_overlap_guard.sql"
TENANT = "hr-overlap-guard-test"
D = datetime.date
UTC = datetime.timezone.utc


def _employee(db) -> str:
    employee_id = str(ULID())
    db.execute(
        "INSERT INTO hr.employees (id, tenant_id, employee_no, first_name, last_name, hire_date) VALUES (%s, %s, %s, 'Legacy', 'Row', '2020-01-01')",
        (employee_id, TENANT, employee_id[-8:]),
    )
    return employee_id


def _contract(db, employee_id, start, end=None, status="active", created=datetime.datetime(2020, 1, 1, tzinfo=UTC)) -> str:
    contract_id = str(ULID())
    db.execute(
        "INSERT INTO hr.contracts (id, tenant_id, employee_id, contract_type, start_date, end_date, status, created_at) "
        "VALUES (%s, %s, %s, 'cdi', %s, %s, %s, %s)",
        (contract_id, TENANT, employee_id, start, end, status, created),
    )
    return contract_id


def _row(db, contract_id):
    return db.execute("SELECT start_date, end_date, status, end_reason FROM hr.contracts WHERE id = %s", (contract_id,)).fetchone()


def test_the_database_refuses_a_second_signed_contract_on_the_same_day(db):
    employee_id = _employee(db)
    _contract(db, employee_id, D(2024, 1, 1))
    _contract(db, employee_id, D(2025, 1, 1), status="draft")  # drafts never count
    with pytest.raises(psycopg.errors.ExclusionViolation):
        _contract(db, employee_id, D(2025, 1, 1))


def test_the_migration_closes_legacy_overlaps_then_holds(db):
    db.execute("ALTER TABLE hr.contracts DROP CONSTRAINT hr_contracts_no_overlap")  # the state before 0007
    employee_id = _employee(db)
    first = _contract(db, employee_id, D(2020, 1, 1))                          # open-ended
    second = _contract(db, employee_id, D(2022, 1, 1), D(2024, 12, 31))        # starts inside the first
    twin_old = _contract(db, employee_id, D(2025, 1, 1), created=datetime.datetime(2025, 1, 1, tzinfo=UTC))
    twin_new = _contract(db, employee_id, D(2025, 1, 1), created=datetime.datetime(2025, 1, 2, tzinfo=UTC))
    draft = _contract(db, employee_id, D(2023, 1, 1), status="draft")

    db.execute(MIGRATION.read_text(encoding="utf-8"))

    assert _row(db, first) == (D(2020, 1, 1), D(2021, 12, 31), "active", "other")
    assert _row(db, second) == (D(2022, 1, 1), D(2024, 12, 31), "active", None)
    assert _row(db, twin_old)[2] == "draft"  # same start day: the older one goes back to draft
    assert _row(db, twin_new) == (D(2025, 1, 1), None, "active", None)
    assert _row(db, draft)[2] == "draft"
    with pytest.raises(psycopg.errors.ExclusionViolation):
        _contract(db, employee_id, D(2026, 1, 1))
