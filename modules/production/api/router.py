from __future__ import annotations

import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from core.db import get_connection
from core.domain.result import Err
from core.tenancy import TenantContext, require_permission
from modules.production.api.machine_service import MachineService
from modules.production.api.packaging_bom_service import PackagingBomService
from modules.production.api.daily_consumption_service import DailyConsumptionService, ResourceTypeService
from modules.production.api.product_classification_service import ProductClassificationService
from modules.production.api.work_order_consumption_service import WorkOrderConsumptionService
from modules.production.api.work_order_yield_service import WorkOrderYieldService
from modules.production.domain.daily_consumption import DailyConsumption, ResourceType, WorkOrderConsumption
from modules.production.domain.product_classification import ProductClassification
from modules.production.api.recipe_service import RecipeService
from modules.production.api.regrind_service import RegrindService, ScrapService
from modules.production.api.service import WorkOrderService
from modules.production.api.work_center_service import WorkCenterService
from modules.production.domain.entities import WorkOrder
from modules.production.domain.machine import Machine
from modules.production.domain.packaging_bom import PackagingBom, PackagingBomLine
from modules.production.domain.recipe import Recipe, RecipeLine
from modules.production.domain.regrind import ScrapRecord
from modules.production.domain.work_center import WorkCenter

router = APIRouter(prefix="/production", tags=["production"])


class PouredInputRequest(BaseModel):
    product_id: str
    quantity: float


class CreateWorkOrderRequest(BaseModel):
    product_id: str
    quantity: float
    work_center_id: str | None = None
    recipe_id: str | None = None
    packaging_bom_id: str | None = None
    poured_inputs: list[PouredInputRequest] = []
    poured_inputs_location_id: str | None = None


class UpdateWorkOrderRequest(BaseModel):
    quantity: float | None = None
    work_center_id: str | None = None
    recipe_id: str | None = None
    packaging_bom_id: str | None = None


class CreateWorkCenterRequest(BaseModel):
    code: str
    name: str
    hourly_rate: float = 0


class UpdateWorkCenterRequest(BaseModel):
    code: str | None = None
    name: str | None = None
    hourly_rate: float | None = None


class BlockWorkCenterRequest(BaseModel):
    reason: str


class CreateMachineRequest(BaseModel):
    work_center_id: str
    code: str
    name: str


class UpdateMachineRequest(BaseModel):
    work_center_id: str | None = None
    code: str | None = None
    name: str | None = None


class TransitionMachineRequest(BaseModel):
    status: str


class MaterialUsedRequest(BaseModel):
    product_id: str
    quantity: float


class ScrapEntryRequest(BaseModel):
    scrap_type: str
    product_id: str
    quantity: float


class CompleteWorkOrderRequest(BaseModel):
    correlation_id: str
    location_id: str
    actual_output_quantity: float | None = None
    materials_used: list[MaterialUsedRequest] = []
    materials_location_id: str | None = None
    scrap_entries: list[ScrapEntryRequest] = []


class SetProductClassificationRequest(BaseModel):
    product_id: str
    category: str
    is_regrind: bool = False
    packaging_format: str | None = None
    is_water: bool = False


class RecordWorkOrderConsumptionRequest(BaseModel):
    resource_type_id: str
    quantity: float
    note: str | None = None


class PackagingBomLineRequest(BaseModel):
    component_product_id: str
    quantity_per_unit: float


class CreatePackagingBomRequest(BaseModel):
    target_product_id: str
    lines: list[PackagingBomLineRequest]


class UpdatePackagingBomRequest(BaseModel):
    target_product_id: str | None = None
    lines: list[PackagingBomLineRequest] | None = None


class RecipeLineRequest(BaseModel):
    component_product_id: str
    default_percentage: float
    min_percentage: float
    max_percentage: float
    is_hard_limit: bool = False


class CreateRecipeRequest(BaseModel):
    target_product_id: str
    lines: list[RecipeLineRequest]
    target_moisture_percentage: float | None = None
    origin: str = "manual"
    ai_confidence: float | None = None


class CreateRecipeVersionRequest(BaseModel):
    previous_recipe_id: str
    lines: list[RecipeLineRequest]
    target_moisture_percentage: float | None = None
    origin: str = "manual"
    ai_confidence: float | None = None


class RecordScrapRequest(BaseModel):
    scrap_type: str
    product_id: str
    quantity: float
    work_order_id: str | None = None
    work_center_id: str | None = None
    source_note: str | None = None
    operation_step_id: str | None = None


class CreateRegrindBatchRequest(BaseModel):
    scrap_record_ids: list[str]
    output_product_id: str
    output_quantity: float
    work_center_id: str | None = None


class CreateResourceTypeRequest(BaseModel):
    code: str
    name: str
    unit: str


