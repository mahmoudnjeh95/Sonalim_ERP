from __future__ import annotations

import json
from pathlib import Path

import psycopg
from ulid import ULID

REPO_ROOT = Path(__file__).resolve().parents[1]
MODULES_DIR = REPO_ROOT / "modules"

# Human-facing names for the default per-module roles. core is deliberately
# excluded — its permissions (partner/product catalog admin, exchange rates,
# core.manage_permissions) are cross-cutting, not a single job function, so
# they stay opt-in via direct grant rather than bundled into a default role.
MODULE_LABELS = {
    "crm": "CRM",
    "finance": "Finance",
    "hr": "Ressources humaines",
    "maintenance": "Maintenance",
    "payroll": "Paie",
    "procurement": "Achats",
    "production": "Production",
    "qc": "Qualité",
    "sales": "Ventes",
    "warehouse": "Entrepôt",
}

ADMINISTRATOR_ROLE_CODE = "administrateur"

# Permissions that open personal data (salary, national id, bank details). Like admin_*, they
# are granted one at a time on purpose and never bundled into a module's everyday role.
DELIBERATE_GRANT_PERMISSIONS = {"hr.view_sensitive"}

# Permissions core itself defines that aren't tied to any business module.
CORE_PERMISSIONS = [
    "core.manage_permissions",
    "core.view_partners",
    "core.manage_partners",
    "core.admin_partners",
    "core.view_exchange_rates",
    "core.manage_exchange_rates",
    "core.view_products",
    "core.manage_products",
    "core.view_audit_log",
    "core.manage_report_options",
]


def permission_catalog() -> list[dict[str, str]]:
    """Every grantable permission string: core's own, plus each module.json's declared list.

    Reuses the manifests modules already ship (see the architecture skill's
    "Module Manifest" section) instead of maintaining a second copy of the
    same list somewhere else.
    """
    catalog = [{"module": "core", "permission": permission} for permission in CORE_PERMISSIONS]

    for manifest_path in sorted(MODULES_DIR.glob("*/module.json")):
        manifest = json.loads(manifest_path.read_text())
        for permission in manifest.get("permissions", []):
            catalog.append({"module": manifest["name"], "permission": permission})

    return catalog


def default_role_catalog() -> list[dict[str, object]]:
    """Default role bundles: one per business module (its view_*/manage_* and other
    non-admin_* permissions) plus a full-access "administrateur" role.

    Derived from permission_catalog() rather than a second hand-maintained list,
    so a module's declared permissions stay the single source of truth. admin_*
    permissions are left out of the per-module roles — they're the ones worth
    granting deliberately, one at a time, not bundled by default.
    """
    catalog = permission_catalog()

    roles: list[dict[str, object]] = []
    for module, label in MODULE_LABELS.items():
        permissions = [
            entry["permission"]
            for entry in catalog
            if entry["module"] == module
            and not entry["permission"].split(".", 1)[1].startswith("admin_")
            and entry["permission"] not in DELIBERATE_GRANT_PERMISSIONS
        ]
        if not permissions:
            continue
        roles.append(
            {
                "code": module,
                "name": label,
                "description": f"Accès courant au module {label} (hors permissions d'administration).",
                "permissions": permissions,
            }
        )

    roles.append(
        {
            "code": ADMINISTRATOR_ROLE_CODE,
            "name": "Administrateur",
            "description": "Accès complet à toutes les permissions déclarées, tous modules confondus.",
            "permissions": [entry["permission"] for entry in catalog],
        }
    )
    return roles


def ensure_default_roles(connection: psycopg.Connection, tenant_id: str) -> dict[str, str]:
    """Idempotently upserts the default role catalog for a tenant. Returns {code: role_id}."""
    role_ids: dict[str, str] = {}
    for role in default_role_catalog():
        code = role["code"]
        row = connection.execute(
            "SELECT id FROM core.roles WHERE tenant_id = %s AND code = %s",
            (tenant_id, code),
        ).fetchone()
        if row is None:
            role_id = str(ULID())
            connection.execute(
                """
                INSERT INTO core.roles (id, tenant_id, code, name, description)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (role_id, tenant_id, code, role["name"], role["description"]),
            )
        else:
            role_id = row[0]
            connection.execute(
                "UPDATE core.roles SET name = %s, description = %s WHERE id = %s",
                (role["name"], role["description"], role_id),
            )
        role_ids[code] = role_id

        for permission in role["permissions"]:
            connection.execute(
                """
                INSERT INTO core.role_permissions (role_id, permission)
                VALUES (%s, %s)
                ON CONFLICT (role_id, permission) DO NOTHING
                """,
                (role_id, permission),
            )
    return role_ids
