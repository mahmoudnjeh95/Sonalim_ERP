"""The `ledger` fixture: a tenant with the SYSCOHADA seed and fiscal year 2030 open, inside the
rolled-back `db` connection of backend/conftest.py (so it skips when no database is reachable)."""
from __future__ import annotations

import pytest
from ulid import ULID

LEDGER_TENANT = "integration-test-ledger"
LEDGER_YEAR = 2030


@pytest.fixture
def ledger(db) -> dict:
    from core.domain.result import Ok
    from modules.finance.api.chart_setup_service import ChartSetupService
    from modules.finance.api.period_service import PeriodService

    actor = str(ULID())
    db.execute(
        "INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')",
        (actor, LEDGER_TENANT, f"{actor}@test.local"),
    )
    ChartSetupService(db).ensure_defaults(tenant_id=LEDGER_TENANT, actor_id=actor)
    opened = PeriodService(db).open_fiscal_year(tenant_id=LEDGER_TENANT, actor_id=actor, year=LEDGER_YEAR)
    assert isinstance(opened, Ok), opened
    return {"db": db, "tenant": LEDGER_TENANT, "actor": actor, "year": LEDGER_YEAR}
