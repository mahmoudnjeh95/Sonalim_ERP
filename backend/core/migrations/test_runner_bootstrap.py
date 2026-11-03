"""The runner bootstraps a brand new database from docker/postgres/init.sql and leaves any other
database alone, because it runs on the live server at every deploy.

No database needed: the connection is a stand-in that records what it was asked to run.
"""
from __future__ import annotations

import re

from core.migrations import runner

# Only these may run unattended: nothing that alters, drops, or needs a superuser.
IDEMPOTENT_STATEMENT = re.compile(r"^CREATE (SCHEMA|TABLE) IF NOT EXISTS ", re.IGNORECASE)


class _RecordingConnection:
    def __init__(self, tracking_table: str | None) -> None:
        self._tracking_table = tracking_table
        self.executed: list[str] = []

    def execute(self, sql: str):
        self.executed.append(sql)
        return self

    def fetchone(self):
        return (self._tracking_table,)


def test_an_existing_database_runs_no_ddl_and_does_not_read_the_file(monkeypatch) -> None:
    monkeypatch.setattr(runner, "BOOTSTRAP_SQL", runner.REPO_ROOT / "does-not-exist.sql")
    connection = _RecordingConnection(tracking_table="core.module_migrations")

    runner._bootstrap_empty_database(connection)

    assert connection.executed == ["SELECT to_regclass('core.module_migrations')"]


def test_a_new_database_gets_the_bootstrap_script() -> None:
    connection = _RecordingConnection(tracking_table=None)

    runner._bootstrap_empty_database(connection)

    assert connection.executed[1:] == [runner.BOOTSTRAP_SQL.read_text(encoding="utf-8")]


def test_the_bootstrap_script_only_holds_idempotent_creates() -> None:
    statements = [s.strip() for s in runner.BOOTSTRAP_SQL.read_text(encoding="utf-8").split(";") if s.strip()]

    assert statements
    assert [s for s in statements if not IDEMPOTENT_STATEMENT.match(s)] == []
