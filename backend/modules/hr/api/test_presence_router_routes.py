"""Every phase-2 route exists and is guarded by the permission the plan names. No database."""
from __future__ import annotations

from modules.hr.api.presence_router import router


def _permission_of(route) -> str | None:
    # require_permission(code) returns a closure over `code`; read it back from the dependency.
    for dependency in route.dependant.dependencies:
        for cell in getattr(dependency.call, "__closure__", None) or ():
            value = cell.cell_contents
            if isinstance(value, str) and value.startswith("hr."):
                return value
    return None


def _routes() -> dict[tuple[str, str], str | None]:
    return {(method, route.path): _permission_of(route) for route in router.routes for method in route.methods}


def test_schedule_routes_and_their_permissions():
    expected = {
        ("GET", "/hr/schedules"): "hr.view_presence",
        ("POST", "/hr/schedules"): "hr.manage_presence",
        ("PATCH", "/hr/schedules/{schedule_id}"): "hr.admin_presence",
        ("GET", "/hr/rotation-patterns"): "hr.view_presence",
        ("POST", "/hr/rotation-patterns"): "hr.manage_presence",
        ("PATCH", "/hr/rotation-patterns/{rotation_id}"): "hr.admin_presence",
        ("GET", "/hr/schedule-assignments"): "hr.view_presence",
        ("POST", "/hr/schedule-assignments"): "hr.manage_presence",
        ("PATCH", "/hr/schedule-assignments/{assignment_id}"): "hr.admin_presence",
        ("GET", "/hr/public-holidays"): "hr.view_presence",
        ("POST", "/hr/public-holidays"): "hr.manage_presence",
        ("PATCH", "/hr/public-holidays/{holiday_id}"): "hr.admin_presence",
        ("GET", "/hr/presence/settings"): "hr.view_presence",
        ("PUT", "/hr/presence/settings"): "hr.admin_presence",
    }
    routes = _routes()
    assert {key: routes.get(key) for key in expected} == expected
