from __future__ import annotations

import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from core.db import get_connection
from core.domain.result import Err, err_detail
from core.tenancy import TenantContext, require_permission
from modules.warehouse.api.analytics_service import WarehouseAnalyticsService
from modules.warehouse.api.barcode_service import BarcodeService
from modules.warehouse.api.cycle_count_service import CycleCountService
from modules.warehouse.api.fulfillment_service import FulfillmentService
from modules.warehouse.api.location_service import LocationService
from modules.warehouse.api.lot_service import LotService
from modules.warehouse.api.putaway_service import PutAwayService
from modules.warehouse.api.replenishment_service import ReplenishmentService
from modules.warehouse.api.reservation_service import ReservationService
from modules.warehouse.api.service import StockService
from modules.warehouse.api.site_service import SiteService
from modules.warehouse.api.valuation_service import ValuationService
from modules.warehouse.domain.barcode import ProductBarcode
from modules.warehouse.domain.cycle_count import CycleCount, CycleCountLine
from modules.warehouse.domain.entities import Location, Site
from modules.warehouse.domain.fulfillment import PickList, PickListLine, Shipment
from modules.warehouse.domain.lot import Lot, LOT_VALID_TRANSITIONS
from modules.warehouse.domain.putaway import PutawayRule
from modules.warehouse.domain.replenishment import ReorderRule, ReplenishmentProposal
from modules.warehouse.domain.reservation import StockReservation
from modules.warehouse.domain.valuation import CostLayer

router = APIRouter(prefix="/warehouse", tags=["warehouse"])


class ReserveStockRequest(BaseModel):
    product_id: str
    location_id: str
    quantity: float
    reference: str
    correlation_id: str
    # Optional hold expiry (timezone-aware); the worker releases it once lapsed.
    expires_at: datetime.datetime | None = None


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
    # Optional so the Stock tab's existing location dialog (predates sites)
    # keeps working unchanged -- an omitted site_id falls back to the
    # tenant's default site, same as a location created before Phase 1.
    site_id: str | None = None
    location_type: Literal["zone", "aisle", "rack", "bin"] = "bin"
    parent_location_id: str | None = None
    sequence: int | None = None
    # A blocked location holds stock that cannot be promised — quarantine above all.
    is_blocked: bool = False
    blocked_reason: str | None = None


def _location_response(location: Location) -> dict:
    return {
        "id": location.id,
        "code": location.code,
        "name": location.name,
        "site_id": location.site_id,
        "location_type": location.location_type,
        "parent_location_id": location.parent_location_id,
        "sequence": location.sequence,
        "is_blocked": location.is_blocked,
        "blocked_reason": location.blocked_reason,
    }


def _site_response(site: Site) -> dict:
    return {"id": site.id, "code": site.code, "name": site.name, "address": site.address, "is_active": site.is_active}


@router.get("/locations")
def list_locations(
    site_id: str | None = None,
    location_type: str | None = None,
    parent_location_id: str | None = None,
    tenant: TenantContext = Depends(require_permission("warehouse.view_moves")),
) -> list[dict]:
    with get_connection() as connection:
        service = LocationService(connection)
        locations = service.list_locations(
            tenant_id=tenant.tenant_id, site_id=site_id, location_type=location_type, parent_location_id=parent_location_id
        )
    return [_location_response(location) for location in locations]


@router.get("/locations/tree")
def get_location_tree(
    site_id: str, tenant: TenantContext = Depends(require_permission("warehouse.view_moves"))
) -> list[dict]:
    with get_connection() as connection:
        service = LocationService(connection)
        locations = service.get_location_tree(tenant_id=tenant.tenant_id, site_id=site_id)
    return [_location_response(location) for location in locations]


@router.post("/locations", status_code=status.HTTP_201_CREATED)
def create_location(
    body: CreateLocationRequest, tenant: TenantContext = Depends(require_permission("warehouse.manage_stock"))
) -> dict:
    with get_connection() as connection:
        service = LocationService(connection)
        result = service.create_location(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            code=body.code,
            name=body.name,
            site_id=body.site_id,
            location_type=body.location_type,
            parent_location_id=body.parent_location_id,
            sequence=body.sequence,
            is_blocked=body.is_blocked,
            blocked_reason=body.blocked_reason,
        )
        if isinstance(result, Err):
            connection.rollback()
            code = status.HTTP_404_NOT_FOUND if result.code == "NOT_FOUND" else status.HTTP_400_BAD_REQUEST
            raise HTTPException(code, err_detail(result))
        connection.commit()
    return _location_response(result.value)


class ReparentLocationRequest(BaseModel):
    parent_location_id: str | None = None


@router.patch("/locations/{location_id}/reparent")
def reparent_location(
    location_id: str,
    body: ReparentLocationRequest,
    tenant: TenantContext = Depends(require_permission("warehouse.admin_locations")),
) -> dict:
    with get_connection() as connection:
        service = LocationService(connection)
        result = service.reparent_location(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            location_id=location_id,
            parent_location_id=body.parent_location_id,
        )
        if isinstance(result, Err):
            connection.rollback()
            code = status.HTTP_404_NOT_FOUND if result.code == "NOT_FOUND" else status.HTTP_400_BAD_REQUEST
            raise HTTPException(code, err_detail(result))
        connection.commit()
    return _location_response(result.value)


