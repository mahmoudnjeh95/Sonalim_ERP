from __future__ import annotations

import logging
import os
from pathlib import Path

import psycopg

from core.db import get_connection

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]

MODULE_MIGRATION_DIRS: dict[str, Path] = {
    "core": REPO_ROOT / "core" / "migrations",
    "warehouse": REPO_ROOT / "modules" / "warehouse" / "migrations",
    "production": REPO_ROOT / "modules" / "production" / "migrations",
    "crm": REPO_ROOT / "modules" / "crm" / "migrations",
    "sales": REPO_ROOT / "modules" / "sales" / "migrations",
    "finance": REPO_ROOT / "modules" / "finance" / "migrations",
    "hr": REPO_ROOT / "modules" / "hr" / "migrations",
    "payroll": REPO_ROOT / "modules" / "payroll" / "migrations",
    "procurement": REPO_ROOT / "modules" / "procurement" / "migrations",
    "qc": REPO_ROOT / "modules" / "qc" / "migrations",
    "maintenance": REPO_ROOT / "modules" / "maintenance" / "migrations",
    "scan": REPO_ROOT / "modules" / "scan" / "migrations",
}

# core runs first (procurement's tables FK into core.products/partners/currencies/uoms);
# the others own independent schemas so order among them does not matter.
# qc runs after production: it carries of_id as an opaque column with no foreign
# key, so the order is about readability rather than a hard dependency.
# maintenance runs last: its init migration copies rows out of production.machines
# and its second migration drops that table, both of which need production's
# migrations (which create that table) to have already run.
# payroll runs right after hr: its rows carry hr employee ids as opaque text (no foreign key)
# and it reads hr only through hr's api services, so hr's schema must exist first.
# scan runs last: it holds no foreign key into another module and reads them only
# through their api services.
MODULE_ORDER = ["core", "warehouse", "production", "crm", "sales", "finance", "hr", "payroll", "procurement", "qc", "maintenance", "scan"]


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


# Arbitrary constant key for pg_advisory_lock: app and worker start together on every
# deploy and both call apply_all_migrations; without the lock they can run the same
# file concurrently and one of them crashes on the duplicate tracking row.
MIGRATION_LOCK_KEY = 72_210_001


def apply_all_migrations() -> None:
    with get_connection() as connection:
        connection.execute("SELECT pg_advisory_lock(%s)", (MIGRATION_LOCK_KEY,))
        try:
            _ensure_tracking_table(connection)
            connection.commit()
            # The applied set is re-read per module inside the lock, so whoever waited
            # sees what the first process just applied and skips it.
            for module_name in MODULE_ORDER:
                apply_module_migrations(connection, module_name, MODULE_MIGRATION_DIRS[module_name])
        finally:
            connection.rollback()
            connection.execute("SELECT pg_advisory_unlock(%s)", (MIGRATION_LOCK_KEY,))
            connection.commit()


def pending_migrations(connection: psycopg.Connection) -> list[tuple[str, Path]]:
    """(module_name, file) for every migration file not recorded in core.module_migrations, in apply order. Read-only."""
    if connection.execute("SELECT to_regclass('core.module_migrations')").fetchone()[0] is None:
        applied: set[tuple[str, str]] = set()
    else:
        applied = {
            (row[0], row[1])
            for row in connection.execute("SELECT module_name, version FROM core.module_migrations").fetchall()
        }
    return [
        (module_name, migration_file)
        for module_name in MODULE_ORDER
        if MODULE_MIGRATION_DIRS[module_name].exists()
        for migration_file in sorted(MODULE_MIGRATION_DIRS[module_name].glob("*.sql"))
        if (module_name, migration_file.name) not in applied
    ]


def auto_migrate_enabled() -> bool:
    return os.getenv("AUTO_MIGRATE", "").strip().lower() in {"1", "true", "yes", "on"}


def migrate_on_startup() -> None:
    """Called by the app and the worker at startup.

    With AUTO_MIGRATE on (compose.yaml's default) pending migrations are applied here.
    Set it to false to only list them in the log and apply the SQL from
    `python -m scripts.migration_sql` by hand.
    """
    if auto_migrate_enabled():
        apply_all_migrations()
        return
    try:
        with get_connection() as connection:
            pending = pending_migrations(connection)
    except psycopg.Error as exc:
        logger.warning("Could not check pending migrations: %s", exc)
        return
    if pending:
        logger.warning(
            "%d migration(s) not applied (AUTO_MIGRATE is off) -- generate the SQL with "
            "`python -m scripts.migration_sql`: %s",
            len(pending),
            ", ".join(f"{module_name}/{migration_file.name}" for module_name, migration_file in pending),
        )
