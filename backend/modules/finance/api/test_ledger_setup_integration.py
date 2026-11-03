"""Installing the SYSCOHADA seed, and opening and closing accounting periods."""
from __future__ import annotations

import datetime

import pytest
from ulid import ULID

from core.domain.result import Err, Ok
from modules.finance.api.chart_setup_service import ChartSetupService
from modules.finance.api.period_service import PeriodService
from modules.finance.domain.syscohada_chart import CHART, DEFAULT_POSTING_RULES, JOURNALS

TENANT = "integration-test-ledger-setup"
MARCH = datetime.date(2030, 3, 1)


@pytest.fixture
def actor(db) -> str:
    user = str(ULID())
    db.execute(
        "INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')",
        (user, TENANT, f"{user}@test.local"),
    )
    return user


def test_setup_installs_the_chart_journals_and_rules_once(db, actor):
    first = ChartSetupService(db).ensure_defaults(tenant_id=TENANT, actor_id=actor)
    assert first == {"accounts": len(CHART), "journals": len(JOURNALS), "posting_rules": len(DEFAULT_POSTING_RULES)}
    again = ChartSetupService(db).ensure_defaults(tenant_id=TENANT, actor_id=actor)
    assert again == {"accounts": 0, "journals": 0, "posting_rules": 0}
    statuses = {row[0] for row in db.execute("SELECT status FROM finance.posting_rules WHERE tenant_id = %s", (TENANT,))}
    assert statuses == {"to_confirm"}
    audited = db.execute(
        "SELECT count(*) FROM core.audit_log WHERE tenant_id = %s AND action = 'ledger_setup.applied'", (TENANT,)
    ).fetchone()[0]
    assert audited == 1


def test_opening_a_year_creates_twelve_open_periods(db, actor):
    periods = PeriodService(db)
    assert isinstance(periods.open_fiscal_year(tenant_id=TENANT, actor_id=actor, year=2030), Ok)
    listed = periods.list_periods(tenant_id=TENANT, year=2030)
    assert [p["period"] for p in listed] == [datetime.date(2030, month, 1) for month in range(1, 13)]
    assert {p["status"] for p in listed} == {"open"}
    again = periods.open_fiscal_year(tenant_id=TENANT, actor_id=actor, year=2030)
    assert isinstance(again, Err) and again.code == "FISCAL_YEAR_EXISTS"


def test_a_closed_period_refuses_postings_until_reopened(db, actor):
    periods = PeriodService(db)
    periods.open_fiscal_year(tenant_id=TENANT, actor_id=actor, year=2030)
    assert isinstance(periods.close_period(tenant_id=TENANT, actor_id=actor, period=MARCH), Ok)
    refused = periods.ensure_open(tenant_id=TENANT, day=datetime.date(2030, 3, 17))
    assert isinstance(refused, Err) and refused.code == "PERIOD_CLOSED" and refused.message_fr
    twice = periods.close_period(tenant_id=TENANT, actor_id=actor, period=MARCH)
    assert isinstance(twice, Err) and twice.code == "INVALID_TRANSITION"
    assert isinstance(periods.reopen_period(tenant_id=TENANT, actor_id=actor, period=MARCH), Ok)
    assert periods.ensure_open(tenant_id=TENANT, day=datetime.date(2030, 3, 17)) == Ok(MARCH)
    actions = {
        row[0]
        for row in db.execute("SELECT action FROM core.audit_log WHERE tenant_id = %s AND entity_type = 'period'", (TENANT,))
    }
    assert actions == {"period.closed", "period.reopened"}


def test_a_date_without_a_period_is_period_missing(db, actor):
    refused = PeriodService(db).ensure_open(tenant_id=TENANT, day=datetime.date(2031, 1, 5))
    assert isinstance(refused, Err) and refused.code == "PERIOD_MISSING"


def test_a_period_is_named_by_its_first_day(db, actor):
    periods = PeriodService(db)
    periods.open_fiscal_year(tenant_id=TENANT, actor_id=actor, year=2030)
    refused = periods.close_period(tenant_id=TENANT, actor_id=actor, period=datetime.date(2030, 3, 2))
    assert isinstance(refused, Err) and refused.code == "INVALID_PERIOD"