# --- Sites --------------------------------------------------------------------------------


class CreateSiteRequest(BaseModel):
    code: str
    name: str
    address: str | None = None


class UpdateSiteRequest(BaseModel):
    code: str | None = None
    name: str | None = None
    address: str | None = None
    is_active: bool | None = None


@router.get("/sites")
def list_sites(tenant: TenantContext = Depends(require_permission("warehouse.view_moves"))) -> list[dict]:
    with get_connection() as connection:
        service = SiteService(connection)
        sites = service.list_sites(tenant_id=tenant.tenant_id)
    return [_site_response(site) for site in sites]


@router.post("/sites", status_code=status.HTTP_201_CREATED)
def create_site(
    body: CreateSiteRequest, tenant: TenantContext = Depends(require_permission("warehouse.manage_sites"))
) -> dict:
    with get_connection() as connection:
        service = SiteService(connection)
        result = service.create_site(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, code=body.code, name=body.name, address=body.address
        )
        if isinstance(result, Err):
            connection.rollback()
            raise HTTPException(status.HTTP_400_BAD_REQUEST, err_detail(result))
        connection.commit()
    return _site_response(result.value)


@router.patch("/sites/{site_id}")
def update_site(
    site_id: str,
    body: UpdateSiteRequest,
    tenant: TenantContext = Depends(require_permission("warehouse.admin_sites")),
) -> dict:
    with get_connection() as connection:
        service = SiteService(connection)
        result = service.update_site(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            site_id=site_id,
            code=body.code,
            name=body.name,
            address=body.address,
            is_active=body.is_active,
        )
        if isinstance(result, Err):
            connection.rollback()
            code = status.HTTP_404_NOT_FOUND if result.code == "NOT_FOUND" else status.HTTP_400_BAD_REQUEST
            raise HTTPException(code, err_detail(result))
        connection.commit()
    return _site_response(result.value)


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
    location_id: str | None = None,
    site_id: str | None = None,
    tenant: TenantContext = Depends(require_permission("warehouse.view_moves")),
) -> list[dict]:
    with get_connection() as connection:
        service = StockService(connection)
        items = service.list_stock_items(tenant.tenant_id, location_id=location_id, site_id=site_id)
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
    site_id: str | None = None,
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
            site_id=site_id,
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
            expires_at=body.expires_at,
        )
        if isinstance(result, Err):
            connection.rollback()
            code = status.HTTP_400_BAD_REQUEST if result.code == "INVALID_EXPIRY" else status.HTTP_409_CONFLICT
            raise HTTPException(code, err_detail(result))
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


# --- Cycle counts -----------------------------------------------------------------------


class CreateCycleCountRequest(BaseModel):
    site_id: str
    scope_location_id: str | None = None
    count_type: Literal["scheduled", "blind"] = "scheduled"
    scheduled_for: datetime.date | None = None


class UpdateCycleCountRequest(BaseModel):
    scheduled_for: datetime.date | None = None
    count_type: Literal["scheduled", "blind"] | None = None


class SubmitLineCountRequest(BaseModel):
    counted_quantity: float


class ResolveLineVarianceRequest(BaseModel):
    decision: Literal["approve", "reject"]


class CompleteCycleCountRequest(BaseModel):
    correlation_id: str


def _cycle_count_response(count: CycleCount) -> dict:
    return {
        "id": count.id,
        "site_id": count.site_id,
        "scope_location_id": count.scope_location_id,
        "count_type": count.count_type,
        "status": count.status,
        "scheduled_for": count.scheduled_for,
        "started_at": count.started_at,
        "completed_at": count.completed_at,
        "created_by": count.created_by,
        "created_at": count.created_at,
    }


def _cycle_count_line_response(line: CycleCountLine) -> dict:
    return {
        "id": line.id,
        "cycle_count_id": line.cycle_count_id,
        "location_id": line.location_id,
        "product_id": line.product_id,
        "expected_quantity": line.expected_quantity,
        "counted_quantity": line.counted_quantity,
        "status": line.status,
        "resolution": line.resolution,
        "counted_by": line.counted_by,
        "counted_at": line.counted_at,
        "resolved_by": line.resolved_by,
        "resolved_at": line.resolved_at,
    }


def _cycle_count_err_status(code: str) -> int:
    if code == "NOT_FOUND":
        return status.HTTP_404_NOT_FOUND
    if code in ("INVALID_TRANSITION", "INVALID_STATE", "LINES_UNRESOLVED"):
        return status.HTTP_409_CONFLICT
    return status.HTTP_400_BAD_REQUEST


@router.get("/cycle-counts")
def list_cycle_counts(
    site_id: str | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    tenant: TenantContext = Depends(require_permission("warehouse.view_cycle_counts")),
) -> list[dict]:
    with get_connection() as connection:
        service = CycleCountService(connection)
        counts = service.list_counts(tenant_id=tenant.tenant_id, site_id=site_id, status=status_filter)
    return [_cycle_count_response(count) for count in counts]


