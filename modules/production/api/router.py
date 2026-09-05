from __future__ import annotations

import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from core.db import get_connection
from core.domain.result import Err
from core.tenancy import TenantContext, require_permission
from modules.production.api.packaging_bom_service import PackagingBomService
from modules.production.api.resource_type_service import ResourceTypeService
from modules.production.api.product_classification_service import ProductClassificationService
from modules.production.api.work_order_yield_service import WorkOrderYieldService
from modules.production.api.team_performance_service import GRAINS, TeamPerformanceService
from modules.production.domain.resource_type import ResourceType
from modules.production.domain.product_classification import ProductClassification
from modules.production.api.recipe_service import RecipeService
from modules.production.api.regrind_service import RegrindDefaultsService, RegrindService, ScrapService
from modules.production.api.of_consolidation_service import OfConsolidationService
from modules.production.api.packaging_variance_service import (
    PackagingTolerancePolicyService,
    PackagingVarianceService,
)
from modules.production.api.recipe_check_service import RecipeCheckService
from modules.production.api.production_report_service import ProductionReportService
from modules.production.api.service import WorkOrderService
from modules.production.api.work_center_service import WorkCenterService
from modules.production.api.mold_service import MoldService
from modules.production.domain.entities import WorkOrder
from modules.production.domain.mold import Mold
from modules.production.api.conditionnement_service import ConditionnementReportService
from modules.production.domain.production_report import (
    ConditionnementReportDetail,
    DailyReportDetail,
    ProductionReport,
    SemolinaLine,
    WasteLine,
)
from modules.production.domain.packaging_bom import PackagingBom, PackagingBomLine
from modules.production.domain.recipe import Recipe, RecipeLine
from modules.production.domain.regrind import ScrapRecord
from modules.production.domain.work_center import WorkCenter

router = APIRouter(prefix="/production", tags=["production"])


class PouredInputRequest(BaseModel):
    product_id: str
    quantity: float


class CreateWorkOrderRequest(BaseModel):
    # Nullable: creation names the work center, PC/PL and start date — not
    # the product. Conditionnement backfills it with the first packaging
    # report filed against this order.
    product_id: str | None = None
    # Nullable: the quantity is assigned later, once known, via the edit form.
    planned_quantity: float | None = None
    work_center_id: str | None = None
    recipe_id: str | None = None
    packaging_bom_id: str | None = None
    start_date: datetime.date | None = None
    product_type: str | None = None
    notes: str | None = None
    poured_inputs: list[PouredInputRequest] = []
    poured_inputs_location_id: str | None = None


class UpdateWorkOrderRequest(BaseModel):
    product_id: str | None = None
    planned_quantity: float | None = None
    work_center_id: str | None = None
    recipe_id: str | None = None
    packaging_bom_id: str | None = None
    start_date: datetime.date | None = None
    product_type: str | None = None
    notes: str | None = None


class CreateMoldRequest(BaseModel):
    code: str
    name: str
    type: str


class UpdateMoldRequest(BaseModel):
    code: str | None = None
    name: str | None = None
    type: str | None = None


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


class SuspendWorkOrderRequest(BaseModel):
    reason: str | None = None


class CloseWorkOrderRequest(BaseModel):
    correlation_id: str
    # Close over unfinished reports. Demands a reason, which is audited.
    force: bool = False
    force_reason: str | None = None
    # When the order actually finished. Defaults to now when omitted.
    closed_at: datetime.datetime | None = None


class CompleteRegrindBatchRequest(BaseModel):
    correlation_id: str
    location_id: str
    actual_output_quantity: float | None = None


class SetProductClassificationRequest(BaseModel):
    product_id: str
    category: str
    is_regrind: bool = False
    packaging_format: str | None = None
    is_water: bool = False


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
    output_quantity: float
    work_center_id: str


class AssignRegrindBatchRequest(BaseModel):
    team: str


class WasteLineRequest(BaseModel):
    """One déchet on a report: what stage lost it, which item, how much.

    `product_id` is optional here and required to submit. A team typing a
    draft may not have decided yet which of two films was spoiled; a report
    arriving at the validation desk without an item cannot be judged, because
    the quantity has no unit.
    """

    category: str
    product_id: str | None = None
    quantity: float = 0
    note: str | None = None

    def to_line(self, order: int) -> WasteLine:
        return WasteLine(
            category=self.category,
            product_id=self.product_id,
            quantity=self.quantity,
            note=self.note,
            line_order=order,
        )


def _waste_lines(lines: list[WasteLineRequest]) -> tuple[WasteLine, ...]:
    """Order comes from the request order -- the shift's own, not a sort."""
    return tuple(line.to_line(order) for order, line in enumerate(lines))


def _serialize_waste_line(line: WasteLine) -> dict:
    return {
        "category": line.category,
        "product_id": line.product_id,
        "quantity": line.quantity,
        "note": line.note,
    }


class SemolinaLineRequest(BaseModel):
    """One quality of semoule poured into one report.

    `product_id` and `location_id` are optional here and required to submit —
    same reasoning as a waste line's item: a team typing a draft may not have
    decided yet, but a report at the validation desk with an unlabelled
    quantity cannot be judged or posted.
    """

    product_id: str | None = None
    quantity: float = 0
    location_id: str | None = None

    def to_line(self, order: int) -> SemolinaLine:
        return SemolinaLine(
            product_id=self.product_id,
            quantity=self.quantity,
            location_id=self.location_id,
            line_order=order,
        )


