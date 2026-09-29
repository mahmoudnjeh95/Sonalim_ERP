"""Payroll runs into the ledger: the PAIE entry of an approved run, one bank / mobile-money / cash
entry per payment method when it is paid, and the mirror of all of them when the run is reversed.

The lines come from payroll's public API only (`PayrollPostingService`); finance never reads
payroll tables. Payroll is an optional dependency, imported when a payroll event is posted."""
from __future__ import annotations

import datetime
from typing import Callable

import psycopg

from core.domain.result import Err, Ok, Result
from modules.finance.api.ledger_posting_service import SYSTEM_ACTOR, LedgerPostingService
from modules.finance.api.posting_failure_service import PostingFailureService
from modules.finance.api.posting_rule_service import PostingRuleService
from modules.finance.domain.ledger import SourceRef
from modules.finance.domain.posting import PaymentEntry, payroll_payment_entries, payroll_run_lines

PAYROLL_JOURNAL = "PAIE"
PAYROLL_MODULE = "payroll"
RUN_KIND = "payroll_run"
PAYMENT_KIND_PREFIX = "payroll_payment_"
METHOD_LABEL_FR = {"bank": "virement", "mobile_money": "mobile money", "cash": "espèces"}


def _default_payroll_api(connection: psycopg.Connection):
    from modules.payroll.api.posting_service import PayrollPostingService

    return PayrollPostingService(connection)


# The one seam tests replace with a fake; production code never reassigns it.
PAYROLL_API_FACTORY: Callable[[psycopg.Connection], object] = _default_payroll_api


def last_day_of(period: datetime.date) -> datetime.date:
    next_month = (period.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)
    return next_month - datetime.timedelta(days=1)


class PayrollLedgerService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection
        self._posting = LedgerPostingService(connection)
        self._rules = PostingRuleService(connection)

    def _payroll(self):
        return PAYROLL_API_FACTORY(self._connection)

    def post_run(
        self, *, tenant_id: str, run_id: str, period: datetime.date, correlation_id: str, causation_id: str | None = None
    ) -> Result[list[dict]]:
        """One PAIE entry per run, dated the last day of the pay month, lines summed per account."""
        source = SourceRef(PAYROLL_MODULE, run_id, RUN_KIND)
        existing = self._posting.find_by_source(tenant_id=tenant_id, source=source)
        if existing is not None:
            return Ok([existing])
        lines = payroll_run_lines(
            self._payroll().posting_lines(tenant_id=tenant_id, run_id=run_id),
            self._rules.rules_for(tenant_id=tenant_id, source="payroll"),
        )
        if isinstance(lines, Err):
            return lines
        posted = self._posting.post_entry(
            tenant_id=tenant_id,
            actor_id=SYSTEM_ACTOR,
            journal_code=PAYROLL_JOURNAL,
            entry_date=last_day_of(period),
            label=f"Paie {period:%m/%Y}",
            lines=lines.value,
            correlation_id=correlation_id,
            source=source,
            reference=run_id,
            causation_id=causation_id,
        )
        if isinstance(posted, Err):
            return posted
        return Ok([posted.value])

    def post_payment(
        self,
        *,
        tenant_id: str,
        run_id: str,
        period: datetime.date,
        paid_on: datetime.date,
        correlation_id: str,
        causation_id: str | None = None,
    ) -> Result[list[dict]]:
        """One entry per payment method, dated the day the run was paid, clearing net pay.
        Every method is checked before any is written, so a refusal leaves nothing half-posted."""
        if self._posting.find_by_source(tenant_id=tenant_id, source=SourceRef(PAYROLL_MODULE, run_id, RUN_KIND)) is None:
            return Err(
                "RUN_NOT_POSTED",
                f"payroll run {run_id} has no posted PAIE entry yet, so its payment cannot clear net pay",
                f"la paie {run_id} n'a pas encore d'écriture PAIE comptabilisée ; son règlement ne peut pas solder les salaires nets",
            )
        entries = payroll_payment_entries(
            self._payroll().payment_lines(tenant_id=tenant_id, run_id=run_id),
            self._rules.rules_for(tenant_id=tenant_id, source="payroll"),
        )
        if isinstance(entries, Err):
            return entries
        posted: list[dict] = []
        pending: list[tuple[SourceRef, PaymentEntry]] = []
        for entry in entries.value:
            source = SourceRef(PAYROLL_MODULE, run_id, PAYMENT_KIND_PREFIX + entry.method)
            existing = self._posting.find_by_source(tenant_id=tenant_id, source=source)
            if existing is not None:
                posted.append(existing)
                continue
            checked = self._posting.check_postable(
                tenant_id=tenant_id, journal_code=entry.journal_code, entry_date=paid_on, lines=entry.lines
            )
            if isinstance(checked, Err):
                return checked
            pending.append((source, entry))
        for source, entry in pending:
            result = self._posting.post_entry(
                tenant_id=tenant_id,
                actor_id=SYSTEM_ACTOR,
                journal_code=entry.journal_code,
                entry_date=paid_on,
                label=f"Paie {period:%m/%Y} – règlement {METHOD_LABEL_FR[entry.method]}",
                lines=entry.lines,
                correlation_id=correlation_id,
                source=source,
                reference=run_id,
                causation_id=causation_id,
            )
            if isinstance(result, Err):
                return result
            posted.append(result.value)
        return Ok(posted)

    def post_reversal(
        self,
        *,
        tenant_id: str,
        run_id: str,
        reversed_on: datetime.date,
        correlation_id: str,
        causation_id: str | None = None,
    ) -> Result[list[dict]]:
        """Mirrors every posted entry of the run, dated the day it was reversed; then cancels the
        run's open posting failures so a later retry cannot post a reversed run."""
        rows = self._connection.execute(
            """
            SELECT id FROM finance.journal_entries
            WHERE tenant_id = %s AND source_module = %s AND source_id = %s
              AND status = 'posted' AND reversal_of IS NULL
            ORDER BY created_at, id
            """,
            (tenant_id, PAYROLL_MODULE, run_id),
        ).fetchall()
        reversals: list[dict] = []
        for (entry_id,) in rows:
            reversed_entry = self._posting.reverse_entry(
                tenant_id=tenant_id,
                actor_id=SYSTEM_ACTOR,
                entry_id=entry_id,
                entry_date=reversed_on,
                correlation_id=correlation_id,
                causation_id=causation_id,
            )
            if isinstance(reversed_entry, Err):
                return reversed_entry
            reversals.append(reversed_entry.value)
        PostingFailureService(self._connection).cancel_for_source(
            tenant_id=tenant_id, source_module=PAYROLL_MODULE, source_id=run_id, kinds=[RUN_KIND, "payroll_payment"]
        )
        return Ok(reversals)