class UpdateResourceTypeRequest(BaseModel):
    code: str | None = None
    name: str | None = None
    unit: str | None = None


class RecordDailyConsumptionRequest(BaseModel):
    consumption_date: datetime.date
    resource_type_id: str
    quantity: float
    note: str | None = None


@router.post("/work-orders", status_code=status.HTTP_201_CREATED)
def create_work_order(
    body: CreateWorkOrderRequest,
    tenant: TenantContext = Depends(require_permission("production.manage_work_orders")),
) -> dict:
    with get_connection() as connection:
        service = WorkOrderService(connection)
        result = service.create_work_order(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            product_id=body.product_id,
            quantity=body.quantity,
            work_center_id=body.work_center_id,
            recipe_id=body.recipe_id,
            packaging_bom_id=body.packaging_bom_id,
            poured_inputs=[(i.product_id, i.quantity) for i in body.poured_inputs],
            poured_inputs_location_id=body.poured_inputs_location_id,
        )
        if isinstance(result, Err):
            connection.rollback()
            code = status.HTTP_409_CONFLICT if result.code in ("INSUFFICIENT_STOCK", "INVALID_QUANTITY") else status.HTTP_400_BAD_REQUEST
            raise HTTPException(code, {"code": result.code, "message": result.message})
        connection.commit()
    return _serialize_work_order(result.value)


@router.get("/work-orders")
def list_work_orders(
    status_filter: str | None = Query(default=None, alias="status"),
    tenant: TenantContext = Depends(require_permission("production.view_work_orders")),
) -> list[dict]:
    with get_connection() as connection:
        service = WorkOrderService(connection)
        orders = service.list_work_orders(tenant.tenant_id, status=status_filter)
    return [_serialize_work_order(o) for o in orders]


@router.get("/work-orders/yields")
def list_work_order_yields(
    tenant: TenantContext = Depends(require_permission("production.view_work_orders")),
) -> list[dict]:
    with get_connection() as connection:
        return WorkOrderYieldService(connection).list_work_order_yields(tenant.tenant_id)


@router.get("/work-orders/{work_order_id}/inputs")
def list_work_order_inputs(
    work_order_id: str, tenant: TenantContext = Depends(require_permission("production.view_work_orders"))
) -> list[dict]:
    with get_connection() as connection:
        return WorkOrderService(connection).list_work_order_inputs(tenant.tenant_id, work_order_id)


@router.get("/work-orders/{work_order_id}/yield")
def get_work_order_yield(
    work_order_id: str, tenant: TenantContext = Depends(require_permission("production.view_work_orders"))
) -> dict:
    with get_connection() as connection:
        result = WorkOrderYieldService(connection).get_work_order_yield(tenant_id=tenant.tenant_id, work_order_id=work_order_id)
    if result is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, {"code": "NOT_FOUND", "message": f"no computable yield for work order {work_order_id}"})
    return result


@router.post("/work-orders/{work_order_id}/consumption", status_code=status.HTTP_201_CREATED)
def record_work_order_consumption(
    work_order_id: str,
    body: RecordWorkOrderConsumptionRequest,
    tenant: TenantContext = Depends(require_permission("production.manage_resource_consumption")),
) -> dict:
    with get_connection() as connection:
        service = WorkOrderConsumptionService(connection)
        result = service.record_consumption(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            work_order_id=work_order_id,
            resource_type_id=body.resource_type_id,
            quantity=body.quantity,
            note=body.note,
        )
        if isinstance(result, Err):
            connection.rollback()
            code = status.HTTP_404_NOT_FOUND if result.code == "NOT_FOUND" else status.HTTP_400_BAD_REQUEST
            raise HTTPException(code, {"code": result.code, "message": result.message})
        connection.commit()
    return _serialize_work_order_consumption(result.value)


@router.get("/work-orders/{work_order_id}/consumption")
def list_work_order_consumption(
    work_order_id: str, tenant: TenantContext = Depends(require_permission("production.view_resource_consumption"))
) -> list[dict]:
    with get_connection() as connection:
        entries = WorkOrderConsumptionService(connection).list_consumption(tenant_id=tenant.tenant_id, work_order_id=work_order_id)
    return [_serialize_work_order_consumption(e) for e in entries]


@router.patch("/work-orders/{work_order_id}")
def update_work_order(
    work_order_id: str,
    body: UpdateWorkOrderRequest,
    tenant: TenantContext = Depends(require_permission("production.admin_work_orders")),
) -> dict:
    with get_connection() as connection:
        service = WorkOrderService(connection)
        result = service.admin_update_work_order(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            work_order_id=work_order_id,
            quantity=body.quantity,
            work_center_id=body.work_center_id,
            recipe_id=body.recipe_id,
            packaging_bom_id=body.packaging_bom_id,
        )
        if isinstance(result, Err):
            connection.rollback()
            code = status.HTTP_404_NOT_FOUND if result.code == "NOT_FOUND" else status.HTTP_400_BAD_REQUEST
            raise HTTPException(code, {"code": result.code, "message": result.message})
        connection.commit()
    return _serialize_work_order(result.value)


