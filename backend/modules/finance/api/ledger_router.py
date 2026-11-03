"""HTTP routes of the SYSCOHADA ledger under /finance. Invoices keep their own router."""
from __future__ import annotations

import datetime
from decimal import Decimal
from typing import NoReturn

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from ulid import ULID

from core.db import get_connection
from core.domain.result import Err, err_detail
from core.tenancy import TenantContext, require_permission, require_session, user_has_permission
from modules.finance.api.account_service import AccountService
from modules.finance.api.chart_setup_service import ChartSetupService
from modules.finance.api.ledger_event_postings import retry_failure
from modules.finance.api.ledger_posting_service import entry_not_found
from modules.finance.api.ledger_query_service import LedgerQueryService
from modules.finance.api.ledger_report_service import LedgerReportService
from modules.finance.api.manual_entry_service import ManualEntryService
from modules.finance.api.period_service import PeriodService
from modules.finance.api.posting_failure_service import PostingFailureService
from modules.finance.api.posting_rule_service import PostingRuleService
from modules.finance.domain.ledger import EntryLine

router = APIRouter(prefix="/finance", tags=["finance.ledger"])

CONFLICT_CODES = {
    "PERIOD_CLOSED", "ENTRY_POSTED", "INVALID_TRANSITION", "FISCAL_YEAR_EXISTS", "ACCOUNT_EXISTS",
    "POSTING_RULE_EXISTS", "RUN_NOT_POSTED", "INVOICE_NOT_POSTED", "LEDGER_POSTING_DISABLED",
}


def jsonable(value):
    """Whole francs as JSON integers, dates as ISO strings, recursively."""
    if isinstance(value, Decimal):
        return int(value)
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    return value


def _refuse(connection, err: Err) -> NoReturn:
    connection.rollback()
    if err.code == "NOT_FOUND":
        code = status.HTTP_404_NOT_FOUND
    elif err.code in CONFLICT_CODES:
        code = status.HTTP_409_CONFLICT
    else:
        code = status.HTTP_400_BAD_REQUEST
    raise HTTPException(code, err_detail(err))


def _check_range(date_from: datetime.date, date_to: datetime.date) -> None:
    if date_from > date_to:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            err_detail(
                Err(
                    "INVALID_PERIOD",
                    f"the range starts ({date_from}) after it ends ({date_to})",
                    f"la plage commence ({date_from}) après sa fin ({date_to})",
                )
            ),
        )


def require_any_permission(*permissions: str):
    """Like require_permission, satisfied by any one of `permissions`."""

    def dependency(tenant: TenantContext = Depends(require_session)) -> TenantContext:
        with get_connection() as connection:
            allowed = any(
                user_has_permission(connection, user_id=tenant.user_id, permission=permission) for permission in permissions
            )
        if not allowed:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                {
                    "code": "FORBIDDEN",
                    "message": f"missing permission: one of {', '.join(permissions)}",
                    "message_fr": f"permission manquante : l'une de {', '.join(permissions)}",
                },
            )
        return tenant

    return dependency


class AccountIn(BaseModel):
    code: str
    name: str
    account_type: str
    is_postable: bool = True
    parent_code: str | None = None


class AccountPatch(BaseModel):
    name: str | None = None
    account_type: str | None = None
    is_postable: bool | None = None
    parent_code: str | None = None  # "" removes the parent


class FiscalYearIn(BaseModel):
    year: int


class RuleIn(BaseModel):
    source: str
    source_kind: str
    code: str
    debit_account_code: str | None = None
    credit_account_code: str | None = None
    journal_code: str | None = None


class RulePatch(BaseModel):
    debit_account_code: str | None = None  # "" clears the side
    credit_account_code: str | None = None
    journal_code: str | None = None


class LineIn(BaseModel):
    account_code: str
    debit: int = Field(default=0, ge=0)
    credit: int = Field(default=0, ge=0)
    label: str | None = None
    partner_id: str | None = None

    def to_line(self) -> EntryLine:
        return EntryLine(
            account_code=self.account_code.strip(),
            debit=Decimal(self.debit),
            credit=Decimal(self.credit),
            label=(self.label or "").strip() or None,
            partner_id=self.partner_id or None,
        )


