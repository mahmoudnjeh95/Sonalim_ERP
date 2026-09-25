from __future__ import annotations

import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from core.api.service import CoreService
from core.db import get_connection
from core.domain.entities import Currency
from core.domain.exchange_rate import BASE_CURRENCY, ExchangeRate
from core.domain.result import Err, err_detail
from core.tenancy import TenantContext, require_permission

router = APIRouter(prefix="/core/exchange-rates", tags=["core.exchange-rates"])
currencies_router = APIRouter(prefix="/core/currencies", tags=["core.currencies"])


class RecordExchangeRateRequest(BaseModel):
    currency_code: str
    rate_to_base: float
    effective_date: datetime.date
    source: str = "manual"


class CreateCurrencyRequest(BaseModel):
    code: str
    name: str
    decimal_places: int = 2


def _rate_response(rate: ExchangeRate) -> dict:
    return {
        "id": rate.id,
        "currency_code": rate.currency_code,
        "rate_to_base": rate.rate_to_base,
        "effective_date": rate.effective_date,
        "source": rate.source,
    }


def _currency_response(currency: Currency) -> dict:
    return {"code": currency.code, "name": currency.name, "decimal_places": currency.decimal_places}


@currencies_router.get("")
def list_currencies(tenant: TenantContext = Depends(require_permission("core.view_exchange_rates"))) -> list[dict]:
    with get_connection() as connection:
        service = CoreService(connection)
        currencies = service.list_currencies()
    return [_currency_response(currency) for currency in currencies]


@currencies_router.post("", status_code=status.HTTP_201_CREATED)
def create_currency(
    body: CreateCurrencyRequest, tenant: TenantContext = Depends(require_permission("core.manage_exchange_rates"))
) -> dict:
    with get_connection() as connection:
        service = CoreService(connection)
        result = service.create_currency(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, code=body.code, name=body.name, decimal_places=body.decimal_places
        )
        if isinstance(result, Err):
            connection.rollback()
            raise HTTPException(status.HTTP_400_BAD_REQUEST, err_detail(result))
        connection.commit()
    return _currency_response(result.value)


@router.post("", status_code=status.HTTP_201_CREATED)
def record_exchange_rate(
    body: RecordExchangeRateRequest,
    tenant: TenantContext = Depends(require_permission("core.manage_exchange_rates")),
) -> dict:
    with get_connection() as connection:
        service = CoreService(connection)
        result = service.record_exchange_rate(
            tenant_id=tenant.tenant_id,
            currency_code=body.currency_code,
            rate_to_base=body.rate_to_base,
            effective_date=body.effective_date,
            source=body.source,
            actor_id=tenant.user_id,
        )
        if isinstance(result, Err):
            connection.rollback()
            raise HTTPException(status.HTTP_400_BAD_REQUEST, err_detail(result))
        connection.commit()
    return _rate_response(result.value)


@router.get("")
def list_exchange_rates(
    currency_code: str | None = None,
    tenant: TenantContext = Depends(require_permission("core.view_exchange_rates")),
) -> list[dict]:
    with get_connection() as connection:
        service = CoreService(connection)
        rates = service.list_exchange_rates(tenant_id=tenant.tenant_id, currency_code=currency_code)
    return [_rate_response(rate) for rate in rates]


@router.get("/convert")
def convert_amount(
    amount: float,
    currency_code: str,
    as_of: datetime.date,
    tenant: TenantContext = Depends(require_permission("core.view_exchange_rates")),
) -> dict:
    with get_connection() as connection:
        service = CoreService(connection)
        result = service.convert_amount(tenant_id=tenant.tenant_id, amount=amount, currency_code=currency_code, as_of_date=as_of)
        if isinstance(result, Err):
            raise HTTPException(status.HTTP_404_NOT_FOUND, err_detail(result))
    base_amount, rate_used = result.value
    return {
        "amount": amount,
        "currency_code": currency_code,
        "as_of": as_of.isoformat(),
        "base_currency": BASE_CURRENCY,
        "base_amount": base_amount,
        "rate_used": rate_used,
    }


@router.get("/today")
def get_today_rates(tenant: TenantContext = Depends(require_permission("core.view_exchange_rates"))) -> list[dict]:
    today = datetime.date.today()
    with get_connection() as connection:
        service = CoreService(connection)
        currencies = service.list_currencies()
        rows: list[dict] = []
        for currency in currencies:
            if currency.code == BASE_CURRENCY:
                rows.append(
                    {
                        "currency_code": BASE_CURRENCY,
                        "rate_to_base": 1.0,
                        "effective_date": today.isoformat(),
                        "source": "base",
                        "is_today": True,
                    }
                )
                continue
            rate = service.get_exchange_rate(tenant_id=tenant.tenant_id, currency_code=currency.code, as_of_date=today)
            rows.append(
                {
                    "currency_code": currency.code,
                    "rate_to_base": rate.rate_to_base if rate else None,
                    "effective_date": rate.effective_date if rate else None,
                    "source": rate.source if rate else None,
                    "is_today": rate is not None and rate.effective_date == today.isoformat(),
                }
            )
    return rows
