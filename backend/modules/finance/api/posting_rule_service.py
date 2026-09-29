"""The posting rules of a tenant: read by the posters, edited from the Posting rules screen."""
from __future__ import annotations

import psycopg

from modules.finance.domain.posting import PostingRule


class PostingRuleService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def rules_for(self, *, tenant_id: str, source: str) -> list[PostingRule]:
        rows = self._connection.execute(
            """
            SELECT source, source_kind, code, debit_account_code, credit_account_code, journal_code, status, id
            FROM finance.posting_rules
            WHERE tenant_id = %s AND source = %s
            """,
            (tenant_id, source),
        ).fetchall()
        return [PostingRule(*row) for row in rows]
