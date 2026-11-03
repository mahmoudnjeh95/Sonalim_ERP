"""Test helpers for the finance module (not a test file itself)."""
from __future__ import annotations


class NoCommitConnection:
    """The `db` fixture's connection with commit and rollback made no-ops.

    Code that manages its own transaction — the event registry (`core.events.consumers._process`),
    the ledger consumers, the routers — runs against it without ending the fixture's transaction,
    so everything still rolls back when the test ends."""

    def __init__(self, connection) -> None:
        self._connection = connection

    def __getattr__(self, name):
        return getattr(self._connection, name)

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> bool:
        return False