@router.post("/cycle-counts", status_code=status.HTTP_201_CREATED)
def create_cycle_count(
    body: CreateCycleCountRequest, tenant: TenantContext = Depends(require_permission("warehouse.manage_cycle_counts"))
) -> dict:
    with get_connection() as connection:
        service = CycleCountService(connection)
        result = service.create_count(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            site_id=body.site_id,
            scope_location_id=body.scope_location_id,
            count_type=body.count_type,
            scheduled_for=body.scheduled_for,
        )
        if isinstance(result, Err):
            connection.rollback()
            raise HTTPException(_cycle_count_err_status(result.code), err_detail(result))
        connection.commit()
    return _cycle_count_response(result.value)


@router.get("/cycle-counts/{cycle_count_id}")
def get_cycle_count(
    cycle_count_id: str, tenant: TenantContext = Depends(require_permission("warehouse.view_cycle_counts"))
) -> dict:
    with get_connection() as connection:
        service = CycleCountService(connection)
        count_result = service.get_count(tenant_id=tenant.tenant_id, cycle_count_id=cycle_count_id)
        if isinstance(count_result, Err):
            raise HTTPException(_cycle_count_err_status(count_result.code), err_detail(count_result))
        lines_result = service.list_lines(tenant_id=tenant.tenant_id, cycle_count_id=cycle_count_id)
        if isinstance(lines_result, Err):
            raise HTTPException(_cycle_count_err_status(lines_result.code), err_detail(lines_result))
    return {**_cycle_count_response(count_result.value), "lines": [_cycle_count_line_response(line) for line in lines_result.value]}


@router.patch("/cycle-counts/{cycle_count_id}")
def update_cycle_count(
    cycle_count_id: str,
    body: UpdateCycleCountRequest,
    tenant: TenantContext = Depends(require_permission("warehouse.admin_cycle_counts")),
) -> dict:
    with get_connection() as connection:
        service = CycleCountService(connection)
        result = service.admin_update_count(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            cycle_count_id=cycle_count_id,
            scheduled_for=body.scheduled_for,
            count_type=body.count_type,
        )
        if isinstance(result, Err):
            connection.rollback()
            raise HTTPException(_cycle_count_err_status(result.code), err_detail(result))
        connection.commit()
    return _cycle_count_response(result.value)


@router.post("/cycle-counts/{cycle_count_id}/start")
def start_cycle_count(
    cycle_count_id: str, tenant: TenantContext = Depends(require_permission("warehouse.manage_cycle_counts"))
) -> dict:
    with get_connection() as connection:
        service = CycleCountService(connection)
        result = service.start_count(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, cycle_count_id=cycle_count_id)
        if isinstance(result, Err):
            connection.rollback()
            raise HTTPException(_cycle_count_err_status(result.code), err_detail(result))
        connection.commit()
    return _cycle_count_response(result.value)


@router.post("/cycle-counts/{cycle_count_id}/lines/{line_id}/count")
def submit_cycle_count_line(
    cycle_count_id: str,
    line_id: str,
    body: SubmitLineCountRequest,
    tenant: TenantContext = Depends(require_permission("warehouse.manage_cycle_counts")),
) -> dict:
    with get_connection() as connection:
        service = CycleCountService(connection)
        result = service.submit_line_count(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            cycle_count_id=cycle_count_id,
            line_id=line_id,
            counted_quantity=body.counted_quantity,
        )
        if isinstance(result, Err):
            connection.rollback()
            raise HTTPException(_cycle_count_err_status(result.code), err_detail(result))
        connection.commit()
    return _cycle_count_line_response(result.value)


@router.post("/cycle-counts/{cycle_count_id}/lines/{line_id}/resolve")
def resolve_cycle_count_line(
    cycle_count_id: str,
    line_id: str,
    body: ResolveLineVarianceRequest,
    tenant: TenantContext = Depends(require_permission("warehouse.manage_cycle_counts")),
) -> dict:
    with get_connection() as connection:
        service = CycleCountService(connection)
        result = service.resolve_line_variance(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            cycle_count_id=cycle_count_id,
            line_id=line_id,
            decision=body.decision,
        )
        if isinstance(result, Err):
            connection.rollback()
            raise HTTPException(_cycle_count_err_status(result.code), err_detail(result))
        connection.commit()
    return _cycle_count_line_response(result.value)


@router.post("/cycle-counts/{cycle_count_id}/complete")
def complete_cycle_count(
    cycle_count_id: str,
    body: CompleteCycleCountRequest,
    tenant: TenantContext = Depends(require_permission("warehouse.manage_cycle_counts")),
) -> dict:
    with get_connection() as connection:
        service = CycleCountService(connection)
        result = service.complete_count(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, cycle_count_id=cycle_count_id, correlation_id=body.correlation_id
        )
        if isinstance(result, Err):
            connection.rollback()
            raise HTTPException(_cycle_count_err_status(result.code), err_detail(result))
        connection.commit()
    return _cycle_count_response(result.value)


@router.post("/cycle-counts/{cycle_count_id}/cancel")
def cancel_cycle_count(
    cycle_count_id: str, tenant: TenantContext = Depends(require_permission("warehouse.manage_cycle_counts"))
) -> dict:
    with get_connection() as connection:
        service = CycleCountService(connection)
        result = service.cancel_count(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, cycle_count_id=cycle_count_id)
        if isinstance(result, Err):
            connection.rollback()
            raise HTTPException(_cycle_count_err_status(result.code), err_detail(result))
        connection.commit()
    return _cycle_count_response(result.value)


