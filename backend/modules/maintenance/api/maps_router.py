from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status
from pydantic import BaseModel

from core.db import get_connection
from core.domain.result import Err, err_detail
from core.tenancy import TenantContext, require_permission
from modules.maintenance.api.map_service import MapService
from modules.maintenance.domain.uploads import read_capped

# No prefix: included into modules/maintenance/api/router.py, which carries /maintenance.
router = APIRouter(tags=["maintenance.maps"])

_STATUS_BY_CODE = {
    "NOT_FOUND": status.HTTP_404_NOT_FOUND,
    "VIEW_IN_USE": status.HTTP_409_CONFLICT,
    "INVALID_IMAGE": status.HTTP_422_UNPROCESSABLE_ENTITY,
    "INVALID_POSITION": status.HTTP_422_UNPROCESSABLE_ENTITY,
    "INVALID_ACTION": status.HTTP_422_UNPROCESSABLE_ENTITY,
}


class CheckpointPart(BaseModel):
    product_id: str
    quantity: float


class AddCheckpointRequest(BaseModel):
    x_pct: float
    y_pct: float
    label: str
    action: str
    instructions: str | None = None
    measure_unit: str | None = None
    requires_photo: bool = False
    parts: list[CheckpointPart] = []


class UpdateCheckpointRequest(BaseModel):
    x_pct: float | None = None
    y_pct: float | None = None
    label: str | None = None
    action: str | None = None
    instructions: str | None = None
    measure_unit: str | None = None
    requires_photo: bool | None = None
    sort_order: int | None = None
    # Replaces the point's whole list ([] clears it); left out it is left as it is.
    parts: list[CheckpointPart] | None = None


def _result(connection, result):
    if isinstance(result, Err):
        connection.rollback()
        raise HTTPException(_STATUS_BY_CODE.get(result.code, status.HTTP_422_UNPROCESSABLE_ENTITY), err_detail(result))
    connection.commit()
    return result.value


@router.get("/equipment/{equipment_id}/views")
def list_views(
    equipment_id: str,
    include_archived: bool = False,
    tenant: TenantContext = Depends(require_permission("maintenance.view_equipment")),
) -> list[dict]:
    with get_connection() as connection:
        return MapService(connection).list_views(
            tenant_id=tenant.tenant_id, equipment_id=equipment_id, include_archived=include_archived
        )


@router.post("/equipment/{equipment_id}/views", status_code=status.HTTP_201_CREATED)
def create_view(
    equipment_id: str,
    label: str = Form(...),
    image: UploadFile = File(...),
    tenant: TenantContext = Depends(require_permission("maintenance.manage_checkpoints")),
) -> dict:
    # A plain `def` (thread pool) like every other handler: the database work must not hold the event loop.
    data = read_capped(image.file)
    with get_connection() as connection:
        return _result(
            connection,
            MapService(connection).create_view(
                tenant_id=tenant.tenant_id,
                actor_id=tenant.user_id,
                equipment_id=equipment_id,
                label=label,
                image=data,
                mime=image.content_type or "",
            ),
        )


@router.patch("/views/{view_id}")
def update_view(
    view_id: str,
    label: str | None = Form(default=None),
    sort_order: int | None = Form(default=None),
    image: UploadFile | None = File(default=None),
    tenant: TenantContext = Depends(require_permission("maintenance.manage_checkpoints")),
) -> dict:
    # An empty multipart part (a form that always sends its file field) is refused by
    # FastAPI's own validation before this runs, with a 422. Typing the parameter
    # `UploadFile | str` would let it through, but FastAPI then reads the stream to decide
    # which side of the union it is and a real upload arrives empty -- so the frontend
    # leaves the field out instead (see updateEquipmentView in features/maintenance/api.ts).
    data = read_capped(image.file) if image is not None else None
    mime = image.content_type if image is not None else None
    with get_connection() as connection:
        return _result(
            connection,
            MapService(connection).update_view(
                tenant_id=tenant.tenant_id,
                actor_id=tenant.user_id,
                view_id=view_id,
                label=label,
                sort_order=sort_order,
                image=data,
                mime=mime,
            ),
        )


@router.delete("/views/{view_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def delete_view(
    view_id: str, tenant: TenantContext = Depends(require_permission("maintenance.manage_checkpoints"))
) -> None:
    with get_connection() as connection:
        _result(connection, MapService(connection).delete_view(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, view_id=view_id))


@router.get("/views/{view_id}/image")
def view_image(
    view_id: str, tenant: TenantContext = Depends(require_permission("maintenance.view_equipment"))
) -> Response:
    with get_connection() as connection:
        found = MapService(connection).get_image(tenant_id=tenant.tenant_id, view_id=view_id)
    if found is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            {"code": "NOT_FOUND", "message": "image not found", "message_fr": "image introuvable"},
        )
    image, mime = found
    return Response(content=image, media_type=mime, headers={"Cache-Control": "private, max-age=86400"})


@router.post("/views/{view_id}/checkpoints", status_code=status.HTTP_201_CREATED)
def add_checkpoint(
    view_id: str,
    body: AddCheckpointRequest,
    tenant: TenantContext = Depends(require_permission("maintenance.manage_checkpoints")),
) -> dict:
    with get_connection() as connection:
        return _result(
            connection,
            MapService(connection).add_checkpoint(
                tenant_id=tenant.tenant_id,
                actor_id=tenant.user_id,
                view_id=view_id,
                x_pct=body.x_pct,
                y_pct=body.y_pct,
                label=body.label,
                action=body.action,
                instructions=body.instructions,
                measure_unit=body.measure_unit,
                requires_photo=body.requires_photo,
                parts=[part.model_dump() for part in body.parts],
            ),
        )


@router.patch("/checkpoints/{checkpoint_id}")
def update_checkpoint(
    checkpoint_id: str,
    body: UpdateCheckpointRequest,
    tenant: TenantContext = Depends(require_permission("maintenance.manage_checkpoints")),
) -> dict:
    fields_set = body.model_fields_set
    with get_connection() as connection:
        return _result(
            connection,
            MapService(connection).update_checkpoint(
                tenant_id=tenant.tenant_id,
                actor_id=tenant.user_id,
                checkpoint_id=checkpoint_id,
                x_pct=body.x_pct,
                y_pct=body.y_pct,
                label=body.label,
                action=body.action,
                instructions=body.instructions,
                instructions_set="instructions" in fields_set,
                measure_unit=body.measure_unit,
                measure_unit_set="measure_unit" in fields_set,
                requires_photo=body.requires_photo,
                sort_order=body.sort_order,
                parts=[part.model_dump() for part in body.parts] if body.parts is not None else None,
            ),
        )


@router.post("/checkpoints/{checkpoint_id}/archive")
def archive_checkpoint(
    checkpoint_id: str, tenant: TenantContext = Depends(require_permission("maintenance.manage_checkpoints"))
) -> dict:
    with get_connection() as connection:
        return _result(
            connection,
            MapService(connection).archive_checkpoint(
                tenant_id=tenant.tenant_id, actor_id=tenant.user_id, checkpoint_id=checkpoint_id
            ),
        )