@router.post("/work-orders/{work_order_id}/start")
def start_work_order(
    work_order_id: str,
    tenant: TenantContext = Depends(require_permission("production.manage_work_orders")),
) -> dict:
    with get_connection() as connection:
        service = WorkOrderService(connection)
        result = service.start_work_order(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, work_order_id=work_order_id)
        if isinstance(result, Err):
            connection.rollback()
            code = status.HTTP_404_NOT_FOUND if result.code == "NOT_FOUND" else status.HTTP_409_CONFLICT
            raise HTTPException(code, {"code": result.code, "message": result.message})
        connection.commit()
    return _serialize_work_order(result.value)


@router.post("/work-orders/{work_order_id}/complete")
def complete_work_order(
    work_order_id: str,
    body: CompleteWorkOrderRequest,
    tenant: TenantContext = Depends(require_permission("production.manage_work_orders")),
) -> dict:
    with get_connection() as connection:
        service = WorkOrderService(connection)
        result = service.complete_work_order(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            work_order_id=work_order_id,
            correlation_id=body.correlation_id,
            location_id=body.location_id,
            actual_output_quantity=body.actual_output_quantity,
            materials_used=[(m.product_id, m.quantity) for m in body.materials_used],
            materials_location_id=body.materials_location_id,
            scrap_entries=[(e.scrap_type, e.product_id, e.quantity) for e in body.scrap_entries],
        )
        if isinstance(result, Err):
            connection.rollback()
            code = status.HTTP_404_NOT_FOUND if result.code == "NOT_FOUND" else status.HTTP_409_CONFLICT
            raise HTTPException(code, {"code": result.code, "message": result.message})
        connection.commit()
    return _serialize_work_order(result.value)


@router.post("/product-classifications", status_code=status.HTTP_201_CREATED)
def set_product_classification(
    body: SetProductClassificationRequest,
    tenant: TenantContext = Depends(require_permission("production.manage_product_classifications")),
) -> dict:
    with get_connection() as connection:
        service = ProductClassificationService(connection)
        result = service.set_classification(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            product_id=body.product_id,
            category=body.category,
            is_regrind=body.is_regrind,
            packaging_format=body.packaging_format,
            is_water=body.is_water,
        )
        if isinstance(result, Err):
            connection.rollback()
            raise HTTPException(status.HTTP_400_BAD_REQUEST, {"code": result.code, "message": result.message})
        connection.commit()
    return _serialize_classification(result.value)


@router.get("/product-classifications")
def list_product_classifications(
    category: str | None = None,
    tenant: TenantContext = Depends(require_permission("production.view_product_classifications")),
) -> list[dict]:
    with get_connection() as connection:
        service = ProductClassificationService(connection)
        classifications = service.list_classifications(tenant.tenant_id, category=category)
    return [_serialize_classification(c) for c in classifications]


@router.get("/product-classifications/{product_id}")
def get_product_classification(
    product_id: str,
    tenant: TenantContext = Depends(require_permission("production.view_product_classifications")),
) -> dict:
    with get_connection() as connection:
        service = ProductClassificationService(connection)
        classification = service.get_classification(tenant.tenant_id, product_id)
    if classification is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, {"code": "NOT_FOUND", "message": f"no classification for {product_id}"})
    return _serialize_classification(classification)


@router.post("/packaging-boms", status_code=status.HTTP_201_CREATED)
def create_packaging_bom(
    body: CreatePackagingBomRequest,
    tenant: TenantContext = Depends(require_permission("production.manage_packaging_boms")),
) -> dict:
    lines = tuple(
        PackagingBomLine(component_product_id=line.component_product_id, quantity_per_unit=line.quantity_per_unit)
        for line in body.lines
    )
    with get_connection() as connection:
        service = PackagingBomService(connection)
        result = service.create_bom(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, target_product_id=body.target_product_id, lines=lines
        )
        if isinstance(result, Err):
            connection.rollback()
            raise HTTPException(status.HTTP_400_BAD_REQUEST, {"code": result.code, "message": result.message})
        connection.commit()
    return _serialize_bom(result.value)


@router.get("/packaging-boms")
def list_packaging_boms(
    target_product_id: str | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    tenant: TenantContext = Depends(require_permission("production.view_packaging_boms")),
) -> list[dict]:
    with get_connection() as connection:
        service = PackagingBomService(connection)
        boms = service.list_boms(tenant.tenant_id, target_product_id=target_product_id, status=status_filter)
    return [_serialize_bom(bom) for bom in boms]


