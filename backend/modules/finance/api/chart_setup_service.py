"""Installs the SYSCOHADA seed for a tenant: chart, journals and default posting rules.

Idempotent: rows that already exist — possibly renamed or re-mapped by the accountant — are left
alone, so running it again after an upgrade only adds what is new."""
from __future__ import annotations

import psycopg
from ulid import ULID

from core.audit import record_audit
from modules.finance.domain.syscohada_chart import CHART, DEFAULT_POSTING_RULES, JOURNALS


class ChartSetupService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def ensure_defaults(self, *, tenant_id: str, actor_id: str) -> dict[str, int]:
        counts = {"accounts": 0, "journals": 0, "posting_rules": 0}
        for account in CHART:
            cursor = self._connection.execute(
                """
                INSERT INTO finance.accounts (tenant_id, code, name, class_no, account_type, is_postable, parent_code)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (tenant_id, code) DO NOTHING
                """,
                (
                    tenant_id, account.code, account.name, account.class_no,
                    account.account_type, account.is_postable, account.parent_code,
                ),
            )
            counts["accounts"] += cursor.rowcount
        for code, name, journal_type in JOURNALS:
            cursor = self._connection.execute(
                """
                INSERT INTO finance.journals (tenant_id, code, name, journal_type)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (tenant_id, code) DO NOTHING
                """,
                (tenant_id, code, name, journal_type),
            )
            counts["journals"] += cursor.rowcount
        for rule in DEFAULT_POSTING_RULES:
            cursor = self._connection.execute(
                """
                INSERT INTO finance.posting_rules
                    (id, tenant_id, source, source_kind, code, debit_account_code, credit_account_code, journal_code)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (tenant_id, source, source_kind, code) DO NOTHING
                """,
                (
                    str(ULID()), tenant_id, rule.source, rule.source_kind, rule.code,
                    rule.debit_account_code, rule.credit_account_code, rule.journal_code,
                ),
            )
            counts["posting_rules"] += cursor.rowcount
        if any(counts.values()):
            record_audit(
                self._connection,
                tenant_id=tenant_id,
                actor_id=actor_id,
                action="ledger_setup.applied",
                entity_type="ledger_setup",
                entity_id=tenant_id,
                payload=counts,
            )
        return counts