def _semolina_lines(lines: list[SemolinaLineRequest]) -> tuple[SemolinaLine, ...]:
    """Order comes from the request order -- the shift's own, not a sort."""
    return tuple(line.to_line(order) for order, line in enumerate(lines))


def _serialize_semolina_line(line: SemolinaLine) -> dict:
    return {
        "product_id": line.product_id,
        "quantity": line.quantity,
        "location_id": line.location_id,
    }


class DailyReportDetailRequest(BaseModel):
    dough_quantity: float = 0
    # Recorded for yield and consolidation; it posts no stock. The finished product
    # enters stock once, when the conditionnement report is validated.
    finished_product_quantity: float = 0
    regrind_quantity: float = 0
    water_quantity: float = 0
    # Water dosed as a percentage of the semoule poured -- the operator's real
    # input; the frontend derives water_quantity from it.
    water_percentage: float = 0
    fuel_quantity: float = 0
    electricity_quantity: float = 0
    # Débit de semoule: feed rate in tonnes/hour. Recorded only, for future
    # recipe statistics -- see PRODUCTION_RECIPE_STATISTICS_PLAN.md.
    semolina_flow_rate: float = 0
    start_time: datetime.time | None = None
    end_time: datetime.time | None = None
    production_minutes: int = 0
    downtime_minutes: int = 0
    downtime_reason: str | None = None
    # Semoule poured this shift, one line per quality, each with its own store.
    semolina_lines: list[SemolinaLineRequest] = []
    # Rebroyat's own store — kept separate from the semoule lines' locations.
    raw_material_location_id: str | None = None
    # Rebroyat poured back into the mix — a raw material like any other, deducted
    # from the same store on validation.
    regrind_input_quantity: float = 0
    regrind_input_product_id: str | None = None
    # What this shift's rebroyat is. The scrap record and the regrind OF are
    # opened against it; unset, they fall back to the OF's finished product.
    regrind_product_id: str | None = None
    # Which mold this shift ran — named per report, not on the OF.
    mold_id: str | None = None
    # Déchets: raw_material, press, pouring and cutting stages only, one line
    # per item lost.
    waste_lines: list[WasteLineRequest] = []

    def to_detail(self) -> DailyReportDetail:
        payload = self.model_dump()
        payload["waste_lines"] = _waste_lines(self.waste_lines)
        payload["semolina_lines"] = _semolina_lines(self.semolina_lines)
        return DailyReportDetail(**payload)


class CreateDailyReportRequest(BaseModel):
    of_id: str
    report_date: datetime.date
    team: str | None = None
    work_center_id: str | None = None
    shift: str | None = None
    detail: DailyReportDetailRequest = DailyReportDetailRequest()


class UpdateDailyReportRequest(BaseModel):
    detail: DailyReportDetailRequest


class CorrectDailyReportRequest(BaseModel):
    detail: DailyReportDetailRequest
    reason: str


class RejectReportRequest(BaseModel):
    reason: str


class DeleteReportRequest(BaseModel):
    # Mandatory: the row is gone afterwards, so the audit entry is the only record
    # that it ever existed.
    reason: str


class ValidateReportRequest(BaseModel):
    correlation_id: str | None = None
    # Required only when the report consumes more than the stock figure holds.
    shortfall_comment: str | None = None
    # Only meaningful when the daily report being validated carries rebroyat:
    # which work center the automatically-opened regrind OF should run on.
    # Left unset, it falls back to the validating report's own work center.
    regrind_work_center_id: str | None = None


class ConditionnementDetailRequest(BaseModel):
    # Phase 9, decision 17: the tonnage off the scale, which feeds yield and
    # consolidation and moves nothing on its own.
    finished_product_quantity: float = 0
    # What the line tallied, in the product's own unit. Decision 18: this is what
    # validation posts into stock.
    packets_counted: float = 0
    film_quantity: float = 0
    carton_quantity: float = 0
    tape_quantity: float = 0
    machine_speed: float | None = None
    production_minutes: int = 0
    downtime_minutes: int = 0
    downtime_reason: str | None = None
    lot_number: str | None = None
    dlc_date: datetime.date | None = None
    film_product_id: str | None = None
    carton_product_id: str | None = None
    tape_product_id: str | None = None
    packaging_location_id: str | None = None
    finished_goods_location_id: str | None = None
    # Déchets: product and packaging stages only.
    waste_lines: list[WasteLineRequest] = []

    def to_detail(self) -> ConditionnementReportDetail:
        payload = self.model_dump()
        payload["waste_lines"] = _waste_lines(self.waste_lines)
        return ConditionnementReportDetail(**payload)


class SetPackagingToleranceRequest(BaseModel):
    tolerance_percent: float
    # None means the tenant-wide default row, matching qc.follow_up_policies.
    product_id: str | None = None


class CreateConditionnementReportRequest(BaseModel):
    of_id: str
    report_date: datetime.date
    team: str | None = None
    work_center_id: str | None = None
    shift: str | None = None
    # Only required when the order has no product yet — its first packaging
    # report is what names one.
    product_id: str | None = None
    detail: ConditionnementDetailRequest = ConditionnementDetailRequest()


class UpdateConditionnementReportRequest(BaseModel):
    detail: ConditionnementDetailRequest


