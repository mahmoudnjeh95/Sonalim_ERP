from __future__ import annotations

import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from core.db import get_connection
from core.domain.result import Err, err_detail
from core.tenancy import TenantContext, require_permission
from modules.warehouse.api.analytics_service import WarehouseAnalyticsService
from modules.warehouse.api.location_service import LocationService
from modules.warehouse.api.lot_service import LotService
from modules.warehouse.api.service import StockService
from modules.warehouse.domain.entities import Location
from modules.warehouse.domain.lot import Lot, LOT_VALID_TRANSITIONS

router = APIRouter(prefix="/warehouse", tags=["warehouse"])


class ReserveStockRequest(BaseModel):
    product_id: str
    location_id: str
    quantity: float
    reference: str
    correlation_id: str


class IssueStockRequest(BaseModel):
    product_id: str
    location_id: str
    quantity: float
    reference: str


class AdjustStockRequest(BaseModel):
    product_id: str
    location_id: str
    delta: float
    reason: str


class TransferStockRequest(BaseModel):
    product_id: str
    from_location_id: str
    to_location_id: str
    quantity: float
    correlation_id: str
    reference: str


class AdminSetStockRequest(BaseModel):
    quantity_on_hand: float
    quantity_reserved: float
    quantity_in_production: float


class CreateLocationRequest(BaseModel):
    code: str
    name: str
    # A blocked location holds stock that cannot be promised — quarantine above all.
    is_blocked: bool = False
    blocked_reason: str | None = None


def _location_response(location: Location) -> dict:
    return {
        "id": location.id,
        "code": location.code,
        "name": location.name,
        "is_blocked": location.is_blocked,
        "blocked_reason": location.blocked_reason,
    }


@router.get("/locations")
def list_locations(tenant: TenantContext = Depends(require_permission("warehouse.view_moves"))) -> list[dict]:
    with get_connection() as connection:
        service = LocationService(connection)
        locations = service.list_locations(tenant_id=tenant.tenant_id)
    return [_location_response(location) for location in locations]


@router.post("/locations", status_code=status.HTTP_201_CREATED)
def create_location(
    body: CreateLocationRequest, tenant: TenantContext = Depends(require_permission("warehouse.manage_stock"))
) -> dict:
    with get_connection() as connection:
        service = LocationService(connection)
        location = service.create_location(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            code=body.code,
            name=body.name,
            is_blocked=body.is_blocked,
            blocked_reason=body.blocked_reason,
        )
        connection.commit()
    return _location_response(location)


class UpdateLocationRequest(BaseModel):
    code: str | None = None
    name: str | None = None
    is_blocked: bool | None = None
    blocked_reason: str | None = None


@router.patch("/locations/{location_id}")
def update_location(
    location_id: str,
    body: UpdateLocationRequest,
    tenant: TenantContext = Depends(require_permission("warehouse.admin_locations")),
) -> dict:
    with get_connection() as connection:
        service = LocationService(connection)
        result = service.update_location(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            location_id=location_id,
            code=body.code,
            name=body.name,
            is_blocked=body.is_blocked,
            blocked_reason=body.blocked_reason,
        )
        if isinstance(result, Err):
            connection.rollback()
            code = status.HTTP_404_NOT_FOUND if result.code == "NOT_FOUND" else status.HTTP_400_BAD_REQUEST
            raise HTTPException(code, err_detail(result))
        connection.commit()
    return _location_response(result.value)


@router.get("/stock")
def list_stock(
    location_id: str | None = None, tenant: TenantContext = Depends(require_permission("warehouse.view_moves"))
) -> list[dict]:
    with get_connection() as connection:
        service = StockService(connection)
        items = service.list_stock_items(tenant.tenant_id, location_id=location_id)
    return [
        {
            "location_id": item.location_id,
            "product_id": item.product_id,
            "quantity_on_hand": item.quantity_on_hand,
            "quantity_reserved": item.quantity_reserved,
            "quantity_in_production": item.quantity_in_production,
            "quantity_available": item.quantity_available,
        }
        for item in items
    ]


@router.get("/stock/moves")
def list_stock_moves(
    location_id: str | None = None,
    product_id: str | None = None,
    move_type: str | None = None,
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
    limit: int = Query(default=200, le=5000),
    tenant: TenantContext = Depends(require_permission("warehouse.view_moves")),
) -> list[dict]:
    with get_connection() as connection:
        service = StockService(connection)
        return service.list_stock_moves(
            tenant_id=tenant.tenant_id,
            location_id=location_id,
            product_id=product_id,
            move_type=move_type,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
        )


