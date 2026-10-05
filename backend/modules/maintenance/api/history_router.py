"""The machine history endpoints (spec 2026-10-02-maintenance-history-design.md): indicators,
journal (+ Excel), one machine's logbook, one checkpoint's history. Read-only, view_jobs.
Costs are only returned to a holder of warehouse.view_valuation."""
from __future__ import annotations

import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from core.db import get_connection
from core.domain.result import Err, err_detail
from core.tenancy import TenantContext, require_permission, user_has_permission
from modules.maintenance.api.history_export import journal_workbook
from modules.maintenance.api.history_service import HistoryService
from modules.maintenance.api.history_sources import production_readings

# No prefix: included into modules/maintenance/api/router.py, which carries /maintenance.
router = APIRouter(tags=["maintenance.history"])

_VIEW = "maintenance.view_jobs"
_STATUS_BY_CODE = {"NOT_FOUND": status.HTTP_404_NOT_FOUND}
_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _period(date_from: datetime.date | None, date_to: datetime.date | None) -> tuple[datetime.date, datetime.date]:
    today = datetime.date.today()
    return date_from or datetime.date(today.year, 1, 1), date_to or today


def _service(connection) -> HistoryService:
    return HistoryService(connection, production=production_readings(connection))


def _costs_visible(connection, tenant: TenantContext) -> bool:
    return user_has_permission(connection, user_id=tenant.user_id, permission="warehouse.view_valuation")


def _unwrap(result):
    if isinstance(result, Err):
        raise HTTPException(_STATUS_BY_CODE.get(result.code, status.HTTP_422_UNPROCESSABLE_ENTITY), err_detail(result))
    return result.value


@router.get("/history/indicators")
def history_indicators(
    date_from: datetime.date | None = Query(default=None, alias="from"),
    date_to: datetime.date | None = Query(default=None, alias="to"),
    equipment_id: str | None = None,
    tenant: TenantContext = Depends(require_permission(_VIEW)),
) -> dict:
    start, end = _period(date_from, date_to)
    with get_connection() as connection:
        return _unwrap(
            _service(connection).indicators(
                tenant_id=tenant.tenant_id, date_from=start, date_to=end, equipment_id=equipment_id,
                costs_visible=_costs_visible(connection, tenant),
            )
        )


def _journal(connection, tenant, date_from, date_to, equipment_id, kind, journal_status) -> dict:
    start, end = _period(date_from, date_to)
    return _unwrap(
        _service(connection).journal(
            tenant_id=tenant.tenant_id, date_from=start, date_to=end, equipment_id=equipment_id, kind=kind,
            status=journal_status, costs_visible=_costs_visible(connection, tenant),
        )
    )


@router.get("/history/journal")
def history_journal(
    date_from: datetime.date | None = Query(default=None, alias="from"),
    date_to: datetime.date | None = Query(default=None, alias="to"),
    equipment_id: str | None = None,
    kind: str | None = None,
    journal_status: str = Query(default="closed", alias="status"),
    tenant: TenantContext = Depends(require_permission(_VIEW)),
) -> dict:
    with get_connection() as connection:
        return _journal(connection, tenant, date_from, date_to, equipment_id, kind, journal_status)


@router.get("/history/journal/export")
def history_journal_export(
    date_from: datetime.date | None = Query(default=None, alias="from"),
    date_to: datetime.date | None = Query(default=None, alias="to"),
    equipment_id: str | None = None,
    kind: str | None = None,
    journal_status: str = Query(default="closed", alias="status"),
    lang: str = "fr",
    tenant: TenantContext = Depends(require_permission(_VIEW)),
) -> Response:
    with get_connection() as connection:
        journal = _journal(connection, tenant, date_from, date_to, equipment_id, kind, journal_status)
    filename = f"maintenance-journal-{journal['from']}_{journal['to']}.xlsx"
    return Response(
        content=journal_workbook(journal, lang=lang),
        media_type=_XLSX,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/equipment/{equipment_id}/history")
def equipment_history(
    equipment_id: str,
    date_from: datetime.date | None = Query(default=None, alias="from"),
    date_to: datetime.date | None = Query(default=None, alias="to"),
    tenant: TenantContext = Depends(require_permission(_VIEW)),
) -> dict:
    start, end = _period(date_from, date_to)
    with get_connection() as connection:
        return _unwrap(
            _service(connection).equipment_history(
                tenant_id=tenant.tenant_id, equipment_id=equipment_id, date_from=start, date_to=end,
                costs_visible=_costs_visible(connection, tenant),
            )
        )


@router.get("/checkpoints/{checkpoint_id}/history")
def checkpoint_history(checkpoint_id: str, tenant: TenantContext = Depends(require_permission(_VIEW))) -> dict:
    with get_connection() as connection:
        return _unwrap(_service(connection).checkpoint_history(tenant_id=tenant.tenant_id, checkpoint_id=checkpoint_id))