class CorrectConditionnementReportRequest(BaseModel):
    detail: ConditionnementDetailRequest
    reason: str


class SetRegrindDefaultRequest(BaseModel):
    output_product_id: str
    input_product_id: str | None = None


class CreateResourceTypeRequest(BaseModel):
    code: str
    name: str
    unit: str


class UpdateResourceTypeRequest(BaseModel):
    code: str | None = None
    name: str | None = None
    unit: str | None = None


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
            planned_quantity=body.planned_quantity,
            work_center_id=body.work_center_id,
            recipe_id=body.recipe_id,
            packaging_bom_id=body.packaging_bom_id,
            start_date=body.start_date,
            product_type=body.product_type,
            notes=body.notes,
            poured_inputs=[(i.product_id, i.quantity) for i in body.poured_inputs],
            poured_inputs_location_id=body.poured_inputs_location_id,
        )
        if isinstance(result, Err):
            connection.rollback()
            raise HTTPException(status.HTTP_400_BAD_REQUEST, {"code": result.code, "message": result.message})
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


@router.get("/work-orders/recipe-correlation")
def list_recipe_correlation(
    tenant: TenantContext = Depends(require_permission("production.view_work_orders")),
) -> list[dict]:
    """Each shift's water dosage and flow rate, against its OF's yield."""
    with get_connection() as connection:
        return WorkOrderYieldService(connection).list_recipe_correlation(tenant_id=tenant.tenant_id)


@router.get("/work-orders/{work_order_id}/inputs")
def list_work_order_inputs(
    work_order_id: str, tenant: TenantContext = Depends(require_permission("production.view_work_orders"))
) -> list[dict]:
    with get_connection() as connection:
        return WorkOrderService(connection).list_work_order_inputs(tenant.tenant_id, work_order_id)


@router.get("/work-orders/{work_order_id}/consolidation")
def get_work_order_consolidation(
    work_order_id: str, tenant: TenantContext = Depends(require_permission("production.view_work_orders"))
) -> dict:
    """Everything this OF produced and consumed, summed from its validated reports.

    Computed live and never stored: a cached total and the reports behind it can
    disagree, and when they do there is no way to tell which is wrong.
    """
    with get_connection() as connection:
        result = OfConsolidationService(connection).consolidate(
            tenant_id=tenant.tenant_id, of_id=work_order_id
        )
    if isinstance(result, Err):
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, {"code": result.code, "message": result.message}
        )
    return result.value


@router.get("/work-orders/{work_order_id}/packaging-variance")
def get_work_order_packaging_variance(
    work_order_id: str, tenant: TenantContext = Depends(require_permission("production.view_work_orders"))
) -> dict:
    """Ecart net: what this OF's tonnage should have packed, against what it did.

    Quality's rejections are subtracted (decision 21), so this is the figure that
    answers "how much good product should be in the store". Read-only by decision
    22 — nothing here refuses anything.
    """
    with get_connection() as connection:
        result = PackagingVarianceService(connection).for_of(
            tenant_id=tenant.tenant_id, of_id=work_order_id
        )
    if isinstance(result, Err):
        raise HTTPException(status.HTTP_404_NOT_FOUND, {"code": result.code, "message": result.message})
    return result.value


@router.get("/reports/{report_id}/packaging-variance")
def get_report_packaging_variance(
    report_id: str, tenant: TenantContext = Depends(require_permission("production.view_reports"))
) -> dict:
    """Ecart de conditionnement: the scale against the counter, for one report.

    No quality adjustment, because at the validation desk there usually is none
    yet — an NC is normally raised days after the shift. This ecart is complete
    the moment the report is, which is what makes it worth showing there.
    """
    with get_connection() as connection:
        result = PackagingVarianceService(connection).for_report(
            tenant_id=tenant.tenant_id, report_id=report_id
        )
    if isinstance(result, Err):
        raise HTTPException(status.HTTP_404_NOT_FOUND, {"code": result.code, "message": result.message})
    return result.value


@router.get("/packaging-variance")
def list_packaging_variance(
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    tenant: TenantContext = Depends(require_permission("production.view_reports")),
) -> list[dict]:
    """Ecart net per finished product over a period, for the finished-goods store."""
    with get_connection() as connection:
        return PackagingVarianceService(connection).by_product(
            tenant_id=tenant.tenant_id, date_from=date_from, date_to=date_to
        )


@router.get("/packaging-tolerances")
def list_packaging_tolerances(
    tenant: TenantContext = Depends(require_permission("production.view_reports")),
) -> list[dict]:
    with get_connection() as connection:
        return PackagingTolerancePolicyService(connection).list_policies(tenant_id=tenant.tenant_id)


@router.put("/packaging-tolerances")
def set_packaging_tolerance(
    body: SetPackagingToleranceRequest,
    tenant: TenantContext = Depends(require_permission("production.admin_reports")),
) -> dict:
    """The percentage at which an ecart stops looking like rounding.

    `product_id` omitted sets the tenant default; naming one sets an override.
    It colours a number and gates nothing, so it is deliberately not a validation
    permission.
    """
    with get_connection() as connection:
        result = PackagingTolerancePolicyService(connection).set_policy(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            tolerance_percent=body.tolerance_percent,
            product_id=body.product_id,
        )
        if isinstance(result, Err):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, {"code": result.code, "message": result.message}
            )
        connection.commit()
    return result.value