@router.get("/analytics/overview")
def analytics_overview(
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
    consumption_window_days: int = Query(default=30, ge=1, le=365),
    dormant_after_days: int = Query(default=60, ge=1, le=730),
    tenant: TenantContext = Depends(require_permission("warehouse.view_moves")),
) -> dict:
    """Stock KPIs for the warehouse screen. The period bounds the movement figures
    (flows, corrections, daily chart); stock levels, days of cover, dormant stock
    and expiring lots are always "as of today". Defaults to the last 30 days."""
    today = datetime.date.today()
    if date_to is None:
        date_to = today
    if date_from is None:
        date_from = date_to - datetime.timedelta(days=29)
    with get_connection() as connection:
        service = WarehouseAnalyticsService(connection)
        return service.overview(
            tenant_id=tenant.tenant_id,
            date_from=date_from,
            date_to=date_to,
            consumption_window_days=consumption_window_days,
            dormant_after_days=dormant_after_days,
            today=today,
        )


@router.get("/stock/{product_id}/available")
def get_available(
    product_id: str,
    location_id: str,
    tenant: TenantContext = Depends(require_permission("warehouse.view_moves")),
) -> dict:
    with get_connection() as connection:
        service = StockService(connection)
        available = service.get_available_quantity(tenant.tenant_id, product_id, location_id)
    return {"product_id": product_id, "location_id": location_id, "available": available}


@router.post("/stock/reserve", status_code=status.HTTP_201_CREATED)
def reserve_stock(
    body: ReserveStockRequest, tenant: TenantContext = Depends(require_permission("warehouse.manage_stock"))
) -> dict:
    with get_connection() as connection:
        service = StockService(connection)
        result = service.reserve_stock(
            tenant_id=tenant.tenant_id,
            product_id=body.product_id,
            location_id=body.location_id,
            quantity=body.quantity,
            correlation_id=body.correlation_id,
            reference=body.reference,
            actor_id=tenant.user_id,
        )
        if isinstance(result, Err):
            connection.rollback()
            raise HTTPException(status.HTTP_409_CONFLICT, err_detail(result))
        connection.commit()
    return {
        "location_id": result.value.location_id,
        "product_id": result.value.product_id,
        "quantity_on_hand": result.value.quantity_on_hand,
        "quantity_reserved": result.value.quantity_reserved,
    }


@router.post("/stock/issue", status_code=status.HTTP_201_CREATED)
def issue_stock(
    body: IssueStockRequest, tenant: TenantContext = Depends(require_permission("warehouse.manage_stock"))
) -> dict:
    with get_connection() as connection:
        service = StockService(connection)
        result = service.issue_stock(
            tenant_id=tenant.tenant_id,
            product_id=body.product_id,
            location_id=body.location_id,
            quantity=body.quantity,
            reference=body.reference,
            actor_id=tenant.user_id,
        )
        if isinstance(result, Err):
            connection.rollback()
            raise HTTPException(status.HTTP_409_CONFLICT, err_detail(result))
        connection.commit()
    return {
        "location_id": result.value.location_id,
        "product_id": result.value.product_id,
        "quantity_on_hand": result.value.quantity_on_hand,
        "quantity_reserved": result.value.quantity_reserved,
    }


@router.post("/stock/adjust", status_code=status.HTTP_201_CREATED)
def adjust_stock(
    body: AdjustStockRequest, tenant: TenantContext = Depends(require_permission("warehouse.adjust_stock"))
) -> dict:
    with get_connection() as connection:
        service = StockService(connection)
        result = service.adjust_stock(
            tenant_id=tenant.tenant_id,
            product_id=body.product_id,
            location_id=body.location_id,
            delta=body.delta,
            reason=body.reason,
            actor_id=tenant.user_id,
        )
        if isinstance(result, Err):
            connection.rollback()
            raise HTTPException(status.HTTP_409_CONFLICT, err_detail(result))
        connection.commit()
    return {
        "location_id": result.value.location_id,
        "product_id": result.value.product_id,
        "quantity_on_hand": result.value.quantity_on_hand,
        "quantity_reserved": result.value.quantity_reserved,
    }


@router.post("/stock/transfer", status_code=status.HTTP_201_CREATED)
def transfer_stock(
    body: TransferStockRequest, tenant: TenantContext = Depends(require_permission("warehouse.manage_stock"))
) -> dict:
    with get_connection() as connection:
        service = StockService(connection)
        result = service.transfer_stock(
            tenant_id=tenant.tenant_id,
            product_id=body.product_id,
            from_location_id=body.from_location_id,
            to_location_id=body.to_location_id,
            quantity=body.quantity,
            correlation_id=body.correlation_id,
            reference=body.reference,
            actor_id=tenant.user_id,
        )
        if isinstance(result, Err):
            connection.rollback()
            raise HTTPException(status.HTTP_409_CONFLICT, err_detail(result))
        connection.commit()
    issued, received = result.value
    return {
        "from": {"location_id": issued.location_id, "quantity_on_hand": issued.quantity_on_hand},
        "to": {"location_id": received.location_id, "quantity_on_hand": received.quantity_on_hand},
        "product_id": body.product_id,
        "quantity": body.quantity,
    }


