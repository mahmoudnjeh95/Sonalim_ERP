"""`user_has_permission` is the check behind every guarded endpoint, callable from code
that needs a permission chosen at run time (a per-section edit right)."""
from __future__ import annotations

import pytest
from ulid import ULID

from core.tenancy import user_has_permission

TENANT = "permission-test"


@pytest.fixture
def user(db) -> str:
    user_id = str(ULID())
    db.execute(
        "INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')",
        (user_id, TENANT, f"{user_id}@test.local"),
    )
    return user_id


def test_a_user_without_the_permission_does_not_have_it(db, user):
    assert user_has_permission(db, user_id=user, permission="production.shift.edit.runs") is False


def test_a_direct_grant_counts(db, user):
    db.execute("INSERT INTO core.user_permissions (user_id, permission) VALUES (%s, 'production.shift.edit.runs')", (user,))
    assert user_has_permission(db, user_id=user, permission="production.shift.edit.runs") is True
    assert user_has_permission(db, user_id=user, permission="production.shift.edit.packing") is False


def test_a_permission_held_through_a_role_counts(db, user):
    role_id = str(ULID())
    db.execute(
        "INSERT INTO core.roles (id, tenant_id, code, name) VALUES (%s, %s, 'chef-conditionnement', 'Chef conditionnement')",
        (role_id, TENANT),
    )
    db.execute("INSERT INTO core.role_permissions (role_id, permission) VALUES (%s, 'production.shift.edit.packing')", (role_id,))
    db.execute("INSERT INTO core.user_roles (user_id, role_id) VALUES (%s, %s)", (user, role_id))
    assert user_has_permission(db, user_id=user, permission="production.shift.edit.packing") is True
    assert user_has_permission(db, user_id=user, permission="production.shift.edit.runs") is False