@router.get("/packaging-boms/{bom_id}")
def get_packaging_bom(
    bom_id: str,
    tenant: TenantContext = Depends(require_permission("production.view_packaging_boms")),
) -> dict:
    with get_connection() as connection:
        service = PackagingBomService(connection)
        bom = service.get_bom(tenant.tenant_id, bom_id)
    if bom is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, {"code": "NOT_FOUND", "message": f"packaging BOM {bom_id} not found"})
    return _serialize_bom(bom)


@router.patch("/packaging-boms/{bom_id}")
def update_packaging_bom(
    bom_id: str,
    body: UpdatePackagingBomRequest,
    tenant: TenantContext = Depends(require_permission("production.admin_packaging_boms")),
) -> dict:
    lines = (
        tuple(
            PackagingBomLine(component_product_id=line.component_product_id, quantity_per_unit=line.quantity_per_unit)
            for line in body.lines
        )
        if body.lines is not None
        else None
    )
    with get_connection() as connection:
        service = PackagingBomService(connection)
        result = service.admin_update_bom(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, bom_id=bom_id, target_product_id=body.target_product_id, lines=lines
        )
        if isinstance(result, Err):
            connection.rollback()
            code = status.HTTP_404_NOT_FOUND if result.code == "NOT_FOUND" else status.HTTP_400_BAD_REQUEST
            raise HTTPException(code, {"code": result.code, "message": result.message})
        connection.commit()
    return _serialize_bom(result.value)


@router.post("/packaging-boms/{bom_id}/activate")
def activate_packaging_bom(
    bom_id: str,
    tenant: TenantContext = Depends(require_permission("production.manage_packaging_boms")),
) -> dict:
    with get_connection() as connection:
        service = PackagingBomService(connection)
        result = service.activate_bom(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, bom_id=bom_id)
        if isinstance(result, Err):
            connection.rollback()
            code = status.HTTP_404_NOT_FOUND if result.code == "NOT_FOUND" else status.HTTP_409_CONFLICT
            raise HTTPException(code, {"code": result.code, "message": result.message})
        connection.commit()
    return _serialize_bom(result.value)


@router.post("/packaging-boms/{bom_id}/archive")
def archive_packaging_bom(
    bom_id: str,
    tenant: TenantContext = Depends(require_permission("production.manage_packaging_boms")),
) -> dict:
    with get_connection() as connection:
        service = PackagingBomService(connection)
        result = service.archive_bom(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, bom_id=bom_id)
        if isinstance(result, Err):
            connection.rollback()
            code = status.HTTP_404_NOT_FOUND if result.code == "NOT_FOUND" else status.HTTP_409_CONFLICT
            raise HTTPException(code, {"code": result.code, "message": result.message})
        connection.commit()
    return _serialize_bom(result.value)


def _serialize_work_order(order: WorkOrder) -> dict:
    return {
        "id": order.id,
        "reference": order.reference,
        "product_id": order.product_id,
        "quantity": order.quantity,
        "status": order.status,
        "work_center_id": order.work_center_id,
        "recipe_id": order.recipe_id,
        "packaging_bom_id": order.packaging_bom_id,
        "actual_output_quantity": order.actual_output_quantity,
    }


def _serialize_classification(classification: ProductClassification) -> dict:
    return {
        "product_id": classification.product_id,
        "category": classification.category,
        "is_regrind": classification.is_regrind,
        "packaging_format": classification.packaging_format,
        "is_water": classification.is_water,
    }


def _serialize_work_order_consumption(entry: WorkOrderConsumption) -> dict:
    return {
        "id": entry.id,
        "work_order_id": entry.work_order_id,
        "resource_type_id": entry.resource_type_id,
        "quantity": entry.quantity,
        "note": entry.note,
    }


def _serialize_bom(bom: PackagingBom) -> dict:
    return {
        "id": bom.id,
        "target_product_id": bom.target_product_id,
        "version": bom.version,
        "status": bom.status,
        "lines": [
            {"component_product_id": line.component_product_id, "quantity_per_unit": line.quantity_per_unit}
            for line in bom.lines
        ],
    }


def _serialize_work_center(work_center: WorkCenter) -> dict:
    return {
        "id": work_center.id,
        "code": work_center.code,
        "name": work_center.name,
        "hourly_rate": work_center.hourly_rate,
        "is_blocked": work_center.is_blocked,
        "blocked_reason": work_center.blocked_reason,
    }


def _serialize_machine(machine: Machine) -> dict:
    return {
        "id": machine.id,
        "work_center_id": machine.work_center_id,
        "code": machine.code,
        "name": machine.name,
        "status": machine.status,
    }