# --- Put-away -----------------------------------------------------------------------------


class CreatePutawayRuleRequest(BaseModel):
    site_id: str
    product_id: str
    target_location_id: str


class ConfirmPutawayRequest(BaseModel):
    site_id: str
    product_id: str
    from_location_id: str
    to_location_id: str
    quantity: float
    correlation_id: str


def _putaway_rule_response(rule: PutawayRule) -> dict:
    return {
        "id": rule.id,
        "site_id": rule.site_id,
        "product_id": rule.product_id,
        "target_location_id": rule.target_location_id,
        "created_by": rule.created_by,
        "created_at": rule.created_at,
    }


def _putaway_err_status(code: str) -> int:
    if code == "NOT_FOUND":
        return status.HTTP_404_NOT_FOUND
    return status.HTTP_400_BAD_REQUEST


@router.get("/putaway/suggestions")
def get_putaway_suggestions(
    site_id: str,
    product_id: str,
    from_location_id: str | None = None,
    tenant: TenantContext = Depends(require_permission("warehouse.view_putaway")),
) -> list[dict]:
    with get_connection() as connection:
        service = PutAwayService(connection)
        suggestions = service.suggest_locations(
            tenant_id=tenant.tenant_id, site_id=site_id, product_id=product_id, exclude_location_id=from_location_id
        )
    return [_location_response(location) for location in suggestions]


@router.get("/putaway/rules")
def list_putaway_rules(
    site_id: str | None = None, tenant: TenantContext = Depends(require_permission("warehouse.view_putaway"))
) -> list[dict]:
    with get_connection() as connection:
        service = PutAwayService(connection)
        rules = service.list_rules(tenant_id=tenant.tenant_id, site_id=site_id)
    return [_putaway_rule_response(rule) for rule in rules]


@router.post("/putaway/rules", status_code=status.HTTP_201_CREATED)
def create_putaway_rule(
    body: CreatePutawayRuleRequest, tenant: TenantContext = Depends(require_permission("warehouse.manage_putaway"))
) -> dict:
    with get_connection() as connection:
        service = PutAwayService(connection)
        result = service.create_rule(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            site_id=body.site_id,
            product_id=body.product_id,
            target_location_id=body.target_location_id,
        )
        if isinstance(result, Err):
            connection.rollback()
            raise HTTPException(_putaway_err_status(result.code), err_detail(result))
        connection.commit()
    return _putaway_rule_response(result.value)


@router.delete("/putaway/rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def delete_putaway_rule(
    rule_id: str, tenant: TenantContext = Depends(require_permission("warehouse.manage_putaway"))
) -> None:
    with get_connection() as connection:
        service = PutAwayService(connection)
        result = service.delete_rule(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, rule_id=rule_id)
        if isinstance(result, Err):
            connection.rollback()
            raise HTTPException(_putaway_err_status(result.code), err_detail(result))
        connection.commit()


@router.post("/putaway/confirm", status_code=status.HTTP_201_CREATED)
def confirm_putaway(
    body: ConfirmPutawayRequest, tenant: TenantContext = Depends(require_permission("warehouse.manage_putaway"))
) -> dict:
    with get_connection() as connection:
        service = PutAwayService(connection)
        result = service.confirm_putaway(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            site_id=body.site_id,
            product_id=body.product_id,
            from_location_id=body.from_location_id,
            to_location_id=body.to_location_id,
            quantity=body.quantity,
            correlation_id=body.correlation_id,
        )
        if isinstance(result, Err):
            connection.rollback()
            raise HTTPException(status.HTTP_409_CONFLICT, err_detail(result))
        connection.commit()
    return {"status": "ok"}


# --- Fulfillment (pick -> pack -> ship) -----------------------------------------------------


class SubmitPickRequest(BaseModel):
    quantity_picked: float


class CorrelatedRequest(BaseModel):
    correlation_id: str


class PackPickListRequest(BaseModel):
    package_count: int
    total_weight_kg: float | None = None
    carrier: str | None = None
    tracking_reference: str | None = None


class UpdateShipmentRequest(BaseModel):
    package_count: int | None = None
    total_weight_kg: float | None = None
    carrier: str | None = None
    tracking_reference: str | None = None


def _pick_list_response(pick_list: PickList) -> dict:
    return {
        "id": pick_list.id,
        "number": pick_list.number,
        "source_type": pick_list.source_type,
        "source_id": pick_list.source_id,
        "partner_id": pick_list.partner_id,
        "location_id": pick_list.location_id,
        "status": pick_list.status,
        "created_at": pick_list.created_at,
        "picked_at": pick_list.picked_at,
        "cancelled_at": pick_list.cancelled_at,
    }


def _pick_line_response(line: PickListLine) -> dict:
    return {
        "id": line.id,
        "pick_list_id": line.pick_list_id,
        "product_id": line.product_id,
        "quantity_requested": line.quantity_requested,
        "quantity_picked": line.quantity_picked,
        "picked_by": line.picked_by,
        "picked_at": line.picked_at,
    }