@router.put("/stock-items/{location_id}/{product_id}")
def admin_set_stock(
    location_id: str,
    product_id: str,
    body: AdminSetStockRequest,
    tenant: TenantContext = Depends(require_permission("warehouse.admin_stock")),
) -> dict:
    with get_connection() as connection:
        service = StockService(connection)
        result = service.admin_set_stock(
            tenant_id=tenant.tenant_id,
            product_id=product_id,
            location_id=location_id,
            quantity_on_hand=body.quantity_on_hand,
            quantity_reserved=body.quantity_reserved,
            quantity_in_production=body.quantity_in_production,
            actor_id=tenant.user_id,
        )
        if isinstance(result, Err):
            connection.rollback()
            raise HTTPException(status.HTTP_400_BAD_REQUEST, err_detail(result))
        connection.commit()
    return {
        "location_id": result.value.location_id,
        "product_id": result.value.product_id,
        "quantity_on_hand": result.value.quantity_on_hand,
        "quantity_reserved": result.value.quantity_reserved,
        "quantity_in_production": result.value.quantity_in_production,
        "quantity_available": result.value.quantity_available,
    }


@router.delete("/stock-items/{location_id}/{product_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def delete_stock_item(
    location_id: str,
    product_id: str,
    tenant: TenantContext = Depends(require_permission("warehouse.admin_stock")),
) -> None:
    with get_connection() as connection:
        service = StockService(connection)
        result = service.delete_stock_item(
            tenant_id=tenant.tenant_id, product_id=product_id, location_id=location_id, actor_id=tenant.user_id
        )
        if isinstance(result, Err):
            connection.rollback()
            code = status.HTTP_404_NOT_FOUND if result.code == "NOT_FOUND" else status.HTTP_400_BAD_REQUEST
            raise HTTPException(code, err_detail(result))
        connection.commit()


# --- Lots/serials -----------------------------------------------------------------------


class TransitionLotRequest(BaseModel):
    new_status: str


class SetLotExpiryRequest(BaseModel):
    expiry_date: datetime.date


def _lot_response(lot: Lot) -> dict:
    return {
        "id": lot.id,
        "product_id": lot.product_id,
        "lot_number": lot.lot_number,
        "status": lot.status,
        "expiry_date": lot.expiry_date,
        "produced_at": lot.produced_at,
        "source_type": lot.source_type,
        "source_id": lot.source_id,
    }


def _lot_err_status(code: str) -> int:
    if code == "NOT_FOUND":
        return status.HTTP_404_NOT_FOUND
    if code == "INVALID_TRANSITION":
        return status.HTTP_409_CONFLICT
    return status.HTTP_400_BAD_REQUEST


@router.get("/lots")
def list_lots(
    product_id: str | None = None,
    source_type: str | None = None,
    without_expiry: bool = False,
    tenant: TenantContext = Depends(require_permission("warehouse.view_lots")),
) -> list[dict]:
    with get_connection() as connection:
        service = LotService(connection)
        lots = service.list_lots(
            tenant_id=tenant.tenant_id, product_id=product_id, source_type=source_type, without_expiry=without_expiry
        )
    return [_lot_response(lot) for lot in lots]


@router.get("/lots/statuses")
def list_lot_statuses(tenant: TenantContext = Depends(require_permission("warehouse.view_lots"))) -> list[str]:
    return sorted(LOT_VALID_TRANSITIONS.keys())


@router.get("/lot-stock")
def list_lot_stock(
    product_id: str | None = None, tenant: TenantContext = Depends(require_permission("warehouse.view_lots"))
) -> list[dict]:
    with get_connection() as connection:
        service = LotService(connection)
        return service.list_lot_stock(tenant_id=tenant.tenant_id, product_id=product_id)


@router.patch("/lots/{lot_id}/expiry")
def set_lot_expiry(
    lot_id: str,
    body: SetLotExpiryRequest,
    tenant: TenantContext = Depends(require_permission("warehouse.set_lot_expiry")),
) -> dict:
    with get_connection() as connection:
        service = LotService(connection)
        result = service.set_expiry(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, lot_id=lot_id, expiry_date=body.expiry_date
        )
        if isinstance(result, Err):
            connection.rollback()
            raise HTTPException(_lot_err_status(result.code), err_detail(result))
        connection.commit()
    return _lot_response(result.value)


@router.post("/lots/{lot_id}/transition")
def transition_lot(
    lot_id: str,
    body: TransitionLotRequest,
    tenant: TenantContext = Depends(require_permission("warehouse.manage_lots")),
) -> dict:
    with get_connection() as connection:
        service = LotService(connection)
        result = service.transition_lot_status(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, lot_id=lot_id, new_status=body.new_status
        )
        if isinstance(result, Err):
            connection.rollback()
            raise HTTPException(_lot_err_status(result.code), err_detail(result))
        connection.commit()
    return _lot_response(result.value)
