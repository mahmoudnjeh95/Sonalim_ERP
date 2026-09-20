from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from core.db import get_connection
from core.domain.result import Err
from core.tenancy import TenantContext, require_permission
from modules.maintenance.api.equipment_service import UNSET, EquipmentService
from modules.maintenance.domain.equipment import Equipment

router = APIRouter(prefix="/maintenance", tags=["maintenance"])


class CreateEquipmentRequest(BaseModel):
    work_center_id: str
    code: str
    name: str
    production_stage: str | None = None


class UpdateEquipmentRequest(BaseModel):
    work_center_id: str | None = None
    code: str | None = None
    name: str | None = None
    # Sent as null it clears the stage; left out it is left as it is.
    production_stage: str | None = None


class TransitionEquipmentRequest(BaseModel):
    status: str


def _serialize_equipment(equipment: Equipment) -> dict:
    return {
        "id": equipment.id,
        "work_center_id": equipment.work_center_id,
        "code": equipment.code,
        "name": equipment.name,
        "status": equipment.status,
        "production_stage": equipment.production_stage,
    }


@router.post("/equipment", status_code=status.HTTP_201_CREATED)
def create_equipment(
    body: CreateEquipmentRequest,
    tenant: TenantContext = Depends(require_permission("maintenance.manage_equipment")),
) -> dict:
    with get_connection() as connection:
        service = EquipmentService(connection)
        result = service.create_equipment(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            work_center_id=body.work_center_id,
            code=body.code,
            name=body.name,
            production_stage=body.production_stage,
        )
        if isinstance(result, Err):
            connection.rollback()
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, {"code": result.code, "message": result.message})
        connection.commit()
    return _serialize_equipment(result.value)


@router.get("/equipment")
def list_equipment(
    work_center_id: str | None = None,
    tenant: TenantContext = Depends(require_permission("maintenance.view_equipment")),
) -> list[dict]:
    with get_connection() as connection:
        service = EquipmentService(connection)
        equipment = service.list_equipment(tenant_id=tenant.tenant_id, work_center_id=work_center_id)
    return [_serialize_equipment(e) for e in equipment]


@router.patch("/equipment/{equipment_id}")
def update_equipment(
    equipment_id: str,
    body: UpdateEquipmentRequest,
    tenant: TenantContext = Depends(require_permission("maintenance.admin_equipment")),
) -> dict:
    with get_connection() as connection:
        service = EquipmentService(connection)
        result = service.update_equipment(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            equipment_id=equipment_id,
            work_center_id=body.work_center_id,
            code=body.code,
            name=body.name,
            production_stage=body.production_stage if "production_stage" in body.model_fields_set else UNSET,
        )
        if isinstance(result, Err):
            connection.rollback()
            code = status.HTTP_404_NOT_FOUND if result.code == "NOT_FOUND" else status.HTTP_400_BAD_REQUEST
            raise HTTPException(code, {"code": result.code, "message": result.message})
        connection.commit()
    return _serialize_equipment(result.value)


@router.post("/equipment/{equipment_id}/status")
def transition_equipment_status(
    equipment_id: str,
    body: TransitionEquipmentRequest,
    tenant: TenantContext = Depends(require_permission("maintenance.manage_equipment")),
) -> dict:
    with get_connection() as connection:
        service = EquipmentService(connection)
        result = service.transition_status(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, equipment_id=equipment_id, new_status=body.status
        )
        if isinstance(result, Err):
            connection.rollback()
            code = status.HTTP_404_NOT_FOUND if result.code == "NOT_FOUND" else status.HTTP_409_CONFLICT
            raise HTTPException(code, {"code": result.code, "message": result.message})
        connection.commit()
    return _serialize_equipment(result.value)
