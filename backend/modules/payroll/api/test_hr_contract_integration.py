"""Pins the hr services payroll depends on to the cross-phase contract's names and shapes."""
from __future__ import annotations

import datetime

from modules.hr.api.payroll_snapshot_service import PayrollSnapshotService
from modules.hr.api.presence_service import PresenceService

EMPTY_TENANT = "payroll-contract-empty-tenant"
PERIOD = datetime.date(2031, 9, 1)


def test_the_snapshot_service_answers_with_the_contract_keywords(db):
    assert PayrollSnapshotService(db).employees_for_period(tenant_id=EMPTY_TENANT, period=PERIOD, employee_ids=None) == []


def test_the_presence_service_answers_with_the_contract_keywords(db):
    presence = PresenceService(db)
    assert presence.month_summary(tenant_id=EMPTY_TENANT, period=PERIOD, employee_ids=[]) == []
    assert presence.is_month_closed(tenant_id=EMPTY_TENANT, period=PERIOD) in (True, False)
