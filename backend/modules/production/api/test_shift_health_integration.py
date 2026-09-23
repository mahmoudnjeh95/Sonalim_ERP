"""Shift lifecycle health: submission funnel, time-to-validate, return rate, completeness."""
from __future__ import annotations

import datetime

import pytest
from ulid import ULID

from core.domain.result import Ok
from modules.production.api.shift_health_service import ShiftHealthService
from modules.production.api.shift_report_service import ShiftReportService
from modules.production.api.shift_validation_service import ShiftValidationService
from modules.production.domain.shift_report import SECTION_KEYS

TENANT = "shift-health-test"
DAY = datetime.date(2030, 8, 1)


@pytest.fixture
def env(db):
    actor = str(ULID())
    work_center = str(ULID())
    db.execute("INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')", (actor, TENANT, f"{actor}@test.local"))
    db.execute("INSERT INTO production.work_centers (id, tenant_id, code, name) VALUES (%s, %s, 'SH-WC', 'Line')", (work_center, TENANT))
    return {"actor": actor, "work_center": work_center}


def _ok(result):
    assert isinstance(result, Ok), getattr(result, "message", result)
    return result.value


def _open_shift(db, env, *, shift="morning", report_date=DAY) -> str:
    return _ok(ShiftReportService(db).open_shift(
        tenant_id=TENANT, actor_id=env["actor"], work_center_id=env["work_center"], report_date=report_date, shift=shift,
    ))["id"]


def _submitted_shift(db, env, *, shift="morning") -> str:
    """Every section declared 'nothing to report', so the shift is handed in."""
    shift_id = _open_shift(db, env, shift=shift)
    service = ShiftReportService(db)
    for key in SECTION_KEYS:
        _ok(service.declare_nothing(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key=key))
    return shift_id


def _mark_validated(db, shift_id, *, minutes_after_submit: int) -> None:
    """Validation proper needs stock to post; the lifecycle facts are all this reads."""
    db.execute(
        "UPDATE production.shift_reports SET status = 'validated', validated_at = submitted_at + make_interval(mins => %s) "
        "WHERE id = %s",
        (minutes_after_submit, shift_id),
    )


def _health(db, *, date_from="2030-08-01", date_to="2030-08-01") -> dict:
    return ShiftHealthService(db).get_shift_health(tenant_id=TENANT, date_from=date_from, date_to=date_to)


def test_funnel_counts_every_status_in_range(db, env):
    _open_shift(db, env, shift="morning")
    _submitted_shift(db, env, shift="afternoon")
    _mark_validated(db, _submitted_shift(db, env, shift="night"), minutes_after_submit=30)

    by_status = {row["status"]: row["count"] for row in _health(db)["funnel"]}

    assert by_status == {"open": 1, "submitted": 1, "validated": 1}


def test_time_to_validate_only_counts_validated_shifts(db, env):
    _mark_validated(db, _submitted_shift(db, env, shift="morning"), minutes_after_submit=30)
    _mark_validated(db, _submitted_shift(db, env, shift="afternoon"), minutes_after_submit=90)
    _mark_validated(db, _submitted_shift(db, env, shift="night"), minutes_after_submit=600)
    _open_shift(db, env, shift="morning", report_date=DAY)  # still open: no submitted_at, not in the sample

    ttv = _health(db)["time_to_validate_minutes"]

    assert ttv["sample_size"] == 3
    assert round(ttv["median"]) == 90
    assert round(ttv["average"]) == 240


def test_time_to_validate_empty_when_nothing_validated(db, env):
    _open_shift(db, env)
    ttv = _health(db)["time_to_validate_minutes"]
    assert ttv == {"median": None, "average": None, "sample_size": 0}


def test_return_rate_counts_returns_even_after_the_team_resubmits(db, env):
    returned = _submitted_shift(db, env, shift="morning")
    _submitted_shift(db, env, shift="afternoon")  # handed in, never sent back
    _open_shift(db, env, shift="night")  # never handed in: not in the denominator
    _ok(ShiftValidationService(db).reject_sections(
        tenant_id=TENANT, actor_id=env["actor"], shift_report_id=returned, section_keys=["runs"], reason="missing data",
    ))
    # The team answers: the section's return_reason is cleared, but the return happened.
    _ok(ShiftReportService(db).declare_nothing(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=returned, section_key="runs"))

    by_key = {row["section_key"]: row for row in _health(db)["return_rate_by_section"]}

    assert (by_key["runs"]["returned_count"], by_key["runs"]["total_count"]) == (1, 2)
    assert by_key["runs"]["return_rate_pct"] == 50.0
    assert by_key["waste_production"]["returned_count"] == 0
    assert by_key["waste_production"]["return_rate_pct"] == 0.0


def test_a_section_saved_with_a_reason_is_not_a_return(db, env):
    """Revision reasons are edit notes (team or validator), not returns."""
    shift_id = _submitted_shift(db, env)
    _ok(ShiftReportService(db).save_section(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id,
                                            section_key="energy", payload={"energy": {"fuel_quantity": 5}}, reason="late figure"))
    by_key = {row["section_key"]: row for row in _health(db)["return_rate_by_section"]}
    assert by_key["energy"]["returned_count"] == 0


def test_completeness_counts_non_empty_sections(db, env):
    _submitted_shift(db, env)  # every section now non-empty
    _open_shift(db, env, shift="night")  # nothing touched yet

    completeness = _health(db)["completeness"]

    assert completeness["total_sections"] == len(SECTION_KEYS)
    assert completeness["shift_count"] == 2
    assert completeness["average_sections_filled"] == len(SECTION_KEYS) / 2


def test_empty_window_returns_zeroed_shape_not_an_error(db, env):
    health = _health(db, date_from="2030-01-01", date_to="2030-01-31")
    assert health["funnel"] == []
    assert health["time_to_validate_minutes"]["sample_size"] == 0
    assert health["completeness"] == {"average_sections_filled": None, "total_sections": len(SECTION_KEYS), "shift_count": 0}
    assert all(row["return_rate_pct"] is None for row in health["return_rate_by_section"])
