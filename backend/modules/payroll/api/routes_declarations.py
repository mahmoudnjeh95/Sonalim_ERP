"""HTTP routes for the monthly declarations and the annual recap (JSON or CSV)."""
from __future__ import annotations

import datetime
from typing import Literal

from fastapi import APIRouter, Depends

from core.tenancy import TenantContext, require_permission
from modules.payroll.api import http
from modules.payroll.api.declaration_service import DeclarationService, declaration_json
from modules.payroll.domain.declarations import to_csv

router = APIRouter()
VIEW = require_permission("payroll.view_declarations")


@router.get("/declarations/codes")
def declaration_codes(period: datetime.date, tenant: TenantContext = Depends(VIEW)):
    with http.get_connection() as connection:
        return DeclarationService(connection).codes(tenant_id=tenant.tenant_id, period=period)


@router.get("/declarations/annual")
def annual_recap(year: int, format: Literal["json", "csv"] = "json", tenant: TenantContext = Depends(VIEW)):
    with http.get_connection() as connection:
        recap = DeclarationService(connection).annual(tenant_id=tenant.tenant_id, year=year)
    if format == "csv":
        return http.csv_response(f"recap-annuel-{year}.csv", to_csv(recap))
    return declaration_json(recap, year=year)


@router.get("/declarations")
def declaration(period: datetime.date, code: str, format: Literal["json", "csv"] = "json", tenant: TenantContext = Depends(VIEW)):
    with http.get_connection() as connection:
        built = http.finish(connection, DeclarationService(connection).declaration(tenant_id=tenant.tenant_id, period=period, code=code))
    if format == "csv":
        return http.csv_response(f"{code.lower()}-{period:%Y-%m}.csv", to_csv(built))
    return declaration_json(built, period=period)
