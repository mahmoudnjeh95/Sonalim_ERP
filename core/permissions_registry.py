from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MODULES_DIR = REPO_ROOT / "modules"

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
