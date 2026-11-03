"""A throwaway FastAPI app carrying the hr router, for tests that go through HTTP.

The session is overridden, and every connection the router or the permission check opens is the
`db` fixture's rolled-back one (commit and rollback made no-ops), so nothing reaches the
development data.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from ulid import ULID

from core.tenancy import TenantContext, require_session

TENANT = "hr-router-test"


class _Connection:
    """The fixture's connection, with the transaction left to the fixture."""

    def __init__(self, connection) -> None:
        self._connection = connection

    def __getattr__(self, name):
        return getattr(self._connection, name)

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> bool:
        return False


@pytest.fixture
def hr_api(db, monkeypatch):
    pytest.importorskip("httpx", reason="the FastAPI test client needs httpx (requirements-dev.txt)")
    from fastapi.testclient import TestClient

    from modules.hr.api import router as router_module

    user_id = str(ULID())
    db.execute(
        "INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')",
        (user_id, TENANT, f"{user_id}@test.local"),
    )
    wrapped = _Connection(db)
    monkeypatch.setattr(router_module, "get_connection", lambda: wrapped)
    monkeypatch.setattr("core.tenancy.get_connection", lambda: wrapped)

    app = FastAPI()
    app.include_router(router_module.router)
    app.dependency_overrides[require_session] = lambda: TenantContext(tenant_id=TENANT, user_id=user_id, session_token="t")

    def grant(*permissions: str) -> None:
        for permission in permissions:
            db.execute(
                "INSERT INTO core.user_permissions (user_id, permission) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (user_id, permission),
            )

    return SimpleNamespace(client=TestClient(app), grant=grant, db=db, user_id=user_id, tenant_id=TENANT)