def _shipment_response(shipment: Shipment) -> dict:
    return {
        "id": shipment.id,
        "number": shipment.number,
        "pick_list_id": shipment.pick_list_id,
        "status": shipment.status,
        "package_count": shipment.package_count,
        "total_weight_kg": shipment.total_weight_kg,
        "carrier": shipment.carrier,
        "tracking_reference": shipment.tracking_reference,
        "packed_by": shipment.packed_by,
        "packed_at": shipment.packed_at,
        "shipped_by": shipment.shipped_by,
        "shipped_at": shipment.shipped_at,
    }


def _fulfillment_err_status(code: str) -> int:
    if code == "NOT_FOUND":
        return status.HTTP_404_NOT_FOUND
    if code in ("INVALID_TRANSITION", "INVALID_STATE", "LINES_UNPICKED", "NOTHING_PICKED", "ALREADY_PACKED", "INSUFFICIENT_STOCK"):
        return status.HTTP_409_CONFLICT
    return status.HTTP_400_BAD_REQUEST


def _raise_fulfillment(connection, result: Err) -> None:
    connection.rollback()
    raise HTTPException(_fulfillment_err_status(result.code), err_detail(result))


@router.get("/pick-lists")
def list_pick_lists(
    status_filter: str | None = Query(default=None, alias="status"),
    tenant: TenantContext = Depends(require_permission("warehouse.view_fulfillment")),
) -> list[dict]:
    with get_connection() as connection:
        pick_lists = FulfillmentService(connection).list_pick_lists(tenant_id=tenant.tenant_id, status=status_filter)
    return [_pick_list_response(pick_list) for pick_list in pick_lists]


@router.get("/pick-lists/{pick_list_id}")
def get_pick_list(
    pick_list_id: str, tenant: TenantContext = Depends(require_permission("warehouse.view_fulfillment"))
) -> dict:
    with get_connection() as connection:
        service = FulfillmentService(connection)
        result = service.get_pick_list(tenant_id=tenant.tenant_id, pick_list_id=pick_list_id)
        if isinstance(result, Err):
            raise HTTPException(_fulfillment_err_status(result.code), err_detail(result))
        lines = service.list_pick_lines(tenant_id=tenant.tenant_id, pick_list_id=pick_list_id)
        shipment = service.get_shipment_for_pick_list(tenant_id=tenant.tenant_id, pick_list_id=pick_list_id)
    return {
        **_pick_list_response(result.value),
        "lines": [_pick_line_response(line) for line in lines],
        "shipment": _shipment_response(shipment) if shipment else None,
    }


@router.post("/pick-lists/{pick_list_id}/lines/{line_id}/pick")
def submit_pick(
    pick_list_id: str,
    line_id: str,
    body: SubmitPickRequest,
    tenant: TenantContext = Depends(require_permission("warehouse.manage_fulfillment")),
) -> dict:
    with get_connection() as connection:
        result = FulfillmentService(connection).submit_pick(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            pick_list_id=pick_list_id,
            line_id=line_id,
            quantity_picked=body.quantity_picked,
        )
        if isinstance(result, Err):
            _raise_fulfillment(connection, result)
        connection.commit()
    return _pick_line_response(result.value)


@router.post("/pick-lists/{pick_list_id}/complete")
def complete_picking(
    pick_list_id: str, tenant: TenantContext = Depends(require_permission("warehouse.manage_fulfillment"))
) -> dict:
    with get_connection() as connection:
        result = FulfillmentService(connection).complete_picking(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, pick_list_id=pick_list_id
        )
        if isinstance(result, Err):
            _raise_fulfillment(connection, result)
        connection.commit()
    return _pick_list_response(result.value)


@router.post("/pick-lists/{pick_list_id}/cancel")
def cancel_pick_list(
    pick_list_id: str,
    body: CorrelatedRequest,
    tenant: TenantContext = Depends(require_permission("warehouse.manage_fulfillment")),
) -> dict:
    with get_connection() as connection:
        result = FulfillmentService(connection).cancel_pick_list(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, pick_list_id=pick_list_id, correlation_id=body.correlation_id
        )
        if isinstance(result, Err):
            _raise_fulfillment(connection, result)
        connection.commit()
    return _pick_list_response(result.value)


@router.post("/pick-lists/{pick_list_id}/pack", status_code=status.HTTP_201_CREATED)
def pack_pick_list(
    pick_list_id: str,
    body: PackPickListRequest,
    tenant: TenantContext = Depends(require_permission("warehouse.manage_fulfillment")),
) -> dict:
    with get_connection() as connection:
        result = FulfillmentService(connection).pack(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            pick_list_id=pick_list_id,
            package_count=body.package_count,
            total_weight_kg=body.total_weight_kg,
            carrier=body.carrier,
            tracking_reference=body.tracking_reference,
        )
        if isinstance(result, Err):
            _raise_fulfillment(connection, result)
        connection.commit()
    return _shipment_response(result.value)


@router.get("/shipments")
def list_shipments(
    status_filter: str | None = Query(default=None, alias="status"),
    tenant: TenantContext = Depends(require_permission("warehouse.view_fulfillment")),
) -> list[dict]:
    with get_connection() as connection:
        shipments = FulfillmentService(connection).list_shipments(tenant_id=tenant.tenant_id, status=status_filter)
    return [_shipment_response(shipment) for shipment in shipments]