@router.get("/work-orders/{work_order_id}/recipe-check")
def get_work_order_recipe_check(
    work_order_id: str, tenant: TenantContext = Depends(require_permission("production.view_work_orders"))
) -> dict:
    """What was poured, measured against the OF's recipe.

    Advisory only. Nothing in the report or validation flow reads this: the line
    has already run, and refusing the paperwork does not change what went into the
    mix. It exists so a supervisor sees the drift and can act on the next batch.
    """
    with get_connection() as connection:
        result = RecipeCheckService(connection).check_work_order(
            tenant_id=tenant.tenant_id, of_id=work_order_id
        )
    if isinstance(result, Err):
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, {"code": result.code, "message": result.message}
        )
    return result.value


@router.get("/work-orders/{work_order_id}/yield")
def get_work_order_yield(
    work_order_id: str, tenant: TenantContext = Depends(require_permission("production.view_work_orders"))
) -> dict:
    with get_connection() as connection:
        result = WorkOrderYieldService(connection).get_work_order_yield(tenant_id=tenant.tenant_id, work_order_id=work_order_id)
    if result is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, {"code": "NOT_FOUND", "message": f"no computable yield for work order {work_order_id}"})
    return result


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
            product_id=body.product_id,
            planned_quantity=body.planned_quantity,
            work_center_id=body.work_center_id,
            recipe_id=body.recipe_id,
            packaging_bom_id=body.packaging_bom_id,
            start_date=body.start_date,
            product_type=body.product_type,
            notes=body.notes,
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


@router.post("/work-orders/{work_order_id}/suspend")
def suspend_work_order(
    work_order_id: str,
    body: SuspendWorkOrderRequest,
    tenant: TenantContext = Depends(require_permission("production.suspend_work_orders")),
) -> dict:
    with get_connection() as connection:
        service = WorkOrderService(connection)
        result = service.suspend_work_order(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, work_order_id=work_order_id, reason=body.reason
        )
        if isinstance(result, Err):
            connection.rollback()
            code = status.HTTP_404_NOT_FOUND if result.code == "NOT_FOUND" else status.HTTP_409_CONFLICT
            raise HTTPException(code, {"code": result.code, "message": result.message})
        connection.commit()
    return _serialize_work_order(result.value)


@router.post("/work-orders/{work_order_id}/resume")
def resume_work_order(
    work_order_id: str,
    tenant: TenantContext = Depends(require_permission("production.suspend_work_orders")),
) -> dict:
    with get_connection() as connection:
        service = WorkOrderService(connection)
        result = service.resume_work_order(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, work_order_id=work_order_id
        )
        if isinstance(result, Err):
            connection.rollback()
            code = status.HTTP_404_NOT_FOUND if result.code == "NOT_FOUND" else status.HTTP_409_CONFLICT
            raise HTTPException(code, {"code": result.code, "message": result.message})
        connection.commit()
    return _serialize_work_order(result.value)


@router.post("/work-orders/{work_order_id}/cancel")
def cancel_work_order(
    work_order_id: str,
    body: SuspendWorkOrderRequest,
    tenant: TenantContext = Depends(require_permission("production.close_work_orders")),
) -> dict:
    with get_connection() as connection:
        service = WorkOrderService(connection)
        result = service.cancel_work_order(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, work_order_id=work_order_id, reason=body.reason
        )
        if isinstance(result, Err):
            connection.rollback()
            code = status.HTTP_404_NOT_FOUND if result.code == "NOT_FOUND" else status.HTTP_409_CONFLICT
            raise HTTPException(code, {"code": result.code, "message": result.message})
        connection.commit()
    return _serialize_work_order(result.value)


@router.post("/work-orders/{work_order_id}/close")
def close_work_order(
    work_order_id: str,
    body: CloseWorkOrderRequest,
    tenant: TenantContext = Depends(require_permission("production.close_work_orders")),
) -> dict:
    with get_connection() as connection:
        service = WorkOrderService(connection)
        result = service.close_work_order(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            work_order_id=work_order_id,
            correlation_id=body.correlation_id,
            force=body.force,
            force_reason=body.force_reason,
            closed_at=body.closed_at,
        )
        if isinstance(result, Err):
            connection.rollback()
            code = status.HTTP_404_NOT_FOUND if result.code == "NOT_FOUND" else status.HTTP_409_CONFLICT
            raise HTTPException(code, {"code": result.code, "message": result.message})
        connection.commit()
    return _serialize_work_order(result.value)


@router.get("/work-orders/{work_order_id}/pre-close-check")
def pre_close_check(
    work_order_id: str, tenant: TenantContext = Depends(require_permission("production.view_work_orders"))
) -> dict:
    """What still stands between this OF and closure.

    Blockers are unfinished production work. Warnings are worth seeing but never
    hold an order open — quality follow-up in particular outlives production by
    design.
    """
    with get_connection() as connection:
        result = WorkOrderService(connection).pre_close_check(
            tenant_id=tenant.tenant_id, work_order_id=work_order_id
        )
    if isinstance(result, Err):
        raise HTTPException(status.HTTP_404_NOT_FOUND, {"code": result.code, "message": result.message})
    return result.value


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
        "planned_quantity": order.planned_quantity,
        "status": order.status,
        "work_center_id": order.work_center_id,
        "recipe_id": order.recipe_id,
        "packaging_bom_id": order.packaging_bom_id,
        "start_date": order.start_date.isoformat() if order.start_date is not None else None,
        "product_type": order.product_type,
        "notes": order.notes,
        "created_by": order.created_by,
        "closed_at": order.closed_at.isoformat() if order.closed_at is not None else None,
        "closed_by": order.closed_by,
    }


