"""Database connections, from one process-wide pool.

`get_connection()` keeps the contract it had when it opened a fresh connection per call:
the block's transaction is committed if it exits normally and rolled back if it raises.
The difference is that the connection then goes back to the pool instead of being closed,
so a request no longer pays for a TCP + auth handshake.

A pooled connection is reused by later callers, so code must not leave session state on
it: no `autocommit = True`, no `connection.row_factory = ...` (pass `row_factory` to
`cursor()` instead), no plain `SET` (use `SET LOCAL`), and session advisory locks are
released before the block ends (as the migration runner does). The pool rolls back any
transaction left open when the connection is returned.

Sizing comes from the environment: DB_POOL_MIN_SIZE (default 1), DB_POOL_MAX_SIZE (default
20) and DB_POOL_TIMEOUT, the seconds a caller waits for a free connection before
`psycopg_pool.PoolTimeout` (default 30). The API and the worker each have their own pool,
so Postgres needs room for twice the max plus backups and admin sessions.
"""
from __future__ import annotations

import atexit
import os
import threading
from contextlib import contextmanager
from typing import Iterator

import psycopg
from psycopg_pool import ConnectionPool

_pool: ConnectionPool | None = None
_pool_lock = threading.Lock()


def _int_env(name: str, default: int) -> int:
    value = os.environ.get(name, "").strip()
    return int(value) if value else default


def _float_env(name: str, default: float) -> float:
    value = os.environ.get(name, "").strip()
    return float(value) if value else default


def _create_pool() -> ConnectionPool:
    purging = threading.Lock()

    def check(connection: psycopg.Connection) -> None:
        # A connection that died while idle (Postgres restarted, network cut) is replaced on
        # checkout instead of failing the request that drew it. The pool backs off 1 s, 2 s,
        # 4 s... between dead connections it draws, so after a restart one request could wait
        # through the whole idle set and time out; on the first dead one, purge them all.
        try:
            ConnectionPool.check_connection(connection)
        except Exception:
            if purging.acquire(blocking=False):
                try:
                    pool.check()  # the pool built below; check() uses the plain check, no recursion
                finally:
                    purging.release()
            raise

    min_size = _int_env("DB_POOL_MIN_SIZE", 1)
    pool = ConnectionPool(
        os.environ["DATABASE_URL"],
        min_size=min_size,
        max_size=max(_int_env("DB_POOL_MAX_SIZE", 20), min_size),
        timeout=_float_env("DB_POOL_TIMEOUT", 30.0),
        check=check,
        name="erp",
        open=True,
    )
    return pool


def get_pool() -> ConnectionPool:
    """The process's pool, opened on first use (so importing this module connects nothing)."""
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                _pool = _create_pool()
    return _pool


def close_pool() -> None:
    """Close the pool and its connections; the next get_connection() opens a new one."""
    global _pool
    with _pool_lock:
        pool, _pool = _pool, None
    if pool is not None:
        pool.close()


atexit.register(close_pool)


@contextmanager
def get_connection() -> Iterator[psycopg.Connection]:
    with get_pool().connection() as connection:
        yield connection
