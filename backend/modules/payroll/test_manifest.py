"""The payroll module is declared like every other module: manifest, load order, permissions."""
from __future__ import annotations

import json
import pathlib

from core.migrations.runner import MODULE_MIGRATION_DIRS, MODULE_ORDER
from core.permissions_registry import MODULE_LABELS, permission_catalog

MODULE_DIR = pathlib.Path(__file__).resolve().parent

PERMISSIONS = [
    "payroll.view_runs",
    "payroll.calculate_runs",
    "payroll.approve_runs",
    "payroll.pay_runs",
    "payroll.reverse_runs",
    "payroll.manage_inputs",
    "payroll.view_rules",
    "payroll.manage_rules",
    "payroll.confirm_rules",
    "payroll.view_declarations",
    "payroll.admin_payslips",
]


def test_payroll_migrates_right_after_hr():
    assert MODULE_ORDER.index("payroll") == MODULE_ORDER.index("hr") + 1
    assert MODULE_MIGRATION_DIRS["payroll"].resolve() == MODULE_DIR / "migrations"


def test_the_manifest_declares_the_spec_permissions_and_contract():
    manifest = json.loads((MODULE_DIR / "module.json").read_text(encoding="utf-8"))
    assert manifest["name"] == "payroll"
    assert manifest["depends"] == ["core", "hr"]
    assert manifest["permissions"] == PERMISSIONS
    assert set(manifest["provides_api"]) == {"PayrollPostingService", "PayrollReportService"}
    assert manifest["publishes_events"] == ["payroll.run.approved", "payroll.run.paid", "payroll.run.reversed"]


def test_payroll_permissions_are_grantable_and_have_a_role_label():
    granted = {entry["permission"] for entry in permission_catalog() if entry["module"] == "payroll"}
    assert granted == set(PERMISSIONS)
    assert MODULE_LABELS["payroll"] == "Paie"
