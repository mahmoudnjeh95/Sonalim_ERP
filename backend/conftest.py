"""Shared pytest fixtures.

Domain tests need nothing here — they run without a database, as documented in the
README. The `db` fixture below is for integration tests that exercise the real SQL
paths; it skips cleanly when no database is reachable, so `pytest` stays green on a
machine that has none.
"""
from __future__ import annotations

import os
from typing import Iterator

import pytest

# Test databases, in order of preference. TEST_DATABASE_URL wins so nobody has to
# point DATABASE_URL at a throwaway just to run the suite; the local development
# database is the last resort and is safe because every test rolls back.
_CANDIDATE_URLS = [
    os.environ.get("TEST_DATABASE_URL"),
    os.environ.get("DATABASE_URL"),
    "postgresql://erp:erp@localhost:5432/erp",
]


def _database_url() -> str | None:
    try:
        import psycopg
    except ImportError:  # pragma: no cover - psycopg is a hard dependency in practice
        return None

    for url in _CANDIDATE_URLS:
        if not url:
            continue
        try:
            with psycopg.connect(url, connect_timeout=3) as connection:
                # Reachable is not enough: an unrelated PostgreSQL on the default
                # port would otherwise be accepted and every test would fail on a
                # missing table instead of skipping. Require the schema the
                # migrations produce.
                migrated = connection.execute(
                    "SELECT count(*) FROM information_schema.tables "
                    "WHERE table_schema = 'production' AND table_name = 'production_reports'"
                ).fetchone()[0]
                if not migrated:
                    continue
            return url
        except Exception:
            continue
    return None


@pytest.fixture(scope="session")
def database_url() -> str:
    url = _database_url()
    if url is None:
        pytest.skip("no reachable database (set TEST_DATABASE_URL or DATABASE_URL)")
    return url


@pytest.fixture
def db(database_url: str) -> Iterator["object"]:
    """A connection whose transaction is always rolled back.

    PostgreSQL makes DDL transactional, so a test may create, alter and drop
    freely and still leave the database exactly as it found it. Services take a
    connection, so they compose with this directly — nothing is committed, and the
    fixture is safe to point at a development database.
    """
    import psycopg

    connection = psycopg.connect(database_url, connect_timeout=10)
    try:
        yield connection
    finally:
        connection.rollback()
        connection.close()