@router.post("/work-centers", status_code=status.HTTP_201_CREATED)
def create_work_center(
    body: CreateWorkCenterRequest,
    tenant: TenantContext = Depends(require_permission("production.manage_work_centers")),
) -> dict:
    with get_connection() as connection:
        service = WorkCenterService(connection)
        result = service.create_work_center(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, code=body.code, name=body.name, hourly_rate=body.hourly_rate
        )
        if isinstance(result, Err):
            connection.rollback()
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, {"code": result.code, "message": result.message})
        connection.commit()
    return _serialize_work_center(result.value)


@router.get("/work-centers")
def list_work_centers(
    tenant: TenantContext = Depends(require_permission("production.view_work_centers")),
) -> list[dict]:
    with get_connection() as connection:
        service = WorkCenterService(connection)
        work_centers = service.list_work_centers(tenant_id=tenant.tenant_id)
    return [_serialize_work_center(wc) for wc in work_centers]


@router.patch("/work-centers/{work_center_id}")
def update_work_center(
    work_center_id: str,
    body: UpdateWorkCenterRequest,
    tenant: TenantContext = Depends(require_permission("production.admin_work_centers")),
) -> dict:
    with get_connection() as connection:
        service = WorkCenterService(connection)
        result = service.update_work_center(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            work_center_id=work_center_id,
            code=body.code,
            name=body.name,
            hourly_rate=body.hourly_rate,
        )
        if isinstance(result, Err):
            connection.rollback()
            code = status.HTTP_404_NOT_FOUND if result.code == "NOT_FOUND" else status.HTTP_400_BAD_REQUEST
            raise HTTPException(code, {"code": result.code, "message": result.message})
        connection.commit()
    return _serialize_work_center(result.value)


@router.post("/work-centers/{work_center_id}/block")
def block_work_center(
    work_center_id: str,
    body: BlockWorkCenterRequest,
    tenant: TenantContext = Depends(require_permission("production.manage_work_centers")),
) -> dict:
    with get_connection() as connection:
        service = WorkCenterService(connection)
        result = service.block_work_center(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, work_center_id=work_center_id, reason=body.reason
        )
        if isinstance(result, Err):
            connection.rollback()
            code = status.HTTP_404_NOT_FOUND if result.code == "NOT_FOUND" else status.HTTP_409_CONFLICT
            raise HTTPException(code, {"code": result.code, "message": result.message})
        connection.commit()
    return _serialize_work_center(result.value)


@router.post("/work-centers/{work_center_id}/unblock")
def unblock_work_center(
    work_center_id: str,
    tenant: TenantContext = Depends(require_permission("production.manage_work_centers")),
) -> dict:
    with get_connection() as connection:
        service = WorkCenterService(connection)
        result = service.unblock_work_center(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, work_center_id=work_center_id)
        if isinstance(result, Err):
            connection.rollback()
            code = status.HTTP_404_NOT_FOUND if result.code == "NOT_FOUND" else status.HTTP_409_CONFLICT
            raise HTTPException(code, {"code": result.code, "message": result.message})
        connection.commit()
    return _serialize_work_center(result.value)


@router.post("/machines", status_code=status.HTTP_201_CREATED)
def create_machine(
    body: CreateMachineRequest,
    tenant: TenantContext = Depends(require_permission("production.manage_machines")),
) -> dict:
    with get_connection() as connection:
        service = MachineService(connection)
        result = service.create_machine(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            work_center_id=body.work_center_id,
            code=body.code,
            name=body.name,
        )
        if isinstance(result, Err):
            connection.rollback()
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, {"code": result.code, "message": result.message})
        connection.commit()
    return _serialize_machine(result.value)


@router.get("/machines")
def list_machines(
    work_center_id: str | None = None,
    tenant: TenantContext = Depends(require_permission("production.view_machines")),
) -> list[dict]:
    with get_connection() as connection:
        service = MachineService(connection)
        machines = service.list_machines(tenant_id=tenant.tenant_id, work_center_id=work_center_id)
    return [_serialize_machine(m) for m in machines]


@router.patch("/machines/{machine_id}")
def update_machine(
    machine_id: str,
    body: UpdateMachineRequest,
    tenant: TenantContext = Depends(require_permission("production.admin_machines")),
) -> dict:
    with get_connection() as connection:
        service = MachineService(connection)
        result = service.update_machine(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            machine_id=machine_id,
            work_center_id=body.work_center_id,
            code=body.code,
            name=body.name,
        )
        if isinstance(result, Err):
            connection.rollback()
            code = status.HTTP_404_NOT_FOUND if result.code == "NOT_FOUND" else status.HTTP_400_BAD_REQUEST
            raise HTTPException(code, {"code": result.code, "message": result.message})
        connection.commit()
    return _serialize_machine(result.value)


