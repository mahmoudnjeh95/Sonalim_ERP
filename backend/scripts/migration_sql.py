"""Print, as one SQL transaction, the migrations a database has not applied yet.

Deploys never migrate the server (AUTO_MIGRATE is off there), so new migration
files are run by hand with the SQL this prints:

    # on the server, after the deploy: exact list from the live core.module_migrations
    docker compose exec -T app python -m scripts.migration_sql > pending.sql
    docker compose exec -T postgres psql -U erp -d erp < pending.sql

    # locally, no database needed: files added since the last deploy
    .venv/Scripts/python -m scripts.migration_sql --since origin/huge_production_migration > pending.sql

Each file is followed by its core.module_migrations row, so the runner never
applies it again; any error rolls the whole batch back.
"""

from __future__ import annotations

import argparse
import datetime
import subprocess
import sys

from dotenv import load_dotenv

from core.db import get_connection
from core.migrations.runner import MODULE_MIGRATION_DIRS, MODULE_ORDER, pending_migrations


def _git(cwd, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True, encoding="utf-8").stdout


def _pending_from_database() -> list[tuple[str, str, str]]:
    with get_connection() as connection:
        pending = pending_migrations(connection)
    return [(module_name, path.name, path.read_text(encoding="utf-8")) for module_name, path in pending]


def _pending_since(ref: str) -> list[tuple[str, str, str]]:
    """Migration files committed at HEAD but absent at `ref`, with their HEAD content."""
    pending = []
    for module_name in MODULE_ORDER:
        directory = MODULE_MIGRATION_DIRS[module_name]
        if not directory.exists():
            continue
        at_ref = set(_git(directory, "ls-tree", "--name-only", ref, ".").split())
        at_head = sorted(name for name in _git(directory, "ls-tree", "--name-only", "HEAD", ".").split() if name.endswith(".sql"))
        edited = _git(directory, "diff", "--name-only", "--diff-filter=M", ref, "HEAD", "--", ".").split()
        for path in edited:
            print(f"warning: {module_name}/{path.rsplit('/', 1)[-1]} was edited after {ref}; the edit will not be re-run", file=sys.stderr)
        for name in at_head:
            if name not in at_ref:
                pending.append((module_name, name, _git(directory, "show", f"HEAD:./{name}")))
    return pending


def render(pending: list[tuple[str, str, str]], source: str) -> str:
    if not pending:
        return f"-- No pending migrations ({source}).\n"
    lines = [
        f"-- Sonalim ERP pending migrations, {source}, generated {datetime.date.today().isoformat()}",
        *(f"--   {module_name}/{name}" for module_name, name, _ in pending),
        "\\set ON_ERROR_STOP on",
        "BEGIN;",
        "",
    ]
    for module_name, name, sql in pending:
        body = sql.rstrip()
        if not body.endswith(";"):
            body += "\n;"
        lines += [
            f"-- ===== {module_name}/{name}",
            body,
            f"INSERT INTO core.module_migrations (module_name, version) VALUES ('{module_name}', '{name}') ON CONFLICT DO NOTHING;",
            "",
        ]
    lines.append("COMMIT;")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--since", metavar="GIT_REF", help="list files added since this ref instead of asking the database")
    args = parser.parse_args()
    load_dotenv()  # local runs; the server container already has DATABASE_URL
    sys.stdout.reconfigure(encoding="utf-8")
    if args.since:
        pending, source = _pending_since(args.since), f"added since {args.since}"
    else:
        pending, source = _pending_from_database(), "not recorded in core.module_migrations"
    sys.stdout.write(render(pending, source))


if __name__ == "__main__":
    main()
