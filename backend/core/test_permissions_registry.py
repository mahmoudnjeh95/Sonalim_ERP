"""The permission catalog comes from the module manifests; the default roles are derived from it."""
from __future__ import annotations

from core.permissions_registry import (
    ADMINISTRATOR_ROLE_CODE,
    DELIBERATE_GRANT_PERMISSIONS,
    DELIBERATE_GRANT_ROLES,
    MODULE_LABELS,
    default_role_catalog,
    permission_catalog,
)

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
}


def _role(code: str) -> dict:
    return next(role for role in default_role_catalog() if role["code"] == code)


_SINGLE_PURPOSE = {role["code"] for role in DELIBERATE_GRANT_ROLES}


def _everyday_roles() -> list[dict]:
    """The per-module roles: not administrateur, not a single-purpose deliberate-grant role."""
    return [r for r in default_role_catalog() if r["code"] != ADMINISTRATOR_ROLE_CODE and r["code"] not in _SINGLE_PURPOSE]


def test_hr_declares_every_code_the_spec_lists():
    declared = {entry["permission"] for entry in permission_catalog() if entry["module"] == "hr"}
    assert PHASE_ONE_HR_CODES <= declared
    assert {"hr.view_attendance", "hr.manage_attendance"} <= declared  # kept, phase 2 maps them to presence


def test_view_sensitive_is_granted_deliberately_not_bundled_in_the_hr_role():
    hr_role = _role("hr")["permissions"]
    assert "hr.view_sensitive" not in hr_role
    assert "hr.view_positions" in hr_role
    assert "hr.admin_positions" not in hr_role


def test_the_administrator_role_still_holds_every_code():
    assert PHASE_ONE_HR_CODES <= set(_role(ADMINISTRATOR_ROLE_CODE)["permissions"])


# --- the admin_* convention the whole role split rests on ---------------------
#
# default_role_catalog() decides membership by string-prefix: a module's everyday
# role gets its codes except those whose name (after the first dot) starts with
# admin_, and except DELIBERATE_GRANT_PERMISSIONS. These tests pin that rule so a
# future edit can't quietly widen an everyday role.


def _tail(permission: str) -> str:
    return permission.split(".", 1)[1]


def test_every_module_role_excludes_exactly_its_admin_codes_and_nothing_else():
    catalog = permission_catalog()
    for role in _everyday_roles():
        declared = {e["permission"] for e in catalog if e["module"] == role["code"]}
        bundled = set(role["permissions"])
        expected = {
            p for p in declared
            if not _tail(p).startswith("admin_") and p not in DELIBERATE_GRANT_PERMISSIONS
        }
        assert bundled == expected, f"{role['code']} role drifted from the admin_* rule"


def test_no_everyday_role_bundles_an_admin_code():
    for role in _everyday_roles():
        leaked = sorted(p for p in role["permissions"] if _tail(p).startswith("admin_"))
        assert not leaked, f"{role['code']} role bundles admin codes: {leaked}"


def test_administrator_holds_every_declared_permission():
    everything = {entry["permission"] for entry in permission_catalog()}
    assert set(_role(ADMINISTRATOR_ROLE_CODE)["permissions"]) == everything


def test_held_back_codes_reach_administrateur_but_no_everyday_role():
    admin = set(_role(ADMINISTRATOR_ROLE_CODE)["permissions"])
    for permission in DELIBERATE_GRANT_PERMISSIONS:
        assert permission in admin, f"{permission} must stay grantable via administrateur"
        for role in _everyday_roles():
            assert permission not in role["permissions"], f"{role['code']} bundles {permission}"


def test_unlocking_a_validated_shift_is_an_admin_right():
    """Reopening a validated shift rewrites already-posted stock -- admin_*, not everyday."""
    assert "production.admin_unlock_validated" in {e["permission"] for e in permission_catalog()}
    assert "production.admin_unlock_validated" not in _role("production")["permissions"]
    # The shift. segment would have defeated the prefix rule (tail = "shift.admin_...").
    assert _tail("production.admin_unlock_validated").startswith("admin_")


def test_running_payroll_is_not_bundled_into_the_everyday_hr_role():
    hr_role = _role("hr")["permissions"]
    assert "hr.view_payroll" not in hr_role and "hr.manage_payroll" not in hr_role
    assert "payroll.view_runs" in _role("payroll")["permissions"]


def test_self_service_is_gone_from_the_catalog():
    """It gated nothing; 0025 prunes the rows it left behind."""
    assert "hr.self_service" not in {entry["permission"] for entry in permission_catalog()}


def test_every_module_with_permissions_has_a_default_role():
    """A new module's codes must not be reachable only through administrateur by accident."""
    catalog = permission_catalog()
    modules = {e["module"] for e in catalog if e["module"] != "core"}
    roles = {r["code"] for r in default_role_catalog()}
    assert modules <= roles, f"no default role for: {sorted(modules - roles)}"
    assert modules <= set(MODULE_LABELS), f"missing MODULE_LABELS entry for: {sorted(modules - set(MODULE_LABELS))}"


def test_reading_with_claude_is_granted_through_its_own_role_only():
    """Claude gets the photos (workers' names on them): never bundled into the scan role."""
    assert "scan.use_cloud_reader" in {e["permission"] for e in permission_catalog()}
    assert "scan.use_cloud_reader" not in _role("scan")["permissions"]
    assert _role("scan_cloud")["permissions"] == ["scan.use_cloud_reader"]
    assert "scan.use_cloud_reader" in _role(ADMINISTRATOR_ROLE_CODE)["permissions"]


def test_single_purpose_roles_hold_only_declared_deliberate_codes():
    declared = {e["permission"] for e in permission_catalog()}
    for role in DELIBERATE_GRANT_ROLES:
        assert set(role["permissions"]) <= declared & DELIBERATE_GRANT_PERMISSIONS, role["code"]