@router.post("/machines/{machine_id}/status")
def transition_machine_status(
    machine_id: str,
    body: TransitionMachineRequest,
    tenant: TenantContext = Depends(require_permission("production.manage_machines")),
) -> dict:
    with get_connection() as connection:
        service = MachineService(connection)
        result = service.transition_status(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, machine_id=machine_id, new_status=body.status
        )
        if isinstance(result, Err):
            connection.rollback()
            code = status.HTTP_404_NOT_FOUND if result.code == "NOT_FOUND" else status.HTTP_409_CONFLICT
            raise HTTPException(code, {"code": result.code, "message": result.message})
        connection.commit()
    return _serialize_machine(result.value)


def _serialize_recipe(recipe: Recipe) -> dict:
    return {
        "id": recipe.id,
        "target_product_id": recipe.target_product_id,
        "version": recipe.version,
        "status": recipe.status,
        "target_moisture_percentage": recipe.target_moisture_percentage,
        "origin": recipe.origin,
        "ai_confidence": recipe.ai_confidence,
        "previous_recipe_id": recipe.previous_recipe_id,
        "lines": [
            {
                "component_product_id": line.component_product_id,
                "default_percentage": line.default_percentage,
                "min_percentage": line.min_percentage,
                "max_percentage": line.max_percentage,
                "is_hard_limit": line.is_hard_limit,
            }
            for line in recipe.lines
        ],
    }


def _recipe_err_status(code: str) -> int:
    if code == "NOT_FOUND":
        return status.HTTP_404_NOT_FOUND
    if code == "INVALID_TRANSITION":
        return status.HTTP_409_CONFLICT
    return status.HTTP_400_BAD_REQUEST


@router.post("/recipes", status_code=status.HTTP_201_CREATED)
def create_recipe(
    body: CreateRecipeRequest, tenant: TenantContext = Depends(require_permission("production.manage_recipes"))
) -> dict:
    lines = tuple(
        RecipeLine(
            component_product_id=line.component_product_id,
            default_percentage=line.default_percentage,
            min_percentage=line.min_percentage,
            max_percentage=line.max_percentage,
            is_hard_limit=line.is_hard_limit,
        )
        for line in body.lines
    )
    with get_connection() as connection:
        service = RecipeService(connection)
        result = service.create_recipe(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            target_product_id=body.target_product_id,
            lines=lines,
            target_moisture_percentage=body.target_moisture_percentage,
            origin=body.origin,
            ai_confidence=body.ai_confidence,
        )
        if isinstance(result, Err):
            connection.rollback()
            raise HTTPException(_recipe_err_status(result.code), {"code": result.code, "message": result.message})
        connection.commit()
    return _serialize_recipe(result.value)


@router.post("/recipes/new-version", status_code=status.HTTP_201_CREATED)
def create_recipe_version(
    body: CreateRecipeVersionRequest, tenant: TenantContext = Depends(require_permission("production.manage_recipes"))
) -> dict:
    lines = tuple(
        RecipeLine(
            component_product_id=line.component_product_id,
            default_percentage=line.default_percentage,
            min_percentage=line.min_percentage,
            max_percentage=line.max_percentage,
            is_hard_limit=line.is_hard_limit,
        )
        for line in body.lines
    )
    with get_connection() as connection:
        service = RecipeService(connection)
        result = service.create_new_version(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            previous_recipe_id=body.previous_recipe_id,
            lines=lines,
            target_moisture_percentage=body.target_moisture_percentage,
            origin=body.origin,
            ai_confidence=body.ai_confidence,
        )
        if isinstance(result, Err):
            connection.rollback()
            raise HTTPException(_recipe_err_status(result.code), {"code": result.code, "message": result.message})
        connection.commit()
    return _serialize_recipe(result.value)


@router.get("/recipes")
def list_recipes(
    target_product_id: str | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    tenant: TenantContext = Depends(require_permission("production.view_recipes")),
) -> list[dict]:
    with get_connection() as connection:
        service = RecipeService(connection)
        recipes = service.list_recipes(tenant.tenant_id, target_product_id=target_product_id, status=status_filter)
    return [_serialize_recipe(recipe) for recipe in recipes]


@router.get("/recipes/{recipe_id}")
def get_recipe(
    recipe_id: str, tenant: TenantContext = Depends(require_permission("production.view_recipes"))
) -> dict:
    with get_connection() as connection:
        service = RecipeService(connection)
        recipe = service.get_recipe(tenant.tenant_id, recipe_id)
    if recipe is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, {"code": "NOT_FOUND", "message": f"recipe {recipe_id} not found"})
    return _serialize_recipe(recipe)


@router.post("/recipes/{recipe_id}/promote-to-trial")
def promote_recipe_to_trial(
    recipe_id: str, tenant: TenantContext = Depends(require_permission("production.manage_recipes"))
) -> dict:
    with get_connection() as connection:
        service = RecipeService(connection)
        result = service.promote_to_trial(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, recipe_id=recipe_id)
        if isinstance(result, Err):
            connection.rollback()
            raise HTTPException(_recipe_err_status(result.code), {"code": result.code, "message": result.message})
        connection.commit()
    return _serialize_recipe(result.value)


