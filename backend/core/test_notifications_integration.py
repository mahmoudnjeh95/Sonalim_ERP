"""Integration tests for shared-kernel in-app notifications, against a real database.

Any module writes through notify(); the four /core/notifications routes let a
user list, count and acknowledge their own rows. Nothing here is maintenance-specific
even though the first caller will be the maintenance module.
"""
from __future__ import annotations

import pytest
from ulid import ULID

from core.notifications import (
    list_notifications,
    mark_all_read,
    mark_read,
    notify,
    unread_count,
    users_with_permission,
)

TENANT = "integration-test-notifications"


def _make_user(db, tenant_id=TENANT):
    user_id = str(ULID())
    db.execute(
        "INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')",
        (user_id, tenant_id, f"{user_id}@test.local"),
    )
    return user_id


@pytest.fixture
def two_users(db):
    return _make_user(db), _make_user(db)


def test_notify_writes_one_row_per_distinct_user_and_skips_empty(db, two_users):
    a, b = two_users
    assert notify(db, tenant_id=TENANT, user_ids=[a, b, a, ""], kind="k", title="T", title_fr="T fr", link="/x") == 2


def test_users_with_permission_unions_direct_and_role_grants(db, two_users):
    a, b = two_users
    db.execute("INSERT INTO core.user_permissions (user_id, permission) VALUES (%s, 'maintenance.plan_jobs')", (a,))
    role_id = str(ULID())
    db.execute("INSERT INTO core.roles (id, tenant_id, code, name) VALUES (%s, %s, %s, 'R')", (role_id, TENANT, role_id))
    db.execute("INSERT INTO core.role_permissions (role_id, permission) VALUES (%s, 'maintenance.plan_jobs')", (role_id,))
    db.execute("INSERT INTO core.user_roles (user_id, role_id) VALUES (%s, %s)", (b, role_id))
    assert users_with_permission(db, TENANT, "maintenance.plan_jobs") == sorted([a, b])


def test_list_unread_count_and_mark_read(db, two_users):
    a, _ = two_users
    notify(db, tenant_id=TENANT, user_ids=[a], kind="k", title="1", title_fr="1")
    notify(db, tenant_id=TENANT, user_ids=[a], kind="k", title="2", title_fr="2")
    rows = list_notifications(db, tenant_id=TENANT, user_id=a, unread_only=True)
    assert [r["title"] for r in rows] == ["2", "1"]
    mark_read(db, tenant_id=TENANT, user_id=a, notification_id=rows[0]["id"])
    assert unread_count(db, tenant_id=TENANT, user_id=a) == 1
    mark_all_read(db, tenant_id=TENANT, user_id=a)
    assert unread_count(db, tenant_id=TENANT, user_id=a) == 0
