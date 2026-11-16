"""@atomic on a connection with no open transaction, the state every router starts in.

The db fixture can't show this: its connection is already in a transaction, where the block is a
savepoint anyway. So each test opens its own connection and commits for real, but only into a
temporary table, which goes away with the connection.
"""
from __future__ import annotations

from typing import Iterator

import psycopg
import pytest
from psycopg.pq import TransactionStatus

from core.atomic import atomic
from core.domain.result import Err, Ok


class _Writer:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def _write(self, value: str) -> None:
        self._connection.execute("INSERT INTO atomic_probe (value) VALUES (%s)", (value,))

    @atomic
    def succeed(self, value: str):
        self._write(value)
        return Ok(value)

    @atomic
    def refuse(self, value: str):
        self._write(value)
        return Err("REFUSED", "refused", "refusé")

    @atomic
    def blow_up(self, value: str):
        self._write(value)
        raise RuntimeError("boom")


@pytest.fixture
def connection(database_url: str) -> Iterator[psycopg.Connection]:
    with psycopg.connect(database_url, connect_timeout=10) as connection:
        connection.execute("CREATE TEMP TABLE atomic_probe (value TEXT)")
        connection.commit()
        assert connection.info.transaction_status == TransactionStatus.IDLE
        yield connection
        connection.rollback()


def _values(connection: psycopg.Connection) -> list[str]:
    values = [row[0] for row in connection.execute("SELECT value FROM atomic_probe ORDER BY value").fetchall()]
    connection.rollback()
    return values


def test_a_success_is_not_committed_until_the_caller_commits(connection):
    assert isinstance(_Writer(connection).succeed("a"), Ok)

    assert connection.info.transaction_status == TransactionStatus.INTRANS
    connection.rollback()
    assert _values(connection) == []


def test_the_callers_commit_makes_a_success_durable(connection):
    assert isinstance(_Writer(connection).succeed("a"), Ok)
    connection.commit()

    assert _values(connection) == ["a"]


def test_a_refusal_leaves_nothing_and_the_connection_usable(connection):
    refused = _Writer(connection).refuse("a")

    assert isinstance(refused, Err) and refused.code == "REFUSED"
    assert connection.info.transaction_status == TransactionStatus.INTRANS
    connection.commit()
    assert _values(connection) == []


def test_an_exception_leaves_nothing_and_reaches_the_caller(connection):
    with pytest.raises(RuntimeError):
        _Writer(connection).blow_up("a")

    connection.commit()
    assert _values(connection) == []


def test_a_refusal_undoes_only_its_own_writes_in_an_open_transaction(connection):
    writer = _Writer(connection)
    writer._write("earlier")

    assert isinstance(writer.refuse("a"), Err)
    connection.commit()

    assert _values(connection) == ["earlier"]


def test_a_later_failure_in_the_same_request_undoes_an_earlier_success(connection):
    writer = _Writer(connection)
    assert isinstance(writer.succeed("a"), Ok)
    assert isinstance(writer.refuse("b"), Err)

    connection.rollback()

    assert _values(connection) == []