@router.post("/recipes/{recipe_id}/reject")
def reject_recipe(
    recipe_id: str, tenant: TenantContext = Depends(require_permission("production.manage_recipes"))
) -> dict:
    with get_connection() as connection:
        service = RecipeService(connection)
        result = service.reject_to_draft(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, recipe_id=recipe_id)
        if isinstance(result, Err):
            connection.rollback()
            raise HTTPException(_recipe_err_status(result.code), {"code": result.code, "message": result.message})
        connection.commit()
    return _serialize_recipe(result.value)


@router.post("/recipes/{recipe_id}/activate")
def activate_recipe(
    recipe_id: str, tenant: TenantContext = Depends(require_permission("production.activate_recipes"))
) -> dict:
    with get_connection() as connection:
        service = RecipeService(connection)
        result = service.activate_recipe(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, recipe_id=recipe_id)
        if isinstance(result, Err):
            connection.rollback()
            raise HTTPException(_recipe_err_status(result.code), {"code": result.code, "message": result.message})
        connection.commit()
    return _serialize_recipe(result.value)


@router.post("/recipes/{recipe_id}/archive")
def archive_recipe(
    recipe_id: str, tenant: TenantContext = Depends(require_permission("production.manage_recipes"))
) -> dict:
    with get_connection() as connection:
        service = RecipeService(connection)
        result = service.archive_recipe(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, recipe_id=recipe_id)
        if isinstance(result, Err):
            connection.rollback()
            raise HTTPException(_recipe_err_status(result.code), {"code": result.code, "message": result.message})
        connection.commit()
    return _serialize_recipe(result.value)


@router.get("/recipes/{recipe_id}/yield-summary")
def get_recipe_yield_summary(
    recipe_id: str, tenant: TenantContext = Depends(require_permission("production.view_recipes"))
) -> dict:
    with get_connection() as connection:
        return WorkOrderYieldService(connection).get_recipe_yield_summary(tenant_id=tenant.tenant_id, recipe_id=recipe_id)


def _serialize_scrap(scrap: ScrapRecord) -> dict:
    return {
        "id": scrap.id,
        "work_order_id": scrap.work_order_id,
        "operation_step_id": scrap.operation_step_id,
        "scrap_type": scrap.scrap_type,
        "product_id": scrap.product_id,
        "quantity": scrap.quantity,
        "is_reground": scrap.is_reground,
        "work_center_id": scrap.work_center_id,
        "source_note": scrap.source_note,
    }


def _serialize_regrind_batch(batch: dict) -> dict:
    return {
        "work_order": _serialize_work_order(batch["work_order"]),
        "scrap_record_ids": batch["scrap_record_ids"],
        "input_quantity_total": batch["input_quantity_total"],
        "loss_quantity": batch["loss_quantity"],
    }


def _regrind_err_status(code: str) -> int:
    if code == "NOT_FOUND":
        return status.HTTP_404_NOT_FOUND
    if code == "ALREADY_REGROUND":
        return status.HTTP_409_CONFLICT
    return status.HTTP_400_BAD_REQUEST


@router.post("/scrap-records", status_code=status.HTTP_201_CREATED)
def record_scrap(
    body: RecordScrapRequest, tenant: TenantContext = Depends(require_permission("production.manage_scrap"))
) -> dict:
    with get_connection() as connection:
        service = ScrapService(connection)
        result = service.record_scrap(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            work_order_id=body.work_order_id,
            work_center_id=body.work_center_id,
            source_note=body.source_note,
            scrap_type=body.scrap_type,
            product_id=body.product_id,
            quantity=body.quantity,
            operation_step_id=body.operation_step_id,
        )
        if isinstance(result, Err):
            connection.rollback()
            raise HTTPException(status.HTTP_400_BAD_REQUEST, {"code": result.code, "message": result.message})
        connection.commit()
    return _serialize_scrap(result.value)


@router.get("/scrap-records")
def list_scrap_records(
    work_order_id: str | None = None,
    is_reground: bool | None = None,
    tenant: TenantContext = Depends(require_permission("production.view_scrap")),
) -> list[dict]:
    with get_connection() as connection:
        service = ScrapService(connection)
        records = service.list_scrap(tenant_id=tenant.tenant_id, work_order_id=work_order_id, is_reground=is_reground)
    return [_serialize_scrap(record) for record in records]


@router.post("/regrind-batches", status_code=status.HTTP_201_CREATED)
def create_regrind_batch(
    body: CreateRegrindBatchRequest, tenant: TenantContext = Depends(require_permission("production.manage_regrind"))
) -> dict:
    with get_connection() as connection:
        service = RegrindService(connection)
        result = service.create_regrind_batch(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            scrap_record_ids=body.scrap_record_ids,
            output_product_id=body.output_product_id,
            output_quantity=body.output_quantity,
            work_center_id=body.work_center_id,
        )
        if isinstance(result, Err):
            connection.rollback()
            raise HTTPException(_regrind_err_status(result.code), {"code": result.code, "message": result.message})
        connection.commit()
    return _serialize_regrind_batch(result.value)