@router.patch("/shipments/{shipment_id}")
def update_shipment(
    shipment_id: str,
    body: UpdateShipmentRequest,
    tenant: TenantContext = Depends(require_permission("warehouse.admin_shipments")),
) -> dict:
    with get_connection() as connection:
        result = FulfillmentService(connection).admin_update_shipment(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            shipment_id=shipment_id,
            package_count=body.package_count,
            total_weight_kg=body.total_weight_kg,
            carrier=body.carrier,
            tracking_reference=body.tracking_reference,
        )
        if isinstance(result, Err):
            _raise_fulfillment(connection, result)
        connection.commit()
    return _shipment_response(result.value)


@router.post("/shipments/{shipment_id}/ship")
def ship_shipment(
    shipment_id: str,
    body: CorrelatedRequest,
    tenant: TenantContext = Depends(require_permission("warehouse.manage_fulfillment")),
) -> dict:
    with get_connection() as connection:
        result = FulfillmentService(connection).ship(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, shipment_id=shipment_id, correlation_id=body.correlation_id
        )
        if isinstance(result, Err):
            _raise_fulfillment(connection, result)
        connection.commit()
    return _shipment_response(result.value)


# --- Barcodes & scan resolution -------------------------------------------------------------


class CreateBarcodeRequest(BaseModel):
    product_id: str
    barcode: str
    barcode_type: Literal["gtin", "internal"]
    units_per_scan: float = 1
    label: str | None = None


class UpdateBarcodeRequest(BaseModel):
    barcode: str | None = None
    barcode_type: Literal["gtin", "internal"] | None = None
    units_per_scan: float | None = None
    label: str | None = None


def _barcode_response(barcode: ProductBarcode) -> dict:
    return {
        "id": barcode.id,
        "product_id": barcode.product_id,
        "barcode": barcode.barcode,
        "barcode_type": barcode.barcode_type,
        "units_per_scan": barcode.units_per_scan,
        "label": barcode.label,
        "created_by": barcode.created_by,
        "created_at": barcode.created_at,
    }


def _barcode_err_status(code: str) -> int:
    if code == "NOT_FOUND":
        return status.HTTP_404_NOT_FOUND
    if code == "DUPLICATE_BARCODE":
        return status.HTTP_409_CONFLICT
    return status.HTTP_400_BAD_REQUEST


@router.get("/scan/resolve")
def resolve_scan(code: str, tenant: TenantContext = Depends(require_permission("warehouse.view_moves"))) -> dict:
    with get_connection() as connection:
        return BarcodeService(connection).resolve(tenant_id=tenant.tenant_id, code=code)


@router.get("/product-barcodes")
def list_product_barcodes(
    product_id: str | None = None, tenant: TenantContext = Depends(require_permission("warehouse.view_moves"))
) -> list[dict]:
    with get_connection() as connection:
        barcodes = BarcodeService(connection).list_barcodes(tenant_id=tenant.tenant_id, product_id=product_id)
    return [_barcode_response(barcode) for barcode in barcodes]


@router.post("/product-barcodes", status_code=status.HTTP_201_CREATED)
def create_product_barcode(
    body: CreateBarcodeRequest, tenant: TenantContext = Depends(require_permission("warehouse.manage_barcodes"))
) -> dict:
    with get_connection() as connection:
        result = BarcodeService(connection).create_barcode(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            product_id=body.product_id,
            barcode=body.barcode,
            barcode_type=body.barcode_type,
            units_per_scan=body.units_per_scan,
            label=body.label,
        )
        if isinstance(result, Err):
            connection.rollback()
            raise HTTPException(_barcode_err_status(result.code), err_detail(result))
        connection.commit()
    return _barcode_response(result.value)


@router.patch("/product-barcodes/{barcode_id}")
def update_product_barcode(
    barcode_id: str,
    body: UpdateBarcodeRequest,
    tenant: TenantContext = Depends(require_permission("warehouse.admin_barcodes")),
) -> dict:
    with get_connection() as connection:
        result = BarcodeService(connection).update_barcode(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            barcode_id=barcode_id,
            barcode=body.barcode,
            barcode_type=body.barcode_type,
            units_per_scan=body.units_per_scan,
            label=body.label,
        )
        if isinstance(result, Err):
            connection.rollback()
            raise HTTPException(_barcode_err_status(result.code), err_detail(result))
        connection.commit()
    return _barcode_response(result.value)


@router.delete("/product-barcodes/{barcode_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def delete_product_barcode(
    barcode_id: str, tenant: TenantContext = Depends(require_permission("warehouse.manage_barcodes"))
) -> None:
    with get_connection() as connection:
        result = BarcodeService(connection).delete_barcode(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, barcode_id=barcode_id)
        if isinstance(result, Err):
            connection.rollback()
            raise HTTPException(_barcode_err_status(result.code), err_detail(result))
        connection.commit()


# --- Reservations (ledger, TTL) -------------------------------------------------------------


class UpdateReservationRequest(BaseModel):
    expires_at: datetime.datetime | None = None
    # Explicit, because "expires_at omitted" already means "leave unchanged".
    clear_expiry: bool = False