class EntryIn(BaseModel):
    journal_code: str = "OD"
    entry_date: datetime.date
    label: str
    reference: str | None = None
    lines: list[LineIn]


class EntryPatch(BaseModel):
    journal_code: str | None = None
    entry_date: datetime.date | None = None
    label: str | None = None
    reference: str | None = None
    lines: list[LineIn] | None = None


class PostIn(BaseModel):
    correlation_id: str | None = None


class ReverseIn(BaseModel):
    entry_date: datetime.date
    correlation_id: str | None = None


# Setup and chart of accounts.


@router.post("/setup")
def setup_ledger(tenant: TenantContext = Depends(require_permission("finance.admin_accounts"))) -> dict:
    with get_connection() as connection:
        counts = ChartSetupService(connection).ensure_defaults(tenant_id=tenant.tenant_id, actor_id=tenant.user_id)
        connection.commit()
    return counts


@router.get("/accounts")
def list_accounts(tenant: TenantContext = Depends(require_permission("finance.view_ledger"))) -> list[dict]:
    with get_connection() as connection:
        return jsonable(AccountService(connection).list_accounts(tenant_id=tenant.tenant_id))


@router.post("/accounts", status_code=status.HTTP_201_CREATED)
def create_account(body: AccountIn, tenant: TenantContext = Depends(require_permission("finance.manage_accounts"))) -> dict:
    with get_connection() as connection:
        result = AccountService(connection).create_account(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, code=body.code, name=body.name,
            account_type=body.account_type, is_postable=body.is_postable, parent_code=body.parent_code,
        )
        if isinstance(result, Err):
            _refuse(connection, result)
        connection.commit()
    return jsonable(result.value)


@router.patch("/accounts/{code}")
def update_account(
    code: str, body: AccountPatch, tenant: TenantContext = Depends(require_permission("finance.admin_accounts"))
) -> dict:
    with get_connection() as connection:
        result = AccountService(connection).update_account(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, code=code, name=body.name,
            account_type=body.account_type, is_postable=body.is_postable, parent_code=body.parent_code,
        )
        if isinstance(result, Err):
            _refuse(connection, result)
        connection.commit()
    return jsonable(result.value)


@router.get("/journals")
def list_journals(tenant: TenantContext = Depends(require_permission("finance.view_ledger"))) -> list[dict]:
    with get_connection() as connection:
        return jsonable(AccountService(connection).list_journals(tenant_id=tenant.tenant_id))


# Fiscal years and periods.


@router.get("/periods")
def list_periods(
    year: int | None = None, tenant: TenantContext = Depends(require_permission("finance.view_ledger"))
) -> list[dict]:
    with get_connection() as connection:
        return jsonable(PeriodService(connection).list_periods(tenant_id=tenant.tenant_id, year=year))


@router.post("/fiscal-years", status_code=status.HTTP_201_CREATED)
def open_fiscal_year(body: FiscalYearIn, tenant: TenantContext = Depends(require_permission("finance.admin_periods"))) -> dict:
    with get_connection() as connection:
        result = PeriodService(connection).open_fiscal_year(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, year=body.year)
        if isinstance(result, Err):
            _refuse(connection, result)
        connection.commit()
    return jsonable(result.value)


@router.post("/periods/{period}/close")
def close_period(period: datetime.date, tenant: TenantContext = Depends(require_permission("finance.admin_periods"))) -> dict:
    with get_connection() as connection:
        result = PeriodService(connection).close_period(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, period=period)
        if isinstance(result, Err):
            _refuse(connection, result)
        connection.commit()
    return jsonable(result.value)


@router.post("/periods/{period}/reopen")
def reopen_period(period: datetime.date, tenant: TenantContext = Depends(require_permission("finance.admin_periods"))) -> dict:
    with get_connection() as connection:
        result = PeriodService(connection).reopen_period(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, period=period)
        if isinstance(result, Err):
            _refuse(connection, result)
        connection.commit()
    return jsonable(result.value)


# Posting rules.


@router.get("/posting-rules")
def list_posting_rules(tenant: TenantContext = Depends(require_permission("finance.view_ledger"))) -> list[dict]:
    with get_connection() as connection:
        return jsonable(PostingRuleService(connection).list_rules(tenant_id=tenant.tenant_id))