@router.get("/regrind-batches")
def list_regrind_batches(
    tenant: TenantContext = Depends(require_permission("production.view_regrind")),
) -> list[dict]:
    with get_connection() as connection:
        service = RegrindService(connection)
        batches = service.list_regrind_batches(tenant_id=tenant.tenant_id)
    return batches


@router.get("/regrind-batches/{work_order_id}")
def get_regrind_batch(
    work_order_id: str, tenant: TenantContext = Depends(require_permission("production.view_regrind"))
) -> dict:
    with get_connection() as connection:
        service = RegrindService(connection)
        batch = service.get_regrind_batch(tenant_id=tenant.tenant_id, work_order_id=work_order_id)
    if batch is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, {"code": "NOT_FOUND", "message": f"regrind batch {work_order_id} not found"}
        )
    return _serialize_regrind_batch(batch)


def _serialize_resource_type(resource_type: ResourceType) -> dict:
    return {"id": resource_type.id, "code": resource_type.code, "name": resource_type.name, "unit": resource_type.unit}


def _serialize_daily_consumption(entry: DailyConsumption) -> dict:
    return {
        "id": entry.id,
        "consumption_date": entry.consumption_date,
        "resource_type_id": entry.resource_type_id,
        "quantity": entry.quantity,
        "note": entry.note,
    }


@router.post("/resource-types", status_code=status.HTTP_201_CREATED)
def create_resource_type(
    body: CreateResourceTypeRequest,
    tenant: TenantContext = Depends(require_permission("production.manage_resource_consumption")),
) -> dict:
    with get_connection() as connection:
        service = ResourceTypeService(connection)
        result = service.create_resource_type(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, code=body.code, name=body.name, unit=body.unit
        )
        if isinstance(result, Err):
            connection.rollback()
            raise HTTPException(status.HTTP_400_BAD_REQUEST, {"code": result.code, "message": result.message})
        connection.commit()
    return _serialize_resource_type(result.value)


@router.get("/resource-types")
def list_resource_types(
    tenant: TenantContext = Depends(require_permission("production.view_resource_consumption")),
) -> list[dict]:
    with get_connection() as connection:
        service = ResourceTypeService(connection)
        resource_types = service.list_resource_types(tenant.tenant_id)
    return [_serialize_resource_type(rt) for rt in resource_types]


@router.patch("/resource-types/{resource_type_id}")
def update_resource_type(
    resource_type_id: str,
    body: UpdateResourceTypeRequest,
    tenant: TenantContext = Depends(require_permission("production.admin_resource_types")),
) -> dict:
    with get_connection() as connection:
        service = ResourceTypeService(connection)
        result = service.update_resource_type(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            resource_type_id=resource_type_id,
            code=body.code,
            name=body.name,
            unit=body.unit,
        )
        if isinstance(result, Err):
            connection.rollback()
            code = status.HTTP_404_NOT_FOUND if result.code == "NOT_FOUND" else status.HTTP_400_BAD_REQUEST
            raise HTTPException(code, {"code": result.code, "message": result.message})
        connection.commit()
    return _serialize_resource_type(result.value)


@router.post("/daily-consumption", status_code=status.HTTP_201_CREATED)
def record_daily_consumption(
    body: RecordDailyConsumptionRequest,
    tenant: TenantContext = Depends(require_permission("production.manage_resource_consumption")),
) -> dict:
    with get_connection() as connection:
        service = DailyConsumptionService(connection)
        result = service.record_consumption(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            consumption_date=body.consumption_date.isoformat(),
            resource_type_id=body.resource_type_id,
            quantity=body.quantity,
            note=body.note,
        )
        if isinstance(result, Err):
            connection.rollback()
            code = status.HTTP_404_NOT_FOUND if result.code == "NOT_FOUND" else status.HTTP_400_BAD_REQUEST
            raise HTTPException(code, {"code": result.code, "message": result.message})
        connection.commit()
    return _serialize_daily_consumption(result.value)


@router.get("/daily-consumption")
def list_daily_consumption(
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
    tenant: TenantContext = Depends(require_permission("production.view_resource_consumption")),
) -> list[dict]:
    with get_connection() as connection:
        service = DailyConsumptionService(connection)
        entries = service.list_consumption(
            tenant_id=tenant.tenant_id,
            date_from=date_from.isoformat() if date_from else None,
            date_to=date_to.isoformat() if date_to else None,
        )
    return [_serialize_daily_consumption(entry) for entry in entries]
