from __future__ import annotations

import functools
from typing import Callable

from psycopg.pq import TransactionStatus

from core.domain.result import Err


class _Refused(Exception):
    def __init__(self, err: Err) -> None:
        self.err = err


def atomic(method: Callable) -> Callable:
    """Run a service method that returns a Result inside a savepoint, undone if it returns Err.

    Multi-step postings (a document and its payments and movements, a voucher and its stock moves)
    write as they go and may refuse halfway; the router rolls the request back, but a caller that
    just keeps its transaction going must not be left with the half that was written. Needs
    `self._connection`.

    It never commits: that stays with the caller, whatever else the request still has to do. On an
    idle connection `connection.transaction()` would be an outermost block that commits on exit, so
    the implicit transaction is opened first. A connection in autocommit has no transaction to
    join and would commit each statement anyway; nothing in this codebase uses one."""

    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        if self._connection.info.transaction_status == TransactionStatus.IDLE:
            self._connection.execute("SELECT 1")
        try:
            with self._connection.transaction():
                result = method(self, *args, **kwargs)
                if isinstance(result, Err):
                    raise _Refused(result)
                return result
        except _Refused as refused:
            return refused.err

    return wrapper
