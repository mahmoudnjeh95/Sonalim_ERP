"""The permission catalog comes from the module manifests; the default roles are derived from it."""
from __future__ import annotations

from core.permissions_registry import ADMINISTRATOR_ROLE_CODE, default_role_catalog, permission_catalog

PHASE_ONE_HR_CODES = {
    "hr.view_presence",
    "hr.manage_presence",
    "hr.import_clock",
    "hr.close_presence",
    "hr.admin_presence",
    "hr.view_positions",
    "hr.manage_positions",
    "hr.admin_positions",
    "hr.view_sensitive",
    "hr.self_service",
}


def _role(code: str) -> dict:
    return next(role for role in default_role_catalog() if role["code"] == code)


def test_hr_declares_every_code_the_spec_lists():
    declared = {entry["permission"] for entry in permission_catalog() if entry["module"] == "hr"}
    assert PHASE_ONE_HR_CODES <= declared
    assert {"hr.view_attendance", "hr.manage_attendance"} <= declared  # kept, phase 2 maps them to presence


def test_view_sensitive_is_granted_deliberately_not_bundled_in_the_hr_role():
    hr_role = _role("hr")["permissions"]
    assert "hr.view_sensitive" not in hr_role
    assert "hr.view_positions" in hr_role and "hr.self_service" in hr_role
    assert "hr.admin_positions" not in hr_role


def test_the_administrator_role_still_holds_every_code():
    assert PHASE_ONE_HR_CODES <= set(_role(ADMINISTRATOR_ROLE_CODE)["permissions"])