def _serialize_classification(classification: ProductClassification) -> dict:
    return {
        "product_id": classification.product_id,
        "category": classification.category,
        "is_regrind": classification.is_regrind,
        "packaging_format": classification.packaging_format,
        "is_water": classification.is_water,
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


def _serialize_mold(mold: Mold) -> dict:
    return {"id": mold.id, "code": mold.code, "name": mold.name, "type": mold.type}


@router.post("/molds", status_code=status.HTTP_201_CREATED)
def create_mold(
    body: CreateMoldRequest,
    tenant: TenantContext = Depends(require_permission("production.manage_work_centers")),
) -> dict:
    with get_connection() as connection:
        service = MoldService(connection)
        result = service.create_mold(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            code=body.code,
            name=body.name,
            type=body.type,
        )
        if isinstance(result, Err):
            connection.rollback()
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, {"code": result.code, "message": result.message})
        connection.commit()
    return _serialize_mold(result.value)


@router.get("/molds")
def list_molds(
    tenant: TenantContext = Depends(require_permission("production.view_work_centers")),
) -> list[dict]:
    with get_connection() as connection:
        molds = MoldService(connection).list_molds(tenant_id=tenant.tenant_id)
    return [_serialize_mold(m) for m in molds]


@router.patch("/molds/{mold_id}")
def update_mold(
    mold_id: str,
    body: UpdateMoldRequest,
    tenant: TenantContext = Depends(require_permission("production.manage_work_centers")),
) -> dict:
    with get_connection() as connection:
        service = MoldService(connection)
        result = service.update_mold(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            mold_id=mold_id,
            code=body.code,
            name=body.name,
            type=body.type,
        )
        if isinstance(result, Err):
            connection.rollback()
            code = status.HTTP_404_NOT_FOUND if result.code == "NOT_FOUND" else status.HTTP_400_BAD_REQUEST
            raise HTTPException(code, {"code": result.code, "message": result.message})
        connection.commit()
    return _serialize_mold(result.value)


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
        "actual_output_quantity": batch["actual_output_quantity"],
        "loss_quantity": batch["loss_quantity"],
        "stage": batch["stage"],
        "assigned_team": batch["assigned_team"],
        "assigned_by": batch["assigned_by"],
        "assigned_at": batch["assigned_at"],
    }


def _regrind_err_status(code: str) -> int:
    if code == "NOT_FOUND":
        return status.HTTP_404_NOT_FOUND
    if code in ("ALREADY_REGROUND", "ALREADY_ASSIGNED"):
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
            output_quantity=body.output_quantity,
            work_center_id=body.work_center_id,
        )
        if isinstance(result, Err):
            connection.rollback()
            raise HTTPException(_regrind_err_status(result.code), {"code": result.code, "message": result.message})
        connection.commit()
    return _serialize_regrind_batch(result.value)


@router.post("/regrind-batches/{work_order_id}/assign")
def assign_regrind_batch(
    work_order_id: str,
    body: AssignRegrindBatchRequest,
    tenant: TenantContext = Depends(require_permission("production.assign_regrind")),
) -> dict:
    with get_connection() as connection:
        service = RegrindService(connection)
        result = service.assign_batch(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            work_order_id=work_order_id,
            team=body.team,
        )
        if isinstance(result, Err):
            connection.rollback()
            raise HTTPException(_regrind_err_status(result.code), {"code": result.code, "message": result.message})
        connection.commit()
    return _serialize_regrind_batch(result.value)


@router.post("/regrind-batches/{work_order_id}/complete")
def complete_regrind_batch(
    work_order_id: str,
    body: CompleteRegrindBatchRequest,
    tenant: TenantContext = Depends(require_permission("production.manage_regrind")),
) -> dict:
    with get_connection() as connection:
        service = RegrindService(connection)
        result = service.complete_batch(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            work_order_id=work_order_id,
            correlation_id=body.correlation_id,
            location_id=body.location_id,
            actual_output_quantity=body.actual_output_quantity,
        )
        if isinstance(result, Err):
            connection.rollback()
            raise HTTPException(_regrind_err_status(result.code), {"code": result.code, "message": result.message})
        connection.commit()
    value = result.value
    return {
        "work_order": _serialize_work_order(value["work_order"]),
        "input_quantity_total": value["input_quantity_total"],
        "output_quantity": value["output_quantity"],
        "loss_quantity": value["loss_quantity"],
    }


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


# --- production reports ---------------------------------------------------
#
# A report is the team's claim about a shift until a supervisor validates it.
# Approving and correcting are deliberately separate rights:
# production.validate_reports lets a supervisor accept the figures,
# production.admin_reports lets them change what the team entered first.


