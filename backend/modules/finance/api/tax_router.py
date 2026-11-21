"""Tax routes: the tax-code catalogue (named VAT rates, the default per side) and the VAT report."""
from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from core.db import get_connection
from core.domain.result import Err, err_detail
from core.tax_codes import TaxCodeService
from core.tenancy import TenantContext, require_permission, require_session, user_has_permission
from modules.finance.api.ledger_router import jsonable
from modules.finance.api.vat_report_service import VatReportService

router = APIRouter(prefix="/finance", tags=["finance.tax"])

MANAGE = "finance.manage_tax_codes"
READERS = ("finance.view_ledger", "finance.view_invoices", "finance.manage_tax_codes", "sales.view_orders",
           "procurement.view_purchase_invoices")


def _unwrap(connection, result) -> Any:
    if isinstance(result, Err):
        connection.rollback()
        code = status.HTTP_404_NOT_FOUND if result.code == "NOT_FOUND" else status.HTTP_400_BAD_REQUEST
        raise HTTPException(code, err_detail(result))
    connection.commit()
    return result.value


class CreateTaxCodeRequest(BaseModel):
    code: str
    name_fr: str
    name_en: str = ""
    rate: Decimal
    applies_to: str = "both"
    exempt: bool = False


class UpdateTaxCodeRequest(BaseModel):
    name_fr: str | None = None
    name_en: str | None = None
    rate: Decimal | None = None
    applies_to: str | None = None
    exempt: bool | None = None
    active: bool | None = None


class DefaultTaxCodeRequest(BaseModel):
    side: str


@router.get("/tax-codes")
def list_tax_codes(include_inactive: bool = False, side: str | None = None,
                   tenant: TenantContext = Depends(require_session)) -> list[dict]:
    with get_connection() as connection:
        # Reference data: anyone who prices or invoices may read it.
        if not any(user_has_permission(connection, user_id=tenant.user_id, permission=p) for p in READERS):
            raise HTTPException(status.HTTP_403_FORBIDDEN, {"code": "FORBIDDEN", "message": "requires a finance, sales or purchasing permission",
                                                            "message_fr": "droit finance, ventes ou achats requis"})
        codes = TaxCodeService(connection).list_codes(tenant_id=tenant.tenant_id, include_inactive=include_inactive, side=side)
        connection.commit()
        return jsonable(codes)


@router.post("/tax-codes", status_code=status.HTTP_201_CREATED)
def create_tax_code(body: CreateTaxCodeRequest, tenant: TenantContext = Depends(require_permission(MANAGE))) -> dict:
    with get_connection() as connection:
        return jsonable(_unwrap(connection, TaxCodeService(connection).create_code(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, **body.model_dump())))


@router.patch("/tax-codes/{code_id}")
def update_tax_code(code_id: str, body: UpdateTaxCodeRequest, tenant: TenantContext = Depends(require_permission(MANAGE))) -> dict:
    with get_connection() as connection:
        return jsonable(_unwrap(connection, TaxCodeService(connection).update_code(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, code_id=code_id, **body.model_dump())))


@router.post("/tax-codes/{code_id}/default")
def set_default_tax_code(code_id: str, body: DefaultTaxCodeRequest, tenant: TenantContext = Depends(require_permission(MANAGE))) -> dict:
    with get_connection() as connection:
        return jsonable(_unwrap(connection, TaxCodeService(connection).set_default(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, code_id=code_id, side=body.side)))


@router.get("/reports/vat")
def vat_report(date_from: datetime.date, date_to: datetime.date,
               tenant: TenantContext = Depends(require_permission("finance.view_ledger"))) -> dict:
    if date_from > date_to:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, err_detail(Err(
            "INVALID_PERIOD", "the start date is after the end date", "la date de début est après la date de fin")))
    with get_connection() as connection:
        return jsonable(VatReportService(connection).report(tenant_id=tenant.tenant_id, date_from=date_from, date_to=date_to))