@router.post("/posting-rules", status_code=status.HTTP_201_CREATED)
def create_posting_rule(
    body: RuleIn, tenant: TenantContext = Depends(require_permission("finance.manage_posting_rules"))
) -> dict:
    with get_connection() as connection:
        result = PostingRuleService(connection).create_rule(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, source=body.source, source_kind=body.source_kind,
            code=body.code, debit_account_code=body.debit_account_code, credit_account_code=body.credit_account_code,
            journal_code=body.journal_code,
        )
        if isinstance(result, Err):
            _refuse(connection, result)
        connection.commit()
    return jsonable(result.value)


@router.patch("/posting-rules/{rule_id}")
def update_posting_rule(
    rule_id: str, body: RulePatch, tenant: TenantContext = Depends(require_permission("finance.manage_posting_rules"))
) -> dict:
    with get_connection() as connection:
        result = PostingRuleService(connection).update_rule(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, rule_id=rule_id,
            debit_account_code=body.debit_account_code, credit_account_code=body.credit_account_code,
            journal_code=body.journal_code,
        )
        if isinstance(result, Err):
            _refuse(connection, result)
        connection.commit()
    return jsonable(result.value)


@router.post("/posting-rules/{rule_id}/confirm")
def confirm_posting_rule(
    rule_id: str, tenant: TenantContext = Depends(require_permission("finance.manage_posting_rules"))
) -> dict:
    with get_connection() as connection:
        result = PostingRuleService(connection).confirm_rule(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, rule_id=rule_id)
        if isinstance(result, Err):
            _refuse(connection, result)
        connection.commit()
    return jsonable(result.value)


# Entries.


@router.get("/entries")
def list_entries(
    date_from: datetime.date,
    date_to: datetime.date,
    journal_code: str | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    tenant: TenantContext = Depends(require_permission("finance.view_ledger")),
) -> list[dict]:
    _check_range(date_from, date_to)
    with get_connection() as connection:
        return jsonable(
            LedgerQueryService(connection).list_entries(
                tenant_id=tenant.tenant_id, date_from=date_from, date_to=date_to,
                journal_code=journal_code, status=status_filter,
            )
        )


@router.get("/entries/{entry_id}")
def get_entry(entry_id: str, tenant: TenantContext = Depends(require_permission("finance.view_ledger"))) -> dict:
    with get_connection() as connection:
        entry = LedgerQueryService(connection).get_entry(tenant_id=tenant.tenant_id, entry_id=entry_id)
    if entry is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, err_detail(entry_not_found(entry_id)))
    return jsonable(entry)


@router.post("/entries", status_code=status.HTTP_201_CREATED)
def create_entry(body: EntryIn, tenant: TenantContext = Depends(require_permission("finance.manage_entries"))) -> dict:
    with get_connection() as connection:
        result = ManualEntryService(connection).create_draft(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, journal_code=body.journal_code,
            entry_date=body.entry_date, label=body.label, reference=body.reference,
            lines=[line.to_line() for line in body.lines],
        )
        if isinstance(result, Err):
            _refuse(connection, result)
        connection.commit()
    return jsonable(result.value)


@router.patch("/entries/{entry_id}")
def update_entry(
    entry_id: str, body: EntryPatch, tenant: TenantContext = Depends(require_permission("finance.admin_entries"))
) -> dict:
    with get_connection() as connection:
        result = ManualEntryService(connection).update_draft(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, entry_id=entry_id,
            journal_code=body.journal_code, entry_date=body.entry_date, label=body.label, reference=body.reference,
            lines=None if body.lines is None else [line.to_line() for line in body.lines],
        )
        if isinstance(result, Err):
            _refuse(connection, result)
        connection.commit()
    return jsonable(result.value)


@router.delete("/entries/{entry_id}")
def delete_entry(entry_id: str, tenant: TenantContext = Depends(require_permission("finance.manage_entries"))) -> dict:
    with get_connection() as connection:
        result = ManualEntryService(connection).delete_draft(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, entry_id=entry_id)
        if isinstance(result, Err):
            _refuse(connection, result)
        connection.commit()
    return result.value


