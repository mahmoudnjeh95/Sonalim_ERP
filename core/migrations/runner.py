from __future__ import annotations

from pathlib import Path

import psycopg

from core.db import get_connection

REPO_ROOT = Path(__file__).resolve().parents[2]

MODULE_MIGRATION_DIRS: dict[str, Path] = {
    "core": REPO_ROOT / "core" / "migrations",
    "warehouse": REPO_ROOT / "modules" / "warehouse" / "migrations",
    "production": REPO_ROOT / "modules" / "production" / "migrations",
    "crm": REPO_ROOT / "modules" / "crm" / "migrations",
    "sales": REPO_ROOT / "modules" / "sales" / "migrations",
    "finance": REPO_ROOT / "modules" / "finance" / "migrations",
    "hr": REPO_ROOT / "modules" / "hr" / "migrations",
    "procurement": REPO_ROOT / "modules" / "procurement" / "migrations",
}

# core runs first (procurement's tables FK into core.products/partners/currencies/uoms);
# the others own independent schemas so order among them does not matter.
MODULE_ORDER = ["core", "warehouse", "production", "crm", "sales", "finance", "hr", "procurement"]


def _ensure_tracking_table(connection: psycopg.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS core.module_migrations (
            module_name TEXT NOT NULL,
            version TEXT NOT NULL,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (module_name, version)
        )
        """
    )


def apply_module_migrations(connection: psycopg.Connection, module_name: str, migrations_dir: Path) -> None:
    if not migrations_dir.exists():
        return

    applied = {
        row[0]
        for row in connection.execute(
            "SELECT version FROM core.module_migrations WHERE module_name = %s",
            (module_name,),
        ).fetchall()
    }

    for migration_file in sorted(migrations_dir.glob("*.sql")):
        version = migration_file.name
        if version in applied:
            continue
        connection.execute(migration_file.read_text(encoding="utf-8"))
        connection.execute(
            "INSERT INTO core.module_migrations (module_name, version) VALUES (%s, %s)",
            (module_name, version),
        )
        connection.commit()


def apply_all_migrations() -> None:
    with get_connection() as connection:
        _ensure_tracking_table(connection)
        connection.commit()
        for module_name in MODULE_ORDER:
            apply_module_migrations(connection, module_name, MODULE_MIGRATION_DIRS[module_name])