def _report_err_status(code: str) -> int:
    if code == "NOT_FOUND":
        return status.HTTP_404_NOT_FOUND
    if code in (
        "INVALID_TRANSITION",
        "NOT_EDITABLE",
        "NOT_CORRECTABLE",
        "OF_NOT_OPEN",
        "DUPLICATE_REPORT",
        "SHORTFALL_COMMENT_REQUIRED",
        "REGRIND_DEFAULT_MISSING",
        "MISSING_STOCK_TARGET",
        "REGRIND_ALREADY_COMPLETED",
    ):
        return status.HTTP_409_CONFLICT
    return status.HTTP_400_BAD_REQUEST


@router.post("/reports/daily", status_code=status.HTTP_201_CREATED)
def create_daily_report(
    body: CreateDailyReportRequest,
    tenant: TenantContext = Depends(require_permission("production.manage_reports")),
) -> dict:
    with get_connection() as connection:
        result = ProductionReportService(connection).create_daily_report(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            of_id=body.of_id,
            report_date=body.report_date,
            detail=body.detail.to_detail(),
            team=body.team,
            work_center_id=body.work_center_id,
            shift=body.shift,
        )
        if isinstance(result, Err):
            connection.rollback()
            raise HTTPException(_report_err_status(result.code), {"code": result.code, "message": result.message})
        connection.commit()
    return _serialize_report_with_detail(result.value)


@router.get("/reports")
def list_reports(
    of_id: str | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    report_type: str | None = None,
    tenant: TenantContext = Depends(require_permission("production.view_reports")),
) -> list[dict]:
    with get_connection() as connection:
        reports = ProductionReportService(connection).list_reports(
            tenant_id=tenant.tenant_id, of_id=of_id, status=status_filter, report_type=report_type
        )
    return [_serialize_report(report) for report in reports]


@router.get("/reports/team-performance")
def list_team_performance(
    grain: str = Query(default="week"),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    tenant: TenantContext = Depends(require_permission("production.view_reports")),
) -> list[dict]:
    """Output, time and waste from validated reports, bucketed by team and period.

    Team is whatever Production Settings has configured — there is no fixed
    list here, so a new team shows up the moment its first validated report
    lands in the window.
    """
    if grain not in GRAINS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            {"code": "INVALID_GRAIN", "message": f"grain must be one of {GRAINS}"},
        )
    with get_connection() as connection:
        return TeamPerformanceService(connection).list_team_performance(
            tenant_id=tenant.tenant_id, grain=grain, date_from=date_from, date_to=date_to
        )


@router.get("/reports/downtime-reasons")
def list_downtime_reasons(
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    tenant: TenantContext = Depends(require_permission("production.view_reports")),
) -> list[dict]:
    """Minutes lost per stated reason, from validated reports, worst first."""
    with get_connection() as connection:
        return TeamPerformanceService(connection).list_downtime_reasons(
            tenant_id=tenant.tenant_id, date_from=date_from, date_to=date_to
        )


@router.get("/reports/{report_id}")
def get_report(
    report_id: str, tenant: TenantContext = Depends(require_permission("production.view_reports"))
) -> dict:
    with get_connection() as connection:
        report = ProductionReportService(connection).get_report(tenant_id=tenant.tenant_id, report_id=report_id)
    if report is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, {"code": "NOT_FOUND", "message": f"report {report_id} not found"})
    return _serialize_report_with_detail(report)


@router.get("/reports/{report_id}/revisions")
def list_report_revisions(
    report_id: str, tenant: TenantContext = Depends(require_permission("production.view_reports"))
) -> list[dict]:
    """Every frozen version of the figures, oldest first.

    Revision 1 is what the team submitted; anything after it is a validator's
    correction with its reason. The first is never overwritten.
    """
    with get_connection() as connection:
        return ProductionReportService(connection).list_revisions(tenant_id=tenant.tenant_id, report_id=report_id)


@router.patch("/reports/daily/{report_id}")
def update_daily_report(
    report_id: str,
    body: UpdateDailyReportRequest,
    tenant: TenantContext = Depends(require_permission("production.manage_reports")),
) -> dict:
    with get_connection() as connection:
        result = ProductionReportService(connection).update_daily_draft(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            report_id=report_id,
            detail=body.detail.to_detail(),
        )
        if isinstance(result, Err):
            connection.rollback()
            raise HTTPException(_report_err_status(result.code), {"code": result.code, "message": result.message})
        connection.commit()
    return _serialize_report_with_detail(result.value)


@router.post("/reports/conditionnement", status_code=status.HTTP_201_CREATED)
def create_conditionnement_report(
    body: CreateConditionnementReportRequest,
    tenant: TenantContext = Depends(require_permission("production.manage_reports")),
) -> dict:
    with get_connection() as connection:
        result = ConditionnementReportService(connection).create_report(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            of_id=body.of_id,
            report_date=body.report_date,
            detail=body.detail.to_detail(),
            team=body.team,
            work_center_id=body.work_center_id,
            shift=body.shift,
            product_id=body.product_id,
        )
        if isinstance(result, Err):
            connection.rollback()
            raise HTTPException(_report_err_status(result.code), {"code": result.code, "message": result.message})
        connection.commit()
    return _serialize_report_with_detail(result.value)


@router.patch("/reports/conditionnement/{report_id}")
def update_conditionnement_report(
    report_id: str,
    body: UpdateConditionnementReportRequest,
    tenant: TenantContext = Depends(require_permission("production.manage_reports")),
) -> dict:
    with get_connection() as connection:
        result = ConditionnementReportService(connection).update_draft(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            report_id=report_id,
            detail=body.detail.to_detail(),
        )
        if isinstance(result, Err):
            connection.rollback()
            raise HTTPException(_report_err_status(result.code), {"code": result.code, "message": result.message})
        connection.commit()
    return _serialize_report_with_detail(result.value)