def _reservation_response(reservation: StockReservation) -> dict:
    return {
        "id": reservation.id,
        "product_id": reservation.product_id,
        "location_id": reservation.location_id,
        "reference": reservation.reference,
        "quantity": reservation.quantity,
        "quantity_open": reservation.quantity_open,
        "status": reservation.status,
        "expires_at": reservation.expires_at,
        "created_by": reservation.created_by,
        "created_at": reservation.created_at,
        "closed_at": reservation.closed_at,
    }


def _reservation_err_status(code: str) -> int:
    if code == "NOT_FOUND":
        return status.HTTP_404_NOT_FOUND
    if code in ("INVALID_STATE", "INSUFFICIENT_STOCK"):
        return status.HTTP_409_CONFLICT
    return status.HTTP_400_BAD_REQUEST


@router.get("/reservations")
def list_reservations(
    status_filter: str | None = Query(default=None, alias="status"),
    tenant: TenantContext = Depends(require_permission("warehouse.view_moves")),
) -> list[dict]:
    with get_connection() as connection:
        reservations = ReservationService(connection).list_reservations(tenant_id=tenant.tenant_id, status=status_filter)
    return [_reservation_response(reservation) for reservation in reservations]


@router.post("/reservations/{reservation_id}/release")
def release_reservation(
    reservation_id: str, tenant: TenantContext = Depends(require_permission("warehouse.manage_stock"))
) -> dict:
    with get_connection() as connection:
        result = ReservationService(connection).release_reservation(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, reservation_id=reservation_id
        )
        if isinstance(result, Err):
            connection.rollback()
            raise HTTPException(_reservation_err_status(result.code), err_detail(result))
        connection.commit()
    return _reservation_response(result.value)


@router.patch("/reservations/{reservation_id}")
def update_reservation(
    reservation_id: str,
    body: UpdateReservationRequest,
    tenant: TenantContext = Depends(require_permission("warehouse.admin_reservations")),
) -> dict:
    with get_connection() as connection:
        result = ReservationService(connection).update_reservation(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            reservation_id=reservation_id,
            expires_at=body.expires_at,
            clear_expiry=body.clear_expiry,
        )
        if isinstance(result, Err):
            connection.rollback()
            raise HTTPException(_reservation_err_status(result.code), err_detail(result))
        connection.commit()
    return _reservation_response(result.value)


# --- FIFO valuation -------------------------------------------------------------------------


def _layer_response(layer: CostLayer) -> dict:
    return {
        "id": layer.id,
        "product_id": layer.product_id,
        "reference": layer.reference,
        "move_type": layer.move_type,
        "quantity_in": layer.quantity_in,
        "quantity_remaining": layer.quantity_remaining,
        "unit_cost": layer.unit_cost,
        "received_at": layer.received_at,
    }


@router.get("/valuation")
def get_valuation(tenant: TenantContext = Depends(require_permission("warehouse.view_valuation"))) -> list[dict]:
    with get_connection() as connection:
        valuations = ValuationService(connection).get_valuation(tenant_id=tenant.tenant_id)
    return [
        {
            "product_id": valuation.product_id,
            "quantity": valuation.quantity,
            "value": valuation.value,
            "unvalued_quantity": valuation.unvalued_quantity,
            "average_unit_cost": valuation.average_unit_cost,
            "currency": "XOF",
        }
        for valuation in valuations
    ]


@router.get("/valuation/cost-of")
def get_cost_of_reference(
    reference: str, tenant: TenantContext = Depends(require_permission("warehouse.view_valuation"))
) -> dict:
    with get_connection() as connection:
        return ValuationService(connection).cost_of_reference(tenant_id=tenant.tenant_id, reference=reference)


@router.get("/valuation/{product_id}/layers")
def list_cost_layers(
    product_id: str,
    include_closed: bool = False,
    tenant: TenantContext = Depends(require_permission("warehouse.view_valuation")),
) -> list[dict]:
    with get_connection() as connection:
        layers = ValuationService(connection).list_layers(
            tenant_id=tenant.tenant_id, product_id=product_id, open_only=not include_closed
        )
    return [_layer_response(layer) for layer in layers]


# --- Replenishment (reorder rules & proposals) ----------------------------------------------


class CreateReorderRuleRequest(BaseModel):
    product_id: str
    reorder_point: float
    order_up_to: float
    site_id: str | None = None
    min_order_quantity: float = 0
    preferred_supplier_id: str | None = None


class UpdateReorderRuleRequest(BaseModel):
    reorder_point: float | None = None
    order_up_to: float | None = None
    min_order_quantity: float | None = None
    preferred_supplier_id: str | None = None
    is_active: bool | None = None


class ApproveProposalRequest(BaseModel):
    correlation_id: str
    quantity: float | None = None
    supplier_id: str | None = None


def _reorder_rule_response(rule: ReorderRule) -> dict:
    return {
        "id": rule.id,
        "product_id": rule.product_id,
        "site_id": rule.site_id,
        "reorder_point": rule.reorder_point,
        "order_up_to": rule.order_up_to,
        "min_order_quantity": rule.min_order_quantity,
        "preferred_supplier_id": rule.preferred_supplier_id,
        "is_active": rule.is_active,
        "created_by": rule.created_by,
        "created_at": rule.created_at,
    }


