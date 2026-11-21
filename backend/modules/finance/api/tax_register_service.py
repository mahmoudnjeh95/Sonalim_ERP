"""The VAT register and the VAT return read from it.

Each sales or purchase document whose entry books VAT writes its rows here, in the same transaction as the
entry, one per (tax code, rate): the base and the VAT in F CFA, signed (credit notes and the reversal of a
cancelled purchase invoice are negative). The return sums them over a period, and shows beside them what the
ledger's VAT accounts moved over the same period, so a manual OD or a document posted before the register
existed is visible as a difference."""
from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any, Iterable

import psycopg
from ulid import ULID

from core.domain.result import Err, Ok, Result
from core.domain.tax import BreakdownPart, allocate_breakdown, parse_breakdown
from modules.finance.api.posting_rule_service import PostingRuleService
from modules.finance.domain.ledger import SourceRef
from modules.finance.domain.posting import vat_account

ZERO = Decimal("0")
DIRECTIONS = {"invoice": "collected", "purchase_invoice": "deductible"}


def allocated_parts(raw_breakdown: object, *, amount: Decimal, vat: Decimal) -> list[BreakdownPart]:
    """The document's split per tax code in whole F CFA, summing to its base (amount - VAT) and VAT. A document
    without a breakdown (an older event) is one part with no code and no rate."""
    parts = parse_breakdown(raw_breakdown)
    if not parts:
        return [BreakdownPart(None, None, amount - vat, vat)]  # type: ignore[arg-type]
    return allocate_breakdown(parts, base_total=amount - vat, vat_total=vat)


class TaxRegisterService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def record(self, *, tenant_id: str, source_rule: str, source: SourceRef, entry: dict, entry_date: datetime.date,
               parts: Iterable[BreakdownPart], sign: int, partner_id: str | None, reference: str | None) -> None:
        rules = PostingRuleService(self._connection).rules_for(tenant_id=tenant_id, source=source_rule)
        for part in parts:
            if not part.base and not part.vat:
                continue
            account = vat_account(rules, source=source_rule, tax_code=part.tax_code) if part.vat else None
            self._connection.execute(
                """
                INSERT INTO finance.tax_entries (id, tenant_id, entry_date, direction, tax_code, rate, base, vat, account_code,
                                                 partner_id, reference, source_module, source_id, source_kind, journal_entry_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (str(ULID()), tenant_id, entry_date, DIRECTIONS[source_rule], part.tax_code, part.rate, sign * part.base,
                 sign * part.vat, account.value if isinstance(account, Ok) else None, partner_id, reference, source.module,
                 source.id, source.kind, entry.get("id")),
            )

    def record_reversal(self, *, tenant_id: str, original: SourceRef, reversal: SourceRef, entry: dict,
                        entry_date: datetime.date) -> None:
        """The original document's rows again, negated, dated the day of the reversal."""
        self._connection.execute(
            """
            INSERT INTO finance.tax_entries (id, tenant_id, entry_date, direction, tax_code, rate, base, vat, account_code,
                                             partner_id, reference, source_module, source_id, source_kind, journal_entry_id)
            SELECT md5(id || ':' || %s), tenant_id, %s, direction, tax_code, rate, -base, -vat, account_code, partner_id, reference,
                   %s, %s, %s, %s
            FROM finance.tax_entries
            WHERE tenant_id = %s AND source_module = %s AND source_id = %s AND source_kind = %s
            """,
            (reversal.kind, entry_date, reversal.module, reversal.id, reversal.kind, entry.get("id"),
             tenant_id, original.module, original.id, original.kind),
        )

    # ---- the return ----------------------------------------------------------------------------------

    def vat_return(self, *, tenant_id: str, date_from: datetime.date, date_to: datetime.date) -> Result[dict[str, Any]]:
        if date_to < date_from:
            return Err("INVALID_PERIOD", "the period ends before it starts", "la période se termine avant de commencer")
        rows = self._connection.execute(
            """
            SELECT direction, tax_code, rate, SUM(base), SUM(vat), COUNT(DISTINCT (source_module, source_id, source_kind))
            FROM finance.tax_entries
            WHERE tenant_id = %s AND entry_date BETWEEN %s AND %s
            GROUP BY direction, tax_code, rate
            ORDER BY direction, tax_code NULLS LAST, rate DESC
            """,
            (tenant_id, date_from, date_to),
        ).fetchall()
        exempt = self._exempt_codes(tenant_id)
        sections: dict[str, list[dict[str, Any]]] = {"collected": [], "deductible": []}
        totals = {direction: {"base": ZERO, "vat": ZERO} for direction in sections}
        for direction, code, rate, base, vat, documents in rows:
            sections[direction].append({"tax_code": code, "rate": rate, "exempt": code in exempt, "base": base, "vat": vat,
                                        "documents": documents})
            totals[direction]["base"] += base
            totals[direction]["vat"] += vat
        net = totals["collected"]["vat"] - totals["deductible"]["vat"]
        return Ok({
            "date_from": date_from, "date_to": date_to,
            "collected": sections["collected"], "deductible": sections["deductible"], "totals": totals,
            # > 0: VAT to pay for the period; < 0: a credit carried forward
            "net_vat_due": net,
            "ledger": self._ledger_check(tenant_id, date_from, date_to, totals),
        })

    def _exempt_codes(self, tenant_id: str) -> set[str]:
        rows = self._connection.execute("SELECT code FROM core.tax_codes WHERE tenant_id = %s AND exempt", (tenant_id,)).fetchall()
        return {row[0] for row in rows}

    def _vat_account_codes(self, tenant_id: str, source: str) -> list[str]:
        side = "credit_account_code" if source == "invoice" else "debit_account_code"
        rows = self._connection.execute(
            f"SELECT DISTINCT {side} FROM finance.posting_rules WHERE tenant_id = %s AND source = %s AND source_kind = 'vat' AND {side} IS NOT NULL",
            (tenant_id, source),
        ).fetchall()
        return sorted(row[0] for row in rows)

    def _ledger_check(self, tenant_id: str, date_from: datetime.date, date_to: datetime.date,
                      totals: dict[str, dict[str, Decimal]]) -> dict[str, Any]:
        """What the VAT accounts moved in posted entries over the period: collected = credit - debit of the sales VAT
        accounts, deductible = debit - credit of the purchase VAT accounts."""
        result: dict[str, Any] = {}
        for direction, source, sign in (("collected", "invoice", -1), ("deductible", "purchase_invoice", 1)):
            accounts = self._vat_account_codes(tenant_id, source)
            movement = ZERO
            if accounts:
                row = self._connection.execute(
                    """
                    SELECT COALESCE(SUM(l.debit - l.credit), 0)
                    FROM finance.journal_lines l JOIN finance.journal_entries e ON e.id = l.entry_id
                    WHERE e.tenant_id = %s AND e.status IN ('posted', 'reversed') AND e.entry_date BETWEEN %s AND %s
                      AND l.account_code = ANY(%s)
                    """,
                    (tenant_id, date_from, date_to, accounts),
                ).fetchone()
                movement = Decimal(str(row[0])) * sign
            result[direction] = {"accounts": accounts, "movement": movement, "difference": movement - totals[direction]["vat"]}
        return result
