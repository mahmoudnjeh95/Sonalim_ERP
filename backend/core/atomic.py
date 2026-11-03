from __future__ import annotations

import functools
from typing import Callable

from core.domain.result import Err


class _Refused(Exception):
    def __init__(self, err: Err) -> None:
        self.err = err


def atomic(method: Callable) -> Callable:
    """Run a service method that returns a Result inside a savepoint, undone if it returns Err.

    Multi-step postings (a document and its payments and movements, a voucher and its stock moves)
    write as they go and may refuse halfway; the router rolls the request back, but a caller that
    just keeps its transaction going must not be left with the half that was written. Needs
    `self._connection`."""

    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        try:
            with self._connection.transaction():
                result = method(self, *args, **kwargs)
                if isinstance(result, Err):
                    raise _Refused(result)
                return result
        except _Refused as refused:
            return refused.err

    return wrapper
