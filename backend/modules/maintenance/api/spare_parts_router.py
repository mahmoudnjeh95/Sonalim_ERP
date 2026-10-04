from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from core.db import get_connection
from core.domain.result import Err, err_detail
from core.tenancy import TenantContext, require_permission
from modules.maintenance.api.spare_parts_service import SparePartsService

# No prefix: included into modules/maintenance/api/router.py, which carries /maintenance.
router = APIRouter(tags=["maintenance.spare_parts"])


class UpdateSettingsRequest(BaseModel):
    # null clears the location.
    spare_parts_location_id: str | None = None


@router.get("/settings")
def get_settings(tenant: TenantContext = Depends(require_permission("maintenance.view_jobs"))) -> dict:
    with get_connection() as connection:
        return SparePartsService(connection).settings(tenant.tenant_id)


@router.put("/settings")
def update_settings(
    body: UpdateSettingsRequest, tenant: TenantContext = Depends(require_permission("maintenance.plan_jobs"))
) -> dict:
    with get_connection() as connection:
        result = SparePartsService(connection).set_location(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, location_id=body.spare_parts_location_id
        )
        if isinstance(result, Err):
            connection.rollback()
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, err_detail(result))
        connection.commit()
    return result.value


@router.get("/settings/locations")
def list_location_options(tenant: TenantContext = Depends(require_permission("maintenance.plan_jobs"))) -> list[dict]:
    """The warehouse locations a planner may pick the spare-parts location from."""
    with get_connection() as connection:
        return SparePartsService(connection).location_options(tenant.tenant_id)


@router.get("/spare-parts")
def spare_parts_catalog(tenant: TenantContext = Depends(require_permission("maintenance.manage_checkpoints"))) -> dict:
    """The products the map editor offers for a checkpoint, with their stock in the spare-parts location."""
    with get_connection() as connection:
        return SparePartsService(connection).catalog(tenant.tenant_id)


@router.get("/part-products")
def part_request_products(tenant: TenantContext = Depends(require_permission("maintenance.view_jobs"))) -> list[dict]:
    """The products a parts request may name, spare parts first -- readable without core.view_products."""
    with get_connection() as connection:
        return SparePartsService(connection).request_products(tenant.tenant_id)
