"""0006 maps the old freely-typed contract_type onto the closed list and takes base_salary over
from salary. This mirrors test_contract_overlap_guard_integration.py's approach for 0007: drop
what 0006 adds, insert legacy-shaped rows, and re-run the committed file inside the rolled-back
transaction, so the mapping it actually performs is what gets asserted (not a copy of its SQL)."""
from __future__ import annotations

import datetime
from pathlib import Path

import psycopg
import pytest
from ulid import ULID

MIGRATION = Path(__file__).resolve().parents[1] / "migrations" / "0006_hr_contract_terms.sql"
TENANT = "hr-contract-terms-migration-test"
D = datetime.date

# The five CHECKs 0006 adds (0001's own status CHECK is not one of them and must survive).
_CHECKS = (
    "hr_contracts_type_check",
    "hr_contracts_pay_frequency_check",
    "hr_contracts_amounts_check",
    "hr_contracts_dates_check",
    "hr_contracts_end_reason_check",
)


def _employee(db) -> str:
    employee_id = str(ULID())
    db.execute(
        "INSERT INTO hr.employees (id, tenant_id, employee_no, first_name, last_name, hire_date) VALUES (%s, %s, %s, 'Legacy', 'Row', '2018-01-01')",
        (employee_id, TENANT, employee_id[-8:]),
    )
    return employee_id


def _legacy_contract(db, employee_id, *, contract_type, start, end=None, salary=150_000, currency="USD") -> str:
    """A row shaped exactly as the pre-0006 schema (and the old, currency-less screen) could
    produce: a freely-typed contract_type, base_salary still at its column default of 0 (0006
    hasn't run yet to take it over from salary), and no trial_end_date / pay_frequency choice."""
    contract_id = str(ULID())
    db.execute(
        "INSERT INTO hr.contracts (id, tenant_id, employee_id, contract_type, start_date, end_date, salary, currency) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
        (contract_id, TENANT, employee_id, contract_type, start, end, salary, currency),
    )
    return contract_id


def _row(db, contract_id):
    return db.execute(
        "SELECT contract_type, base_salary, currency FROM hr.contracts WHERE id = %s", (contract_id,)
    ).fetchone()


def test_the_migration_maps_legacy_contract_types_and_takes_base_salary_from_salary(db):
    # Drop only the five CHECKs 0006 adds (0001's own status CHECK is not one of them and must
    # survive). The columns themselves stay: ADD COLUMN IF NOT EXISTS keeps 0006 safe to re-run,
    # and every row inserted below leaves base_salary unset, so it sits at the column's own
    # default of 0 — exactly the pre-0006 state the take-over UPDATE (base_salary = 0 AND
    # salary > 0) is written to catch.
    for check in _CHECKS:
        db.execute(f"ALTER TABLE hr.contracts DROP CONSTRAINT IF EXISTS {check}")

    # 0007 (applied after 0006 on the shared dev database) refuses two signed contracts of the
    # same employee on overlapping days, so each scenario gets its own employee.
    permanent = _legacy_contract(db, _employee(db), contract_type="permanent", start=D(2018, 1, 1), salary=150_000)
    known_cdd = _legacy_contract(db, _employee(db), contract_type="CDD", start=D(2023, 1, 1), end=D(2023, 12, 31), salary=90_000)
    free_text_with_end = _legacy_contract(db, _employee(db), contract_type="Stage", start=D(2024, 1, 1), end=D(2024, 6, 30), salary=40_000)
    free_text_open_ended = _legacy_contract(db, _employee(db), contract_type="Journalier", start=D(2022, 1, 1), salary=3_500)
    usd_row = _legacy_contract(db, _employee(db), contract_type="permanent", start=D(2019, 1, 1), salary=1_800, currency="USD")
    eur_row = _legacy_contract(db, _employee(db), contract_type="permanent", start=D(2020, 1, 1), salary=500, currency="EUR")
    run_id, payslip_line = str(ULID()), str(ULID())
    db.execute("INSERT INTO hr.payroll_runs (id, tenant_id, period_month, status) VALUES (%s, %s, '2019-01-01', 'calculated')", (run_id, TENANT))
    db.execute(
        "INSERT INTO hr.payroll_items (id, tenant_id, payroll_run_id, employee_id, base_salary, bonuses, deductions, taxes, net_salary, currency) "
        "VALUES (%s, %s, %s, %s, 1800, 0, 0, 0, 1800, 'USD')",
        (payslip_line, TENANT, run_id, _employee(db)),
    )

    db.execute(MIGRATION.read_text(encoding="utf-8"))

    # 'permanent' (a known value, case aside) keeps its meaning: CDI.
    assert _row(db, permanent) == ("cdi", 150_000, "XOF")
    # A value already on the closed list (any case) is just lower-cased.
    assert _row(db, known_cdd) == ("cdd", 90_000, "XOF")
    # A free-text type is not in the closed list: an end date means fixed-term (CDD)...
    assert _row(db, free_text_with_end) == ("cdd", 40_000, "XOF")
    # ...and no end date means CDI, exactly like 'permanent'.
    assert _row(db, free_text_open_ended) == ("cdi", 3_500, "XOF")
    # The old screens always wrote USD for amounts typed in F CFA: relabelled XOF, not converted...
    assert _row(db, usd_row) == ("cdi", 1_800, "XOF")
    # ...and so is the legacy payslip line that copied the contract's label...
    assert db.execute("SELECT currency FROM hr.payroll_items WHERE id = %s", (payslip_line,)).fetchone()[0] == "XOF"
    # ...while any other currency is left as it was.
    assert _row(db, eur_row) == ("cdi", 500, "EUR")

    # The CHECKs are back and hold for the table, not just the rows just mapped: a contract type
    # outside the closed list is refused for a brand new insert too.
    with pytest.raises(psycopg.errors.CheckViolation):
        _legacy_contract(db, _employee(db), contract_type="not-a-type", start=D(2025, 1, 1), salary=100_000)
