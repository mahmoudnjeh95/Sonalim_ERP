"""Migrations run on the live server at every deploy (AUTO_MIGRATE), so they may
change the schema and derive data from rows already there -- but never load
test or demo data. Seed data belongs in scripts/seed_*.py, which no deploy runs.

No database needed: this reads the SQL files.
"""
from __future__ import annotations

import re

import pytest

from core.migrations.runner import MODULE_MIGRATION_DIRS, REPO_ROOT

# Literal rows: `INSERT INTO t (...) VALUES (...)`. A backfill derived from
# existing rows is `INSERT ... SELECT` and stays allowed.
LITERAL_INSERT = re.compile(r"INSERT\s+INTO\s+[\w.\"]+\s*(\([^)]*\))?\s*VALUES", re.IGNORECASE)

# Anything pointing at a demo/test tenant, user or fixture.
TEST_DATA_MARKERS = re.compile(r"demo@|sonalim-erp\.local|integration-test|['\"]demo[-_]|test[-_]tenant", re.IGNORECASE)

# Reference data, not test data: the currency list every tenant needs.
LITERAL_INSERT_ALLOWED = {"core/migrations/0006_core_currencies_and_exchange_rates.sql"}


def _migration_files():
    for directory in MODULE_MIGRATION_DIRS.values():
        if directory.exists():
            yield from sorted(directory.glob("*.sql"))


def _without_comments(sql: str) -> str:
    return re.sub(r"--[^\n]*", "", sql)


@pytest.mark.parametrize("path", list(_migration_files()), ids=lambda p: p.relative_to(REPO_ROOT).as_posix())
def test_a_migration_carries_no_test_data(path):
    relative = path.relative_to(REPO_ROOT).as_posix()
    sql = _without_comments(path.read_text(encoding="utf-8"))
    assert not TEST_DATA_MARKERS.search(sql), f"{relative} references demo/test data -- put it in scripts/seed_*.py instead"
    if relative not in LITERAL_INSERT_ALLOWED:
        assert not LITERAL_INSERT.search(sql), (
            f"{relative} inserts literal rows -- migrations reach the live server; seed/test rows belong in "
            "scripts/seed_*.py (a backfill from existing rows should be INSERT ... SELECT)"
        )


def test_the_guard_actually_catches_what_it_is_for():
    assert LITERAL_INSERT.search("INSERT INTO core.users (id, email) VALUES ('1', 'x')")
    assert TEST_DATA_MARKERS.search("WHERE email = 'demo@sonalim-erp.local'")
    assert not LITERAL_INSERT.search("INSERT INTO warehouse.cost_layers (id) SELECT id FROM warehouse.stock_items")