@router.post("/entries/{entry_id}/post")
def post_entry(
    entry_id: str, body: PostIn, tenant: TenantContext = Depends(require_permission("finance.manage_entries"))
) -> dict:
    with get_connection() as connection:
        result = ManualEntryService(connection).post(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, entry_id=entry_id,
            correlation_id=body.correlation_id or str(ULID()),
        )
        if isinstance(result, Err):
            _refuse(connection, result)
        connection.commit()
    return jsonable(result.value)


@router.post("/entries/{entry_id}/reverse")
def reverse_entry(
    entry_id: str, body: ReverseIn, tenant: TenantContext = Depends(require_permission("finance.admin_entries"))
) -> dict:
    with get_connection() as connection:
        result = ManualEntryService(connection).reverse(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, entry_id=entry_id,
            entry_date=body.entry_date, correlation_id=body.correlation_id or str(ULID()),
        )
        if isinstance(result, Err):
            _refuse(connection, result)
        connection.commit()
    return jsonable(result.value)


# Refused automatic postings, and what one source (a payroll run) has in the ledger.


@router.get("/posting-failures")
def list_posting_failures(
    status_filter: str = Query(default="open", alias="status"),
    tenant: TenantContext = Depends(require_permission("finance.view_ledger")),
) -> list[dict]:
    with get_connection() as connection:
        return jsonable(
            PostingFailureService(connection).list_failures(
                tenant_id=tenant.tenant_id, status=None if status_filter == "all" else status_filter
            )
        )


@router.post("/posting-failures/{failure_id}/retry")
def retry_posting_failure(
    failure_id: str, tenant: TenantContext = Depends(require_permission("finance.manage_entries"))
) -> dict:
    with get_connection() as connection:
        result = retry_failure(connection, tenant_id=tenant.tenant_id, actor_id=tenant.user_id, failure_id=failure_id)
        if isinstance(result, Err):
            _refuse(connection, result)
        connection.commit()
    return {"entries": jsonable(result.value)}


@router.get("/ledger/sources/{source_module}/{source_id}")
def source_postings(
    source_module: str,
    source_id: str,
    tenant: TenantContext = Depends(require_any_permission("finance.view_ledger", "payroll.view_runs")),
) -> dict:
    with get_connection() as connection:
        entries = LedgerQueryService(connection).entries_for_source(
            tenant_id=tenant.tenant_id, source_module=source_module, source_id=source_id
        )
        failures = PostingFailureService(connection).failures_for_source(
            tenant_id=tenant.tenant_id, source_module=source_module, source_id=source_id
        )
    return {"entries": jsonable(entries), "failures": jsonable(failures)}


# Reports.


@router.get("/reports/trial-balance")
def trial_balance(
    date_from: datetime.date,
    date_to: datetime.date,
    tenant: TenantContext = Depends(require_permission("finance.view_ledger")),
) -> dict:
    _check_range(date_from, date_to)
    with get_connection() as connection:
        return jsonable(LedgerReportService(connection).trial_balance(tenant_id=tenant.tenant_id, date_from=date_from, date_to=date_to))


@router.get("/reports/general-ledger")
def general_ledger(
    account_code: str,
    date_from: datetime.date,
    date_to: datetime.date,
    tenant: TenantContext = Depends(require_permission("finance.view_ledger")),
) -> dict:
    _check_range(date_from, date_to)
    with get_connection() as connection:
        result = LedgerReportService(connection).general_ledger(
            tenant_id=tenant.tenant_id, account_code=account_code, date_from=date_from, date_to=date_to
        )
        if isinstance(result, Err):
            _refuse(connection, result)
    return jsonable(result.value)


@router.get("/reports/balances")
def account_balances(
    as_of: datetime.date,
    prefixes: str = "42,43,44",
    tenant: TenantContext = Depends(require_permission("finance.view_ledger")),
) -> list[dict]:
    with get_connection() as connection:
        return jsonable(
            LedgerReportService(connection).account_balances(
                tenant_id=tenant.tenant_id,
                prefixes=[prefix.strip() for prefix in prefixes.split(",") if prefix.strip()],
                as_of=as_of,
            )
        )