@router.patch("/reports/conditionnement/{report_id}/correct")
def correct_conditionnement_report(
    report_id: str,
    body: CorrectConditionnementReportRequest,
    tenant: TenantContext = Depends(require_permission("production.admin_reports")),
) -> dict:
    with get_connection() as connection:
        result = ConditionnementReportService(connection).correct_report(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            report_id=report_id,
            detail=body.detail.to_detail(),
            reason=body.reason,
        )
        if isinstance(result, Err):
            connection.rollback()
            raise HTTPException(_report_err_status(result.code), {"code": result.code, "message": result.message})
        connection.commit()
    return _serialize_report_with_detail(result.value)


@router.post("/reports/{report_id}/submit")
def submit_report(
    report_id: str, tenant: TenantContext = Depends(require_permission("production.manage_reports"))
) -> dict:
    with get_connection() as connection:
        result = ProductionReportService(connection).submit_report(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, report_id=report_id
        )
        if isinstance(result, Err):
            connection.rollback()
            raise HTTPException(_report_err_status(result.code), {"code": result.code, "message": result.message})
        connection.commit()
    return _serialize_report(result.value)


@router.patch("/reports/daily/{report_id}/correct")
def correct_daily_report(
    report_id: str,
    body: CorrectDailyReportRequest,
    tenant: TenantContext = Depends(require_permission("production.admin_reports")),
) -> dict:
    with get_connection() as connection:
        result = ProductionReportService(connection).correct_daily_report(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            report_id=report_id,
            detail=body.detail.to_detail(),
            reason=body.reason,
        )
        if isinstance(result, Err):
            connection.rollback()
            raise HTTPException(_report_err_status(result.code), {"code": result.code, "message": result.message})
        connection.commit()
    return _serialize_report_with_detail(result.value)


@router.post("/reports/{report_id}/validate")
def validate_report(
    report_id: str,
    body: ValidateReportRequest = ValidateReportRequest(),
    tenant: TenantContext = Depends(require_permission("production.validate_reports")),
) -> dict:
    """Validation is what posts stock. A shortfall posts anyway but needs a comment."""
    with get_connection() as connection:
        result = ProductionReportService(connection).validate_report(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            report_id=report_id,
            correlation_id=body.correlation_id,
            shortfall_comment=body.shortfall_comment,
            regrind_work_center_id=body.regrind_work_center_id,
        )
        if isinstance(result, Err):
            connection.rollback()
            raise HTTPException(_report_err_status(result.code), {"code": result.code, "message": result.message})
        connection.commit()
    return _serialize_report(result.value)


@router.post("/reports/{report_id}/reject")
def reject_report(
    report_id: str,
    body: RejectReportRequest,
    tenant: TenantContext = Depends(require_permission("production.validate_reports")),
) -> dict:
    with get_connection() as connection:
        result = ProductionReportService(connection).reject_report(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, report_id=report_id, reason=body.reason
        )
        if isinstance(result, Err):
            connection.rollback()
            raise HTTPException(_report_err_status(result.code), {"code": result.code, "message": result.message})
        connection.commit()
    return _serialize_report(result.value)


@router.delete("/reports/{report_id}")
def delete_report(
    report_id: str,
    body: DeleteReportRequest,
    tenant: TenantContext = Depends(require_permission("production.admin_reports")),
) -> dict:
    """Delete a report, undoing whatever it posted.

    A validated report has moved stock, so deleting it reverses those movements
    first. Gated by admin_reports — the same elevated right that lets a validator
    change entered figures.
    """
    with get_connection() as connection:
        result = ProductionReportService(connection).delete_report(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            report_id=report_id,
            reason=body.reason,
        )
        if isinstance(result, Err):
            connection.rollback()
            raise HTTPException(_report_err_status(result.code), {"code": result.code, "message": result.message})
        connection.commit()
    return result.value


@router.patch("/reports/daily/{report_id}/correct-validated")
def correct_validated_daily_report(
    report_id: str,
    body: CorrectDailyReportRequest,
    tenant: TenantContext = Depends(require_permission("production.admin_reports")),
) -> dict:
    """Change a validated daily report, reversing and re-posting its stock."""
    with get_connection() as connection:
        result = ProductionReportService(connection).correct_validated_report(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            report_id=report_id,
            detail=body.detail.to_detail(),
            reason=body.reason,
        )
        if isinstance(result, Err):
            connection.rollback()
            raise HTTPException(_report_err_status(result.code), {"code": result.code, "message": result.message})
        connection.commit()
    return _serialize_report_with_detail(result.value)


@router.patch("/reports/conditionnement/{report_id}/correct-validated")
def correct_validated_conditionnement_report(
    report_id: str,
    body: CorrectConditionnementReportRequest,
    tenant: TenantContext = Depends(require_permission("production.admin_reports")),
) -> dict:
    """Change a validated conditionnement report, reversing and re-posting its stock."""
    with get_connection() as connection:
        result = ProductionReportService(connection).correct_validated_report(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            report_id=report_id,
            detail=body.detail.to_detail(),
            reason=body.reason,
        )
        if isinstance(result, Err):
            connection.rollback()
            raise HTTPException(_report_err_status(result.code), {"code": result.code, "message": result.message})
        connection.commit()
    return _serialize_report_with_detail(result.value)