def _proposal_response(proposal: ReplenishmentProposal) -> dict:
    return {
        "id": proposal.id,
        "rule_id": proposal.rule_id,
        "product_id": proposal.product_id,
        "site_id": proposal.site_id,
        "available_at_proposal": proposal.available_at_proposal,
        "quantity": proposal.quantity,
        "supplier_id": proposal.supplier_id,
        "status": proposal.status,
        "created_at": proposal.created_at,
        "decided_by": proposal.decided_by,
        "decided_at": proposal.decided_at,
        "closed_at": proposal.closed_at,
    }


def _replenishment_err_status(code: str) -> int:
    if code == "NOT_FOUND":
        return status.HTTP_404_NOT_FOUND
    if code in ("INVALID_STATE", "DUPLICATE_RULE", "RULE_HAS_HISTORY"):
        return status.HTTP_409_CONFLICT
    return status.HTTP_400_BAD_REQUEST


def _raise_replenishment(connection, result: Err) -> None:
    connection.rollback()
    raise HTTPException(_replenishment_err_status(result.code), err_detail(result))


@router.get("/reorder-rules")
def list_reorder_rules(tenant: TenantContext = Depends(require_permission("warehouse.view_replenishment"))) -> list[dict]:
    with get_connection() as connection:
        rules = ReplenishmentService(connection).list_rules(tenant_id=tenant.tenant_id)
    return [_reorder_rule_response(rule) for rule in rules]


@router.post("/reorder-rules", status_code=status.HTTP_201_CREATED)
def create_reorder_rule(
    body: CreateReorderRuleRequest, tenant: TenantContext = Depends(require_permission("warehouse.manage_replenishment"))
) -> dict:
    with get_connection() as connection:
        result = ReplenishmentService(connection).create_rule(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            product_id=body.product_id,
            reorder_point=body.reorder_point,
            order_up_to=body.order_up_to,
            site_id=body.site_id,
            min_order_quantity=body.min_order_quantity,
            preferred_supplier_id=body.preferred_supplier_id,
        )
        if isinstance(result, Err):
            _raise_replenishment(connection, result)
        connection.commit()
    return _reorder_rule_response(result.value)


@router.patch("/reorder-rules/{rule_id}")
def update_reorder_rule(
    rule_id: str,
    body: UpdateReorderRuleRequest,
    tenant: TenantContext = Depends(require_permission("warehouse.admin_reorder_rules")),
) -> dict:
    with get_connection() as connection:
        result = ReplenishmentService(connection).update_rule(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            rule_id=rule_id,
            reorder_point=body.reorder_point,
            order_up_to=body.order_up_to,
            min_order_quantity=body.min_order_quantity,
            preferred_supplier_id=body.preferred_supplier_id,
            is_active=body.is_active,
        )
        if isinstance(result, Err):
            _raise_replenishment(connection, result)
        connection.commit()
    return _reorder_rule_response(result.value)


@router.delete("/reorder-rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def delete_reorder_rule(
    rule_id: str, tenant: TenantContext = Depends(require_permission("warehouse.manage_replenishment"))
) -> None:
    with get_connection() as connection:
        result = ReplenishmentService(connection).delete_rule(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, rule_id=rule_id)
        if isinstance(result, Err):
            _raise_replenishment(connection, result)
        connection.commit()


@router.get("/replenishment/proposals")
def list_replenishment_proposals(
    status_filter: str | None = Query(default=None, alias="status"),
    tenant: TenantContext = Depends(require_permission("warehouse.view_replenishment")),
) -> list[dict]:
    with get_connection() as connection:
        proposals = ReplenishmentService(connection).list_proposals(tenant_id=tenant.tenant_id, status=status_filter)
    return [_proposal_response(proposal) for proposal in proposals]


@router.post("/replenishment/evaluate")
def evaluate_replenishment(tenant: TenantContext = Depends(require_permission("warehouse.manage_replenishment"))) -> dict:
    with get_connection() as connection:
        outcome = ReplenishmentService(connection).evaluate(tenant_id=tenant.tenant_id, actor_id=tenant.user_id)
        connection.commit()
    return {
        "created": [_proposal_response(p) for p in outcome["created"]],
        "fulfilled": [_proposal_response(p) for p in outcome["fulfilled"]],
    }


@router.post("/replenishment/proposals/{proposal_id}/approve")
def approve_replenishment_proposal(
    proposal_id: str,
    body: ApproveProposalRequest,
    tenant: TenantContext = Depends(require_permission("warehouse.manage_replenishment")),
) -> dict:
    with get_connection() as connection:
        result = ReplenishmentService(connection).approve_proposal(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            proposal_id=proposal_id,
            correlation_id=body.correlation_id,
            quantity=body.quantity,
            supplier_id=body.supplier_id,
        )
        if isinstance(result, Err):
            _raise_replenishment(connection, result)
        connection.commit()
    return _proposal_response(result.value)


@router.post("/replenishment/proposals/{proposal_id}/dismiss")
def dismiss_replenishment_proposal(
    proposal_id: str, tenant: TenantContext = Depends(require_permission("warehouse.manage_replenishment"))
) -> dict:
    with get_connection() as connection:
        result = ReplenishmentService(connection).dismiss_proposal(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, proposal_id=proposal_id
        )
        if isinstance(result, Err):
            _raise_replenishment(connection, result)
        connection.commit()
    return _proposal_response(result.value)
