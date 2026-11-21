"""The posting rules of a tenant: read by the posters, edited from the Posting rules screen.

Seeded rules start `to_confirm`; the accountant confirms them one by one. Any edit sends a rule
back to `to_confirm`, so "confirmed" always means "this exact mapping was checked"."""
from __future__ import annotations

import psycopg
from ulid import ULID

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from modules.finance.api.ledger_posting_service import LedgerPostingService
from modules.finance.domain.posting import PostingRule, validate_rule

RULE_KEYS = (
    "id", "source", "source_kind", "code", "debit_account_code", "credit_account_code",
    "journal_code", "status", "confirmed_by", "confirmed_at", "updated_at",
)
RULE_COLUMNS = ", ".join(RULE_KEYS)


def rule_not_found(rule_id: str) -> Err:
    return Err("NOT_FOUND", f"posting rule {rule_id} not found", f"règle d'imputation {rule_id} introuvable")


def _merge(current: str | None, new: str | None) -> str | None:
    """`None` keeps the current value; an empty string clears it."""
    if new is None:
        return current
    return new.strip() or None


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

    def list_rules(self, *, tenant_id: str) -> list[dict]:
        rows = self._connection.execute(
            f"SELECT {RULE_COLUMNS} FROM finance.posting_rules WHERE tenant_id = %s ORDER BY source, source_kind, code",
            (tenant_id,),
        ).fetchall()
        return [dict(zip(RULE_KEYS, row)) for row in rows]

    def _get(self, tenant_id: str, rule_id: str) -> dict | None:
        row = self._connection.execute(
            f"SELECT {RULE_COLUMNS} FROM finance.posting_rules WHERE tenant_id = %s AND id = %s FOR UPDATE",
            (tenant_id, rule_id),
        ).fetchone()
        return None if row is None else dict(zip(RULE_KEYS, row))

    def _validate(self, tenant_id: str, rule: PostingRule) -> Result[PostingRule]:
        ledger = LedgerPostingService(self._connection)
        codes = [code for code in (rule.debit_account_code, rule.credit_account_code) if code]
        if rule.source in ("invoice", "purchase_invoice") and rule.source_kind == "vat" and rule.code.strip() != "*":
            # A VAT rule's code is one of the tenant's tax codes (core.tax_codes).
            from core.tax_codes import TaxCodeService

            if TaxCodeService(self._connection).find_code(tenant_id=tenant_id, code=rule.code) is None:
                return Err("TAX_CODE_NOT_FOUND", f"tax code {rule.code.strip()} does not exist",
                           f"le code de taxe {rule.code.strip()} n'existe pas")
        return validate_rule(rule, ledger.load_accounts(tenant_id=tenant_id, codes=codes), ledger.journal_codes(tenant_id=tenant_id))

    def create_rule(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        source: str,
        source_kind: str,
        code: str,
        debit_account_code: str | None = None,
        credit_account_code: str | None = None,
        journal_code: str | None = None,
    ) -> Result[dict]:
        checked = self._validate(
            tenant_id,
            PostingRule(
                source=source.strip(),
                source_kind=source_kind.strip(),
                # tax codes are upper case (core.tax_codes)
                code=code.strip().upper() if source_kind == "vat" else code,
                debit_account_code=_merge(None, debit_account_code),
                credit_account_code=_merge(None, credit_account_code),
                journal_code=_merge(None, journal_code),
            ),
        )
        if isinstance(checked, Err):
            return checked
        rule = checked.value
        exists = self._connection.execute(
            """
            SELECT 1 FROM finance.posting_rules
            WHERE tenant_id = %s AND source = %s AND source_kind = %s AND code = %s
            """,
            (tenant_id, rule.source, rule.source_kind, rule.code),
        ).fetchone()
        if exists:
            return Err(
                "POSTING_RULE_EXISTS",
                f"a rule for {rule.source} / {rule.source_kind} / {rule.code} already exists",
                f"une règle existe déjà pour {rule.source} / {rule.source_kind} / {rule.code}",
            )
        rule_id = str(ULID())
        self._connection.execute(
            """
            INSERT INTO finance.posting_rules
                (id, tenant_id, source, source_kind, code, debit_account_code, credit_account_code, journal_code)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                rule_id, tenant_id, rule.source, rule.source_kind, rule.code,
                rule.debit_account_code, rule.credit_account_code, rule.journal_code,
            ),
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="posting_rule.created",
            entity_type="posting_rule",
            entity_id=rule_id,
            payload={
                "source": rule.source,
                "source_kind": rule.source_kind,
                "code": rule.code,
                "debit_account_code": rule.debit_account_code,
                "credit_account_code": rule.credit_account_code,
                "journal_code": rule.journal_code,
            },
        )
        return Ok(self._get(tenant_id, rule_id))

    def update_rule(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        rule_id: str,
        debit_account_code: str | None = None,
        credit_account_code: str | None = None,
        journal_code: str | None = None,
    ) -> Result[dict]:
        """`None` keeps a field, `""` clears it. Any edit sends the rule back to `to_confirm`."""
        current = self._get(tenant_id, rule_id)
        if current is None:
            return rule_not_found(rule_id)
        checked = self._validate(
            tenant_id,
            PostingRule(
                source=current["source"],
                source_kind=current["source_kind"],
                code=current["code"],
                debit_account_code=_merge(current["debit_account_code"], debit_account_code),
                credit_account_code=_merge(current["credit_account_code"], credit_account_code),
                journal_code=_merge(current["journal_code"], journal_code),
            ),
        )
        if isinstance(checked, Err):
            return checked
        rule = checked.value
        self._connection.execute(
            """
            UPDATE finance.posting_rules
            SET debit_account_code = %s, credit_account_code = %s, journal_code = %s,
                status = 'to_confirm', confirmed_by = NULL, confirmed_at = NULL, updated_at = NOW()
            WHERE tenant_id = %s AND id = %s
            """,
            (rule.debit_account_code, rule.credit_account_code, rule.journal_code, tenant_id, rule_id),
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="posting_rule.updated",
            entity_type="posting_rule",
            entity_id=rule_id,
            payload={
                "debit_account_code": rule.debit_account_code,
                "credit_account_code": rule.credit_account_code,
                "journal_code": rule.journal_code,
                "previous_status": current["status"],
            },
        )
        return Ok(self._get(tenant_id, rule_id))

    def confirm_rule(self, *, tenant_id: str, actor_id: str, rule_id: str) -> Result[dict]:
        current = self._get(tenant_id, rule_id)
        if current is None:
            return rule_not_found(rule_id)
        key = f"{current['source']} / {current['source_kind']} / {current['code']}"
        if current["status"] == "confirmed":
            return Err(
                "INVALID_TRANSITION",
                f"posting rule {key} is already confirmed",
                f"la règle d'imputation {key} est déjà confirmée",
            )
        self._connection.execute(
            """
            UPDATE finance.posting_rules
            SET status = 'confirmed', confirmed_by = %s, confirmed_at = NOW(), updated_at = NOW()
            WHERE tenant_id = %s AND id = %s
            """,
            (actor_id, tenant_id, rule_id),
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="posting_rule.confirmed",
            entity_type="posting_rule",
            entity_id=rule_id,
            payload={"source": current["source"], "source_kind": current["source_kind"], "code": current["code"]},
        )
        return Ok(self._get(tenant_id, rule_id))
