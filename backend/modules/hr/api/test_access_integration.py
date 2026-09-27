"""hr.view_sensitive decides who reads and who writes pay, national ids and bank details."""
from __future__ import annotations

import pytest
from fastapi import HTTPException
from ulid import ULID

from core.tenancy import TenantContext
from modules.hr.api.access import can_view_sensitive, require_sensitive_for

TENANT = "hr-access-test"


@pytest.fixture
def caller(db):
    user_id = str(ULID())
    db.execute(
        "INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')",
        (user_id, TENANT, f"{user_id}@test.local"),
    )
    return TenantContext(tenant_id=TENANT, user_id=user_id, session_token="t")


def test_a_write_without_sensitive_fields_needs_nothing_more(db, caller):
    require_sensitive_for(db, caller, [])


def test_a_write_with_a_sensitive_field_needs_hr_view_sensitive(db, caller):
    with pytest.raises(HTTPException) as refused:
        require_sensitive_for(db, caller, ["national_id"])
    assert refused.value.status_code == 403
    assert refused.value.detail["code"] == "FORBIDDEN"
    assert refused.value.detail["message_fr"] == "permission manquante : hr.view_sensitive"


def test_the_right_opens_both_reading_and_writing(db, caller):
    assert can_view_sensitive(db, caller) is False
    db.execute("INSERT INTO core.user_permissions (user_id, permission) VALUES (%s, 'hr.view_sensitive')", (caller.user_id,))
    assert can_view_sensitive(db, caller) is True
    require_sensitive_for(db, caller, ["base_salary"])


def test_the_right_can_come_from_a_role(db, caller):
    role_id = str(ULID())
    db.execute("INSERT INTO core.roles (id, tenant_id, code, name) VALUES (%s, %s, %s, 'Paie')", (role_id, TENANT, f"paie-{role_id}"))
    db.execute("INSERT INTO core.role_permissions (role_id, permission) VALUES (%s, 'hr.view_sensitive')", (role_id,))
    db.execute("INSERT INTO core.user_roles (user_id, role_id) VALUES (%s, %s)", (caller.user_id, role_id))
    assert can_view_sensitive(db, caller) is True