@router.post("/reports/{report_id}/revise")
def revise_report(
    report_id: str, tenant: TenantContext = Depends(require_permission("production.manage_reports"))
) -> dict:
    """Reopen a rejected report so the team can correct and resubmit it."""
    with get_connection() as connection:
        result = ProductionReportService(connection).revise_report(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, report_id=report_id
        )
        if isinstance(result, Err):
            connection.rollback()
            raise HTTPException(_report_err_status(result.code), {"code": result.code, "message": result.message})
        connection.commit()
    return _serialize_report(result.value)


def _serialize_report(report: ProductionReport) -> dict:
    return {
        "id": report.id,
        "of_id": report.of_id,
        "report_type": report.report_type,
        "report_date": report.report_date.isoformat(),
        "status": report.status,
        "revision": report.revision,
        "team": report.team,
        "work_center_id": report.work_center_id,
        "shift": report.shift,
        "created_by": report.created_by,
        "submitted_at": report.submitted_at.isoformat() if report.submitted_at is not None else None,
        "validated_by": report.validated_by,
        "validated_at": report.validated_at.isoformat() if report.validated_at is not None else None,
        "rejection_reason": report.rejection_reason,
    }


def _serialize_daily_detail(detail: DailyReportDetail) -> dict:
    return {
        "dough_quantity": detail.dough_quantity,
        "finished_product_quantity": detail.finished_product_quantity,
        "regrind_quantity": detail.regrind_quantity,
        "water_quantity": detail.water_quantity,
        "water_percentage": detail.water_percentage,
        "fuel_quantity": detail.fuel_quantity,
        "electricity_quantity": detail.electricity_quantity,
        "semolina_flow_rate": detail.semolina_flow_rate,
        "start_time": detail.start_time.isoformat() if detail.start_time is not None else None,
        "end_time": detail.end_time.isoformat() if detail.end_time is not None else None,
        "production_minutes": detail.production_minutes,
        "downtime_minutes": detail.downtime_minutes,
        "downtime_reason": detail.downtime_reason,
        # Without these a form reopening the report could not show which
        # qualities, products and stores it named, and saving would silently
        # blank them.
        "semolina_lines": [_serialize_semolina_line(line) for line in detail.semolina_lines],
        "raw_material_location_id": detail.raw_material_location_id,
        "regrind_input_quantity": detail.regrind_input_quantity,
        "regrind_input_product_id": detail.regrind_input_product_id,
        "regrind_product_id": detail.regrind_product_id,
        "mold_id": detail.mold_id,
        "waste_lines": [_serialize_waste_line(line) for line in detail.waste_lines],
    }


def _serialize_conditionnement_detail(detail: ConditionnementReportDetail) -> dict:
    return {
        "finished_product_quantity": detail.finished_product_quantity,
        "packets_counted": detail.packets_counted,
        "film_quantity": detail.film_quantity,
        "carton_quantity": detail.carton_quantity,
        "tape_quantity": detail.tape_quantity,
        "machine_speed": detail.machine_speed,
        "production_minutes": detail.production_minutes,
        "downtime_minutes": detail.downtime_minutes,
        "downtime_reason": detail.downtime_reason,
        "lot_number": detail.lot_number,
        "dlc_date": detail.dlc_date.isoformat() if detail.dlc_date is not None else None,
        "film_product_id": detail.film_product_id,
        "carton_product_id": detail.carton_product_id,
        "tape_product_id": detail.tape_product_id,
        "packaging_location_id": detail.packaging_location_id,
        "finished_goods_location_id": detail.finished_goods_location_id,
        "waste_lines": [_serialize_waste_line(line) for line in detail.waste_lines],
    }


def _serialize_report_with_detail(value: dict) -> dict:
    detail = value.get("detail")
    if isinstance(detail, ConditionnementReportDetail):
        serialized = _serialize_conditionnement_detail(detail)
    elif isinstance(detail, DailyReportDetail):
        serialized = _serialize_daily_detail(detail)
    else:
        serialized = None
    return {**_serialize_report(value["report"]), "detail": serialized}


# --- regrind defaults -------------------------------------------------------
#
# What the regrind of a given input yields. A daily report validating with
# rebroyat above zero opens its own regrind OF, which is impossible without this.


@router.get("/regrind-defaults")
def list_regrind_defaults(
    tenant: TenantContext = Depends(require_permission("production.view_regrind")),
) -> list[dict]:
    with get_connection() as connection:
        return RegrindDefaultsService(connection).list_defaults(tenant_id=tenant.tenant_id)


@router.put("/regrind-defaults")
def set_regrind_default(
    body: SetRegrindDefaultRequest,
    tenant: TenantContext = Depends(require_permission("production.manage_regrind")),
) -> dict:
    """Set the output product for one input, or the tenant default when input_product_id is omitted."""
    with get_connection() as connection:
        result = RegrindDefaultsService(connection).set_default(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            output_product_id=body.output_product_id,
            input_product_id=body.input_product_id,
        )
        if isinstance(result, Err):
            connection.rollback()
            raise HTTPException(status.HTTP_400_BAD_REQUEST, {"code": result.code, "message": result.message})
        connection.commit()
    return result.value
