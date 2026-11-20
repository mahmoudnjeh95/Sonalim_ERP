"""core.db: get_connection() draws from a pool and keeps its commit/rollback contract."""
from __future__ import annotations

import time

import psycopg
import pytest

from core import db as core_db


@pytest.fixture
def pool_env(database_url: str, monkeypatch: pytest.MonkeyPatch):
    """A fresh one-connection pool on the test database, closed afterwards."""
    core_db.close_pool()
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("DB_POOL_MIN_SIZE", "1")
    monkeypatch.setenv("DB_POOL_MAX_SIZE", "1")
    monkeypatch.setenv("DB_POOL_TIMEOUT", "5")
    yield database_url
    core_db.close_pool()


def _backend_pid(connection: psycopg.Connection) -> int:
    return connection.execute("SELECT pg_backend_pid()").fetchone()[0]


def test_sizing_comes_from_the_environment(pool_env):
    pool = core_db.get_pool()
    assert (pool.min_size, pool.max_size, pool.timeout) == (1, 1, 5.0)
    assert core_db.get_pool() is pool


def test_connection_is_reused_not_reopened(pool_env):
    with core_db.get_connection() as connection:
        first = _backend_pid(connection)
    with core_db.get_connection() as connection:
        assert _backend_pid(connection) == first


def test_block_commits_on_exit_and_rolls_back_on_error(pool_env):
    with core_db.get_connection() as connection:
        connection.execute("CREATE TEMP TABLE pool_probe (n int)")  # lives with the pooled session
    with core_db.get_connection() as connection:
        connection.execute("INSERT INTO pool_probe VALUES (1)")
    with pytest.raises(RuntimeError):
        with core_db.get_connection() as connection:
            connection.execute("INSERT INTO pool_probe VALUES (2)")
            raise RuntimeError("refused halfway")
    with core_db.get_connection() as connection:
        assert connection.info.transaction_status == psycopg.pq.TransactionStatus.IDLE
        assert [row[0] for row in connection.execute("SELECT n FROM pool_probe")] == [1]


def test_dead_connection_is_replaced_on_checkout(pool_env):
    with core_db.get_connection() as connection:
        dead_pid = _backend_pid(connection)
    with psycopg.connect(pool_env, autocommit=True) as admin:
        # The timeout makes it wait until the backend has actually exited.
        assert admin.execute("SELECT pg_terminate_backend(%s, 5000)", (dead_pid,)).fetchone()[0]
    with core_db.get_connection() as connection:
        assert _backend_pid(connection) != dead_pid


def test_a_pool_full_of_dead_connections_recovers_at_once(pool_env, monkeypatch: pytest.MonkeyPatch):
    # As after a Postgres restart: every idle connection is dead. Without purging them all on
    # the first failure, the pool backs off 1 s, 2 s, 4 s... per dead one and times out.
    core_db.close_pool()
    monkeypatch.setenv("DB_POOL_MAX_SIZE", "5")
    monkeypatch.setenv("DB_POOL_TIMEOUT", "4")
    held = [core_db.get_pool().getconn() for _ in range(5)]
    pids = [_backend_pid(connection) for connection in held]
    for connection in held:
        connection.rollback()
        core_db.get_pool().putconn(connection)
    with psycopg.connect(pool_env, autocommit=True) as admin:
        for pid in pids:
            assert admin.execute("SELECT pg_terminate_backend(%s, 5000)", (pid,)).fetchone()[0]

    started = time.monotonic()
    with core_db.get_connection() as connection:
        assert _backend_pid(connection) not in pids
    assert time.monotonic() - started < 2.5


def test_close_pool_lets_the_next_call_open_a_new_one(pool_env):
    first = core_db.get_pool()
    core_db.close_pool()
    assert first.closed
    with core_db.get_connection() as connection:
        assert connection.execute("SELECT 1").fetchone()[0] == 1
    assert core_db.get_pool() is not first
