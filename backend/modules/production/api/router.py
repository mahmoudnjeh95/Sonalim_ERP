from __future__ import annotations

import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel

from core.api.service import CoreService
from core.db import get_connection
from core.domain.result import Err
from core.tenancy import TenantContext, require_permission, require_session, user_has_permission
from modules.production.api.packaging_bom_service import PackagingBomService
from modules.production.api.resource_type_service import ResourceTypeService
from modules.production.api.product_classification_service import ProductClassificationService
from modules.production.api.work_order_overview_service import WorkOrderOverviewService
from modules.production.api.work_order_yield_service import WorkOrderYieldService
from modules.production.api.recipe_correlation_insight_service import (
    RecipeCorrelationInsightUnavailable,
    summarize_recipe_correlation,
)
from modules.production.api import ia_assistant_service
from modules.production.api.team_performance_service import GRAINS, TeamPerformanceService
from modules.production.api.machine_performance_service import MachinePerformanceService
from modules.production.api.consumption_report_service import CATEGORIES, ConsumptionReportService
from modules.production.api.consumption_report_export import build_consumption_workbook
from modules.production.api.daily_recap_export import build_daily_recap_workbook, fetch_period_rows, resolve_period
from modules.production.api.production_analytics_service import build_analytics_payload
from modules.production.api.report_period_service import list_validated_report_dates
from modules.procurement.api.service import PurchaseOrderService
from modules.maintenance.api.equipment_service import EquipmentService
from modules.production.domain.resource_type import ResourceType
from modules.production.domain.product_classification import ProductClassification
from modules.production.api.recipe_service import RecipeService
from modules.production.api.regrind_service import RegrindDefaultsService, RegrindService, ScrapService
from modules.production.api.of_consolidation_service import OfConsolidationService
from modules.production.api.dashboard_day_service import GRANULARITIES, DashboardDayService
from modules.production.api.day_sheet_service import DaySheetService
from modules.production.api.lot_suggestion_service import LotSuggestionService
from modules.production.api.shift_report_service import ShiftReportService
from modules.production.api.shift_validation_service import ShiftValidationService
from modules.production.domain.shift_report import SECTION_KEYS, permission_for_section
from modules.production.api.dashboard_lines_service import DashboardLinesService
from modules.production.api.dashboard_live_service import DashboardLiveService
from modules.production.api.stock_release_service import StockReleaseService
from modules.production.api.dashboard_settings_service import DashboardSettingsService
from modules.production.api.waste_type_service import WasteTypeService
from modules.production.domain.dashboard import ShiftWindow
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
    DowntimeLine,
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
    # Optional: who is responsible for this OF. Never required, unlike work_center_id.
    supervisor_id: str | None = None
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
    supervisor_id: str | None = None
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


class ReleaseStockItem(BaseModel):
    product_id: str
    quantity: float


class ReleaseStockRequest(BaseModel):
    day: datetime.date  # the day the goods were packed
    items: list[ReleaseStockItem]


class SetProductClassificationRequest(BaseModel):
    product_id: str
    category: str
    is_regrind: bool = False
    packaging_format: str | None = None
    is_water: bool = False
    packaging_kind: str | None = None


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


class DowntimeLineRequest(BaseModel):
    """One arrêt on a report: the motif, how long, an optional note.

    `motif` is optional here and required at submit-time only if the line
    records minutes -- see validate_downtime_lines. A team typing a draft may
    not have settled on wording yet.
    """

    motif: str | None = None
    downtime_type: str | None = None
    classification: str | None = None
    minutes: int = 0
    note: str | None = None

    def to_line(self, order: int) -> DowntimeLine:
        return DowntimeLine(
            motif=self.motif,
            downtime_type=self.downtime_type,
            classification=self.classification,
            minutes=self.minutes,
            note=self.note,
            line_order=order,
        )


def _downtime_lines(lines: list[DowntimeLineRequest]) -> tuple[DowntimeLine, ...]:
    """Order comes from the request order -- the shift's own, not a sort."""
    return tuple(line.to_line(order) for order, line in enumerate(lines))


def _serialize_downtime_line(line: DowntimeLine) -> dict:
    return {
        "motif": line.motif,
        "downtime_type": line.downtime_type,
        "classification": line.classification,
        "minutes": line.minutes,
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
    # Which fournisseur this shift's fioul came from -- informational only, see
    # DailyReportDetail.fuel_supplier_id.
    fuel_supplier_id: str | None = None
    # Gasoil (diesel) -- a separate fuel from fuel_quantity (fioul). Derived on
    # the frontend from gasoil_flow_rate x generator_hours.
    gasoil_quantity: float = 0
    gasoil_supplier_id: str | None = None
    # Groupe électrogène consumption rate (L/h) and hours run this shift --
    # the operator's real inputs; gasoil_quantity is their product.
    gasoil_flow_rate: float = 0
    generator_hours: float = 0
    electricity_quantity: float = 0
    # Débit de semoule: feed rate in tonnes/hour. Recorded only, for future
    # recipe statistics -- see PRODUCTION_RECIPE_STATISTICS_PLAN.md.
    semolina_flow_rate: float = 0
    start_time: datetime.time | None = None
    end_time: datetime.time | None = None
    production_minutes: int = 0
    # Arrêts, one line per stoppage -- a shift may stop more than once, for
    # more than one reason.
    downtime_lines: list[DowntimeLineRequest] = []
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
    # Déchets: raw_material, press, pouring, cross, kneading and
    # finished_product_conditioning stages only, one line per item lost.
    waste_lines: list[WasteLineRequest] = []

    def to_detail(self) -> DailyReportDetail:
        payload = self.model_dump()
        payload["waste_lines"] = _waste_lines(self.waste_lines)
        payload["semolina_lines"] = _semolina_lines(self.semolina_lines)
        payload["downtime_lines"] = _downtime_lines(self.downtime_lines)
        return DailyReportDetail(**payload)


class CreateDailyReportRequest(BaseModel):
    of_id: str
    report_date: datetime.date
    team: str | None = None
    work_center_id: str | None = None
    # Which machine within the work center ran this shift. Optional here (a
    # draft may be saved before the team knows) but required to submit — see
    # ProductionReportService.submit_report.
    equipment_id: str | None = None
    shift: str | None = None
    detail: DailyReportDetailRequest = DailyReportDetailRequest()


class UpdateDailyReportRequest(BaseModel):
    detail: DailyReportDetailRequest


class CorrectDailyReportRequest(BaseModel):
    detail: DailyReportDetailRequest
    reason: str
    # Past the REGRIND_DELTA_REQUIRES_NEW_ORDER refusal: confirms opening a new
    # rebroyat order for the difference when the corrected figure is higher than
    # what an already-closed regrind order ground. Mirrors DeleteReportRequest.force.
    force: bool = False


class RejectReportRequest(BaseModel):
    reason: str


class DeleteReportRequest(BaseModel):
    # Mandatory: the row is gone afterwards, so the audit entry is the only record
    # that it ever existed.
    reason: str
    # Past the REGRIND_ALREADY_COMPLETED refusal: also reverses the regrind
    # order's stock receipt and removes the order along with the report.
    force: bool = False


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
    # Part of carton_quantity that held no sellable product (empty/damaged
    # cartons). See ConditionnementReportDetail.waste_carton_quantity.
    waste_carton_quantity: float = 0
    tape_quantity: float = 0  # deprecated, superseded by scotch_quantity/ruban_quantity
    scotch_quantity: float = 0
    ruban_quantity: float = 0
    machine_speed: float | None = None
    production_minutes: int = 0
    downtime_minutes: int = 0
    downtime_reason: str | None = None
    downtime_note: str | None = None
    lot_number: str | None = None
    dlc_date: datetime.date | None = None
    film_product_id: str | None = None
    carton_product_id: str | None = None
    tape_product_id: str | None = None  # deprecated
    scotch_product_id: str | None = None
    ruban_product_id: str | None = None
    # Which fournisseur each packaging item came from -- informational only, see
    # ConditionnementReportDetail.film_supplier_id.
    film_supplier_id: str | None = None
    carton_supplier_id: str | None = None
    tape_supplier_id: str | None = None  # deprecated
    scotch_supplier_id: str | None = None
    ruban_supplier_id: str | None = None
    packaging_location_id: str | None = None
    finished_goods_location_id: str | None = None
    # The daily report whose output this run packaged. Optional -- see the
    # field's docstring on ConditionnementReportDetail.
    daily_report_id: str | None = None
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
    # Which machine within the work center ran this shift. Optional here, same
    # as the daily report, and required to submit for the same reason.
    equipment_id: str | None = None
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
            supervisor_id=body.supervisor_id,
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


@router.get("/work-orders/supervisors")
def list_work_order_supervisors(
    tenant: TenantContext = Depends(require_permission("production.view_work_orders")),
) -> list[dict]:
    """Users with the Production role -- who can be named an OF's supervisor."""
    with get_connection() as connection:
        return WorkOrderService(connection).list_supervisor_options(tenant_id=tenant.tenant_id)


@router.get("/work-orders/yields")
def list_work_order_yields(
    tenant: TenantContext = Depends(require_permission("production.view_work_orders")),
) -> list[dict]:
    with get_connection() as connection:
        return WorkOrderYieldService(connection).list_work_order_yields(tenant.tenant_id)


@router.get("/work-orders/overview")
def get_work_orders_overview(
    date: datetime.date | None = Query(default=None, description="Plant-local date. Defaults to the server's."),
    at: datetime.time | None = Query(default=None, description="Plant-local clock time, HH:MM. Defaults to the server's."),
    tenant: TenantContext = Depends(require_permission("production.view_work_orders")),
) -> list[dict]:
    """One light row per OF for the list: products, produced tonnes, shift counts, pending tonnes, live."""
    now = datetime.datetime.now()
    with get_connection() as connection:
        return WorkOrderOverviewService(connection).overview(
            tenant_id=tenant.tenant_id, date=date or now.date(), at=at or now.time().replace(second=0, microsecond=0)
        )


@router.get("/work-orders/recipe-correlation")
def list_recipe_correlation(
    tenant: TenantContext = Depends(require_permission("production.view_work_orders")),
) -> list[dict]:
    """Each shift's water dosage and flow rate, against its OF's yield."""
    with get_connection() as connection:
        return WorkOrderYieldService(connection).list_recipe_correlation(tenant_id=tenant.tenant_id)


@router.get("/work-orders/recipe-correlation/insight")
def get_recipe_correlation_insight(
    locale: str = "fr",
    tenant: TenantContext = Depends(require_permission("production.view_work_orders")),
) -> dict:
    """A generated one-sentence reading of the same figures `list_recipe_correlation`
    returns. Never raises for a missing key, a network error or an empty data set --
    `available: false` just means the card shows nothing, the same way an OF with no
    validated semoule shows no yield rather than an error."""
    with get_connection() as connection:
        rows = WorkOrderYieldService(connection).list_recipe_correlation(tenant_id=tenant.tenant_id)
    try:
        text = summarize_recipe_correlation(rows, locale=locale)
    except RecipeCorrelationInsightUnavailable:
        return {"available": False, "text": None}
    return {"available": True, "text": text}


class SendIaAssistantMessageRequest(BaseModel):
    content: str
    locale: str = "fr"


@router.get("/ia-assistant/conversations")
def list_ia_assistant_conversations(
    tenant: TenantContext = Depends(require_permission("production.use_ia_assistant")),
) -> list[dict]:
    """Only this user's own conversations, in this tenant -- never another user's,
    even to an admin. See ia_assistant_service's module docstring."""
    with get_connection() as connection:
        return ia_assistant_service.list_conversations(connection, tenant_id=tenant.tenant_id, user_id=tenant.user_id)


@router.post("/ia-assistant/conversations", status_code=status.HTTP_201_CREATED)
def create_ia_assistant_conversation(
    tenant: TenantContext = Depends(require_permission("production.use_ia_assistant")),
) -> dict:
    with get_connection() as connection:
        conversation = ia_assistant_service.create_conversation(connection, tenant_id=tenant.tenant_id, user_id=tenant.user_id)
        connection.commit()
    return conversation


@router.delete("/ia-assistant/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def delete_ia_assistant_conversation(
    conversation_id: str,
    tenant: TenantContext = Depends(require_permission("production.use_ia_assistant")),
) -> None:
    with get_connection() as connection:
        try:
            ia_assistant_service.delete_conversation(
                connection, tenant_id=tenant.tenant_id, user_id=tenant.user_id, conversation_id=conversation_id
            )
        except ia_assistant_service.IaAssistantNotFound:
            connection.rollback()
            raise HTTPException(status.HTTP_404_NOT_FOUND, {"code": "NOT_FOUND", "message": f"conversation {conversation_id} not found"})
        connection.commit()


@router.get("/ia-assistant/conversations/{conversation_id}/messages")
def list_ia_assistant_messages(
    conversation_id: str,
    tenant: TenantContext = Depends(require_permission("production.use_ia_assistant")),
) -> list[dict]:
    with get_connection() as connection:
        try:
            return ia_assistant_service.list_messages(
                connection, tenant_id=tenant.tenant_id, user_id=tenant.user_id, conversation_id=conversation_id
            )
        except ia_assistant_service.IaAssistantNotFound:
            raise HTTPException(status.HTTP_404_NOT_FOUND, {"code": "NOT_FOUND", "message": f"conversation {conversation_id} not found"})


@router.post("/ia-assistant/conversations/{conversation_id}/messages", status_code=status.HTTP_201_CREATED)
def send_ia_assistant_message(
    conversation_id: str,
    body: SendIaAssistantMessageRequest,
    tenant: TenantContext = Depends(require_permission("production.use_ia_assistant")),
) -> dict:
    """Runs the Groq tool-calling loop and persists the exchange. Never a bare
    500: a missing key/network failure surfaces as 503 (available: false upstream
    in the UI), a day's quota hit as 429 -- both are expected operating states for
    a free-tier assistant, not bugs."""
    with get_connection() as connection:
        try:
            reply = ia_assistant_service.send_message(
                connection,
                tenant_id=tenant.tenant_id,
                user_id=tenant.user_id,
                conversation_id=conversation_id,
                user_text=body.content,
                locale=body.locale,
            )
        except ia_assistant_service.IaAssistantNotFound:
            connection.rollback()
            raise HTTPException(status.HTTP_404_NOT_FOUND, {"code": "NOT_FOUND", "message": f"conversation {conversation_id} not found"})
        except ia_assistant_service.IaAssistantRateLimited as exc:
            connection.rollback()
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, {"code": "RATE_LIMITED", "message": str(exc)})
        except ia_assistant_service.IaAssistantUnavailable as exc:
            connection.rollback()
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, {"code": "UNAVAILABLE", "message": str(exc)})
        connection.commit()
    return reply


@router.get("/work-orders/active-consolidations")
def list_active_consolidations(
    tenant: TenantContext = Depends(require_permission("production.view_work_orders")),
) -> list[dict]:
    """Consolidation of every ongoing or suspended OF, each with the teams that filed its validated reports."""
    with get_connection() as connection:
        return OfConsolidationService(connection).consolidate_active(tenant_id=tenant.tenant_id)


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
            supervisor_id=body.supervisor_id,
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
            packaging_kind=body.packaging_kind,
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
        "supervisor_id": order.supervisor_id,
        "recipe_id": order.recipe_id,
        "packaging_bom_id": order.packaging_bom_id,
        "start_date": order.start_date.isoformat() if order.start_date is not None else None,
        "product_type": order.product_type,
        "notes": order.notes,
        "created_by": order.created_by,
        "closed_at": order.closed_at.isoformat() if order.closed_at is not None else None,
        "closed_by": order.closed_by,
        "is_regrind": order.is_regrind,
    }


def _serialize_classification(classification: ProductClassification) -> dict:
    return {
        "product_id": classification.product_id,
        "category": classification.category,
        "is_regrind": classification.is_regrind,
        "packaging_format": classification.packaging_format,
        "is_water": classification.is_water,
        "packaging_kind": classification.packaging_kind,
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


@router.get("/machines")
def list_machines(
    work_center_id: str | None = None,
    tenant: TenantContext = Depends(require_permission("production.view_reports")),
) -> list[dict]:
    """Machines a report can be attributed to -- every one tenant-wide, or one
    line's, when `work_center_id` narrows it (e.g. filling a report's machine
    field, where only the OF's own line's machines are offered).

    A thin pass-through into maintenance's own EquipmentService (an in-process
    call to its public API, the same pattern report_stock_service uses to call
    warehouse), gated by a production permission -- so a floor user filing or
    reading a report is never also required to hold maintenance.view_equipment
    just to see which machine ran it.
    """
    with get_connection() as connection:
        equipment = EquipmentService(connection).list_equipment(tenant_id=tenant.tenant_id, work_center_id=work_center_id)
    return [{"id": e.id, "code": e.code, "name": e.name, "status": e.status} for e in equipment]


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


@router.get("/recipes/drift-summary")
def list_recipe_drift_summary(
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    tenant: TenantContext = Depends(require_permission("production.view_work_orders")),
) -> list[dict]:
    """How often each recipe's OFs trip a hard or soft recipe-check finding.

    Registered before /recipes/{recipe_id} -- "drift-summary" would otherwise
    match that path param.
    """
    with get_connection() as connection:
        return RecipeCheckService(connection).list_recipe_drift(
            tenant_id=tenant.tenant_id, date_from=date_from, date_to=date_to
        )


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
        "regrind_work_order_id": scrap.regrind_work_order_id,
    }


def _serialize_regrind_batch(batch: dict) -> dict:
    return {
        "work_order": _serialize_work_order(batch["work_order"]),
        "scrap_record_ids": batch["scrap_record_ids"],
        "scrap_inputs": batch["scrap_inputs"],
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
        "REGRIND_STOCK_MOVE_NOT_FOUND",
        "REGRIND_DELTA_REQUIRES_NEW_ORDER",
        "REGRIND_MULTIPLE_CLOSED_BATCHES",
        "EMPTY_SECTION",
        "DUPLICATE_ROW",
        "CHANGED_SINCE_OPENED",
        "OPEN_STOP",
        "NOTHING_TO_VALIDATE",
        "ALREADY_POSTED",
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
            equipment_id=body.equipment_id,
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


@router.get("/reports/machine-performance")
def list_machine_performance(
    grain: str = Query(default="week"),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    tenant: TenantContext = Depends(require_permission("production.view_reports")),
) -> list[dict]:
    """Output, time and downtime from validated reports, bucketed by machine and period.

    Rows are keyed by equipment_id, an opaque reference into maintenance's own
    schema -- resolve it to a machine's code/name via
    GET /production/work-centers/{id}/machines or GET /maintenance/equipment.
    """
    if grain not in GRAINS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            {"code": "INVALID_GRAIN", "message": f"grain must be one of {GRAINS}"},
        )
    with get_connection() as connection:
        return MachinePerformanceService(connection).list_machine_performance(
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


@router.get("/reports/downtime-breakdown")
def list_downtime_breakdown(
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    tenant: TenantContext = Depends(require_permission("production.view_reports")),
) -> list[dict]:
    """Minutes lost per reason, team and machine, from validated reports."""
    with get_connection() as connection:
        return TeamPerformanceService(connection).list_downtime_breakdown(
            tenant_id=tenant.tenant_id, date_from=date_from, date_to=date_to
        )


def _validate_consumption_category(category: str | None) -> None:
    if category is not None and category not in CATEGORIES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            {"code": "INVALID_CATEGORY", "message": f"category must be one of {CATEGORIES}"},
        )


@router.get("/reports/consumption-by-supplier")
def list_consumption_by_supplier(
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    category: str | None = Query(default=None),
    tenant: TenantContext = Depends(require_permission("production.view_reports")),
) -> list[dict]:
    """Monthly film/carton/scotch/ruban/gasoil/fuel consumption, grouped by
    category, month, PC/PL and fournisseur -- see ConsumptionReportService."""
    _validate_consumption_category(category)
    with get_connection() as connection:
        return ConsumptionReportService(connection).list_monthly_consumption_by_supplier(
            tenant_id=tenant.tenant_id, date_from=date_from, date_to=date_to, category=category
        )


@router.get("/reports/consumption-by-supplier/export")
def export_consumption_by_supplier(
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    category: str | None = Query(default=None),
    tenant: TenantContext = Depends(require_permission("production.view_reports")),
) -> Response:
    """Same data as list_consumption_by_supplier, laid out as the .xlsx workbook
    that replaces the plant's hand-built monthly spreadsheets."""
    _validate_consumption_category(category)
    with get_connection() as connection:
        rows = ConsumptionReportService(connection).list_monthly_consumption_by_supplier(
            tenant_id=tenant.tenant_id, date_from=date_from, date_to=date_to, category=category
        )
        core_service = CoreService(connection)
        product_names = {p.id: p.name for p in core_service.list_products(tenant.tenant_id)}
        supplier_names = {p.id: p.name for p in core_service.list_partners(tenant_id=tenant.tenant_id)}

    content = build_consumption_workbook(rows, product_names=product_names, supplier_names=supplier_names)
    filename = f"consommation-{date_from or 'debut'}-{date_to or 'fin'}.xlsx"
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/reports/daily-recap/export")
def export_daily_recap(
    date: str = Query(...),
    period: str = Query(default="day"),
    tenant: TenantContext = Depends(require_permission("production.view_reports")),
) -> Response:
    """The plant's monthly "Sonali rapport général" workbook, scoped to a day,
    an ISO week or a calendar month (see `period`, anchored on `date`):
    produit fini, consommation MP/film/carton/rub&scotch/gasoil/fuel, coût
    unitaire, achats MP/film/carton, charges fixes (manual) and the blended
    coût de production/tonne -- see daily_recap_export.py. For week/month,
    every validated-production day in the range also gets its own
    "CP <date>" sheet, and the period-total "Coût de production" sheet's
    charges term sums to what those days' sheets show together."""
    if period not in ("day", "week", "month"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, {"code": "INVALID_PERIOD", "message": "period must be one of 'day', 'week', 'month'"})

    date_from, date_to, period_phrase, period_days = resolve_period(period, date)

    with get_connection() as connection:
        receipt_lines = PurchaseOrderService(connection).list_confirmed_receipt_line_details(tenant_id=tenant.tenant_id)
        mp_rows, packaging_rows, finished_goods_rows = fetch_period_rows(
            connection, tenant_id=tenant.tenant_id, date_from=date_from, date_to=date_to, receipt_lines=receipt_lines
        )

        core_service = CoreService(connection)
        product_names = {p.id: p.name for p in core_service.list_products(tenant.tenant_id)}
        supplier_names = {p.id: p.name for p in core_service.list_partners(tenant_id=tenant.tenant_id)}

        daily_breakdowns = []
        if period != "day":
            days_with_data = list_validated_report_dates(connection, tenant_id=tenant.tenant_id, date_from=date_from, date_to=date_to)
            for day in days_with_data:
                day_mp_rows, day_packaging_rows, day_finished_goods_rows = fetch_period_rows(
                    connection, tenant_id=tenant.tenant_id, date_from=day, date_to=day, receipt_lines=receipt_lines
                )
                daily_breakdowns.append({
                    "date": day, "mp_rows": day_mp_rows, "packaging_rows": day_packaging_rows,
                    "finished_goods_rows": day_finished_goods_rows,
                })

    mp_product_ids = {r["product_id"] for r in mp_rows if r["product_id"]}
    film_product_ids = {r["product_id"] for r in packaging_rows if r["category"] == "film" and r["product_id"]}
    carton_product_ids = {r["product_id"] for r in packaging_rows if r["category"] == "carton" and r["product_id"]}

    content = build_daily_recap_workbook(
        period_phrase=period_phrase, period_days=period_days,
        mp_rows=mp_rows, packaging_rows=packaging_rows, finished_goods_rows=finished_goods_rows,
        receipt_lines=receipt_lines, mp_product_ids=mp_product_ids, film_product_ids=film_product_ids,
        carton_product_ids=carton_product_ids, product_names=product_names, supplier_names=supplier_names,
        daily_breakdowns=daily_breakdowns,
    )
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="recap-{period}-{date_from}-{date_to}.xlsx"'},
    )


@router.get("/reports/daily-recap/analytics")
def get_daily_recap_analytics(
    date: str = Query(...),
    period: str = Query(default="day"),
    tenant: TenantContext = Depends(require_permission("production.view_reports")),
) -> dict:
    """The always-on charts/tables view behind the Production recap tab: the
    selected period's own MP/emballage cost and tonnage, a trailing trend of
    the same shape (30 days / 12 weeks / 12 months depending on `period`),
    and purchase-cost anomalies -- see production_analytics_service.py.
    Unlike /reports/daily-recap/export, this never includes fixed charges
    (those stay hand-entered in the exported workbook only)."""
    if period not in ("day", "week", "month"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, {"code": "INVALID_PERIOD", "message": "period must be one of 'day', 'week', 'month'"})

    with get_connection() as connection:
        return build_analytics_payload(connection, tenant_id=tenant.tenant_id, period=period, date=date)


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
            equipment_id=body.equipment_id,
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
            force=body.force,
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
            force=body.force,
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
        "equipment_id": report.equipment_id,
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
        "fuel_supplier_id": detail.fuel_supplier_id,
        "gasoil_quantity": detail.gasoil_quantity,
        "gasoil_supplier_id": detail.gasoil_supplier_id,
        "gasoil_flow_rate": detail.gasoil_flow_rate,
        "generator_hours": detail.generator_hours,
        "electricity_quantity": detail.electricity_quantity,
        "semolina_flow_rate": detail.semolina_flow_rate,
        "start_time": detail.start_time.isoformat() if detail.start_time is not None else None,
        "end_time": detail.end_time.isoformat() if detail.end_time is not None else None,
        "production_minutes": detail.production_minutes,
        "downtime_lines": [_serialize_downtime_line(line) for line in detail.downtime_lines],
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
        "waste_carton_quantity": detail.waste_carton_quantity,
        "tape_quantity": detail.tape_quantity,
        "scotch_quantity": detail.scotch_quantity,
        "ruban_quantity": detail.ruban_quantity,
        "machine_speed": detail.machine_speed,
        "production_minutes": detail.production_minutes,
        "downtime_minutes": detail.downtime_minutes,
        "downtime_reason": detail.downtime_reason,
        "downtime_note": detail.downtime_note,
        "lot_number": detail.lot_number,
        "dlc_date": detail.dlc_date.isoformat() if detail.dlc_date is not None else None,
        "film_product_id": detail.film_product_id,
        "carton_product_id": detail.carton_product_id,
        "tape_product_id": detail.tape_product_id,
        "scotch_product_id": detail.scotch_product_id,
        "ruban_product_id": detail.ruban_product_id,
        "film_supplier_id": detail.film_supplier_id,
        "carton_supplier_id": detail.carton_supplier_id,
        "tape_supplier_id": detail.tape_supplier_id,
        "scotch_supplier_id": detail.scotch_supplier_id,
        "ruban_supplier_id": detail.ruban_supplier_id,
        "packaging_location_id": detail.packaging_location_id,
        "finished_goods_location_id": detail.finished_goods_location_id,
        "daily_report_id": detail.daily_report_id,
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


# --- waste types ------------------------------------------------------------
#
# The déchet kinds a plant adds to the built-in ones: a name, and the report the
# entry belongs to. See waste_type_service.py.


class CreateWasteTypeRequest(BaseModel):
    name: str
    report_type: str
    sort_order: int = 0


class UpdateWasteTypeRequest(BaseModel):
    name: str | None = None
    sort_order: int | None = None
    is_active: bool | None = None


def _waste_type_result(connection, result) -> dict:
    if isinstance(result, Err):
        connection.rollback()
        code = (
            status.HTTP_404_NOT_FOUND
            if result.code == "NOT_FOUND"
            else status.HTTP_409_CONFLICT
            if result.code == "DUPLICATE_WASTE_TYPE"
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(code, {"code": result.code, "message": result.message})
    connection.commit()
    return result.value


@router.get("/waste-types")
def list_waste_types(
    report_type: str | None = None,
    include_inactive: bool = True,
    # Anyone who can read a report needs the names to read its déchets.
    tenant: TenantContext = Depends(require_permission("production.view_reports")),
) -> list[dict]:
    with get_connection() as connection:
        return WasteTypeService(connection).list_types(
            tenant_id=tenant.tenant_id, report_type=report_type, include_inactive=include_inactive
        )


@router.post("/waste-types", status_code=status.HTTP_201_CREATED)
def create_waste_type(
    body: CreateWasteTypeRequest,
    tenant: TenantContext = Depends(require_permission("production.manage_waste_types")),
) -> dict:
    with get_connection() as connection:
        result = WasteTypeService(connection).create_type(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            name=body.name,
            report_type=body.report_type,
            sort_order=body.sort_order,
        )
        return _waste_type_result(connection, result)


@router.patch("/waste-types/{waste_type_id}")
def update_waste_type(
    waste_type_id: str,
    body: UpdateWasteTypeRequest,
    tenant: TenantContext = Depends(require_permission("production.manage_waste_types")),
) -> dict:
    with get_connection() as connection:
        result = WasteTypeService(connection).update_type(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            waste_type_id=waste_type_id,
            name=body.name,
            sort_order=body.sort_order,
            is_active=body.is_active,
        )
        return _waste_type_result(connection, result)


# --- dashboard settings -----------------------------------------------------
#
# What the production dashboard is configured with: the clock times of each
# shift, which team works which shift on which line, which stage each machine
# belongs to, and which stores hold finished product before and after its
# release. Each list is replaced as a whole. See dashboard_settings_service.py.


class ShiftWindowRequest(BaseModel):
    shift: str
    start_time: datetime.time
    end_time: datetime.time


class ReplaceShiftWindowsRequest(BaseModel):
    items: list[ShiftWindowRequest]


class TeamRotationEntryRequest(BaseModel):
    team: str
    anchor_date: datetime.date
    anchor_stop: int


class ReplaceTeamRotationRequest(BaseModel):
    items: list[TeamRotationEntryRequest]


class StoreRoleRequest(BaseModel):
    location_id: str
    role: str


class ReplaceStoreRolesRequest(BaseModel):
    items: list[StoreRoleRequest]


def _settings_result(connection, result) -> list[dict]:
    if isinstance(result, Err):
        connection.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, {"code": result.code, "message": result.message})
    connection.commit()
    return result.value


@router.get("/dashboard/settings")
def get_dashboard_settings(
    tenant: TenantContext = Depends(require_permission("production.view_reports")),
) -> dict:
    with get_connection() as connection:
        return DashboardSettingsService(connection).get_settings(tenant_id=tenant.tenant_id)


@router.put("/dashboard/settings/shift-windows")
def replace_shift_windows(
    body: ReplaceShiftWindowsRequest,
    tenant: TenantContext = Depends(require_permission("production.manage_dashboard_settings")),
) -> list[dict]:
    with get_connection() as connection:
        result = DashboardSettingsService(connection).replace_shift_windows(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            windows=[ShiftWindow(shift=i.shift, start=i.start_time, end=i.end_time) for i in body.items],
        )
        return _settings_result(connection, result)


@router.put("/dashboard/settings/team-rotation")
def replace_team_rotation(
    body: ReplaceTeamRotationRequest,
    tenant: TenantContext = Depends(require_permission("production.manage_dashboard_settings")),
) -> list[dict]:
    with get_connection() as connection:
        result = DashboardSettingsService(connection).replace_team_rotation(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            entries=[{"team": i.team, "anchor_date": i.anchor_date.isoformat(), "anchor_stop": i.anchor_stop} for i in body.items],
        )
        return _settings_result(connection, result)


@router.put("/dashboard/settings/store-roles")
def replace_store_roles(
    body: ReplaceStoreRolesRequest,
    tenant: TenantContext = Depends(require_permission("production.manage_dashboard_settings")),
) -> list[dict]:
    with get_connection() as connection:
        result = DashboardSettingsService(connection).replace_store_roles(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, entries=[i.model_dump() for i in body.items]
        )
        return _settings_result(connection, result)


@router.get("/dashboard/lines")
def get_dashboard_lines(
    at: datetime.time | None = Query(default=None, description="Plant-local clock time, HH:MM. Defaults to the server's."),
    date: datetime.date | None = Query(default=None, description="Which day's board to show. Defaults to the server's today."),
    tenant: TenantContext = Depends(require_permission("production.view_work_orders")),
) -> dict:
    """The live board: each line with the OFs open on it, every machine declared
    on it (with its stage once the plant has set one), and the 4-team rotation
    for `date`, each team's slot coloured by that line's shift report."""
    with get_connection() as connection:
        today = datetime.date.today()
        return DashboardLinesService(connection).get_lines(
            tenant_id=tenant.tenant_id,
            at=at or datetime.datetime.now().time().replace(second=0, microsecond=0),
            date=date or today,
            today=today,
        )


@router.get("/dashboard/day")
def get_dashboard_day(
    date: datetime.date = Query(...),
    tenant: TenantContext = Depends(require_permission("production.view_reports")),
) -> dict:
    """One day's production from validated reports: totals against the previous
    day, each OF cut by shift and team, and where déchets and stops came from."""
    with get_connection() as connection:
        return DashboardDayService(connection).get_day(tenant_id=tenant.tenant_id, date=date)


@router.get("/dashboard/live")
def get_dashboard_live(
    date: datetime.date | None = Query(default=None, description="Plant-local date. Defaults to the server's."),
    at: datetime.time | None = Query(default=None, description="Plant-local clock time, HH:MM. Defaults to the server's."),
    tenant: TenantContext = Depends(require_permission("production.view_reports")),
) -> dict:
    """The shift running on each line right now, from what its team has entered or handed in and
    nobody has validated yet. Shown apart on the board and never added to the day's validated
    totals."""
    now = datetime.datetime.now()
    with get_connection() as connection:
        return DashboardLiveService(connection).get_live(
            tenant_id=tenant.tenant_id, date=date or now.date(), at=at or now.time().replace(second=0, microsecond=0)
        )


@router.get("/stock-release")
def get_stock_release(
    day: datetime.date | None = Query(default=None, description="The day the goods were packed. Defaults to yesterday, or today when nothing from yesterday can be released."),
    tenant: TenantContext = Depends(require_permission("production.release_stock")),
) -> dict:
    """The products packed on a day, what has already been released and what the line store still holds."""
    with get_connection() as connection:
        return StockReleaseService(connection).get_release_list(tenant_id=tenant.tenant_id, day=day)


@router.post("/stock-release")
def release_stock(
    body: ReleaseStockRequest, tenant: TenantContext = Depends(require_permission("production.release_stock"))
) -> dict:
    """Move packed goods from the line store to each product's own store, all or nothing."""
    with get_connection() as connection:
        result = StockReleaseService(connection).release(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, day=body.day, items=[item.model_dump() for item in body.items]
        )
        if isinstance(result, Err):
            connection.rollback()
            raise HTTPException(status.HTTP_400_BAD_REQUEST, {"code": result.code, "message": result.message})
        connection.commit()
    return result.value


@router.get("/day-sheet")
def get_day_sheet(
    date: datetime.date = Query(...),
    work_center_id: str = Query(...),
    include_pending: bool = Query(default=False),
    tenant: TenantContext = Depends(require_permission("production.view_reports")),
) -> dict:
    """One line's Daily and Conditionnement reports for a day on one grid, the way the
    plant's Excel day sheet lays them out: a column per shift and a total. Validated
    reports only unless `include_pending`, which adds the ones still being filled in."""
    with get_connection() as connection:
        result = DaySheetService(connection).get_day_sheet(
            tenant_id=tenant.tenant_id, date=date, work_center_id=work_center_id, include_pending=include_pending
        )
    if isinstance(result, Err):
        raise HTTPException(status.HTTP_404_NOT_FOUND, {"code": result.code, "message": result.message})
    return result.value


@router.get("/month-recap")
def get_month_recap(
    month: str = Query(..., pattern=r"^\d{4}-(0[1-9]|1[0-2])$", description="YYYY-MM"),
    work_center_id: str = Query(...),
    tenant: TenantContext = Depends(require_permission("production.view_reports")),
) -> dict:
    """A line's month on the same rows as the day sheet, every validated Daily and
    Conditionnement report added up, with a column per product produced."""
    with get_connection() as connection:
        result = DaySheetService(connection).get_month_recap(
            tenant_id=tenant.tenant_id, month=datetime.date.fromisoformat(f"{month}-01"), work_center_id=work_center_id
        )
    if isinstance(result, Err):
        raise HTTPException(status.HTTP_404_NOT_FOUND, {"code": result.code, "message": result.message})
    return result.value


@router.get("/lot-suggestion")
def get_lot_suggestion(
    work_center_id: str = Query(...),
    report_date: datetime.date = Query(...),
    tenant: TenantContext = Depends(require_permission("production.view_reports")),
) -> dict:
    """The lot number a packing report on this line and day most likely carries: the line's
    last lot counted on by the days since. Only ever a suggestion -- the form fills it in and
    the team can type another."""
    with get_connection() as connection:
        return LotSuggestionService(connection).suggest(
            tenant_id=tenant.tenant_id, work_center_id=work_center_id, report_date=report_date
        )


@router.get("/dashboard/trend")
def get_dashboard_trend(
    date_from: datetime.date = Query(...),
    date_to: datetime.date = Query(...),
    granularity: str = Query(default="day"),
    tenant: TenantContext = Depends(require_permission("production.view_reports")),
) -> dict:
    """Semoule poured (rebroyat included) and finished product, for the period
    and for the equal-length period just before it, bucketed by shift, day,
    week or month. A bucket nobody reported on is null, not zero."""
    if granularity not in GRANULARITIES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            {"code": "INVALID_GRANULARITY", "message": f"granularity must be one of {GRANULARITIES}"},
        )
    if date_from > date_to:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            {"code": "INVALID_PERIOD", "message": "date_from cannot be after date_to"},
        )
    with get_connection() as connection:
        return DashboardDayService(connection).get_trend(
            tenant_id=tenant.tenant_id, date_from=date_from, date_to=date_to, granularity=granularity
        )


# --- shift reports ----------------------------------------------------------
#
# One report per line, date and shift, filled section by section. Reading needs
# production.shift.view. Changing a section needs that section's own edit right
# (production.shift.edit.<section>), so the team that owns the packing table is not
# the team that can edit the production runs; roles bundle these same permissions.


class OpenShiftRequest(BaseModel):
    work_center_id: str
    report_date: datetime.date
    shift: str
    team: str | None = None


class UpdateShiftHeaderRequest(BaseModel):
    team: str | None = None
    conducteur: str | None = None
    agent_fabrication: str | None = None
    machiniste: str | None = None
    aide_machiniste: str | None = None


class SaveShiftSectionRequest(BaseModel):
    payload: dict
    reason: str | None = None


def _forbidden(permission: str) -> HTTPException:
    return HTTPException(
        status.HTTP_403_FORBIDDEN, {"code": "FORBIDDEN", "message": f"missing permission: {permission}"}
    )


def _require_section_edit(section_key: str, tenant: TenantContext = Depends(require_session)) -> TenantContext:
    """The caller must be allowed to edit this section, which is named in the URL."""
    if section_key not in SECTION_KEYS:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, {"code": "INVALID_SECTION", "message": f"unknown section {section_key!r}"}
        )
    permission = permission_for_section(section_key)
    with get_connection() as connection:
        if not user_has_permission(connection, user_id=tenant.user_id, permission=permission):
            raise _forbidden(permission)
    return tenant


def _require_any_shift_edit(tenant: TenantContext = Depends(require_session)) -> TenantContext:
    """Opening a shift or filling its header is open to anyone who can edit some section."""
    with get_connection() as connection:
        if not any(
            user_has_permission(connection, user_id=tenant.user_id, permission=permission_for_section(key))
            for key in SECTION_KEYS
        ):
            raise _forbidden("production.shift.edit.<section>")
    return tenant


def _shift_result(connection, result):
    if isinstance(result, Err):
        connection.rollback()
        raise HTTPException(_report_err_status(result.code), {"code": result.code, "message": result.message})
    connection.commit()
    return result.value


@router.get("/shift-reports")
def list_shift_reports(
    report_date: datetime.date | None = None,
    work_center_id: str | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    of_id: str | None = Query(default=None, description="Only the shifts that worked on this work order."),
    tenant: TenantContext = Depends(require_permission("production.shift.view")),
) -> list[dict]:
    with get_connection() as connection:
        return ShiftReportService(connection).list_shifts(
            tenant_id=tenant.tenant_id,
            report_date=report_date,
            work_center_id=work_center_id,
            status=status_filter,
            of_id=of_id,
        )


@router.post("/shift-reports", status_code=status.HTTP_201_CREATED)
def open_shift_report(body: OpenShiftRequest, tenant: TenantContext = Depends(_require_any_shift_edit)) -> dict:
    with get_connection() as connection:
        result = ShiftReportService(connection).open_shift(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            work_center_id=body.work_center_id,
            report_date=body.report_date,
            shift=body.shift,
            team=body.team,
        )
        return _shift_result(connection, result)


@router.get("/shift-reports/{shift_report_id}")
def get_shift_report(
    shift_report_id: str, tenant: TenantContext = Depends(require_permission("production.shift.view"))
) -> dict:
    with get_connection() as connection:
        return _shift_result(
            connection, ShiftReportService(connection).get_shift(tenant_id=tenant.tenant_id, shift_report_id=shift_report_id)
        )


@router.patch("/shift-reports/{shift_report_id}/header")
def update_shift_report_header(
    shift_report_id: str,
    body: UpdateShiftHeaderRequest,
    tenant: TenantContext = Depends(_require_any_shift_edit),
) -> dict:
    with get_connection() as connection:
        result = ShiftReportService(connection).update_header(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            shift_report_id=shift_report_id,
            fields=body.model_dump(exclude_unset=True),
        )
        return _shift_result(connection, result)


@router.put("/shift-reports/{shift_report_id}/sections/{section_key}")
def save_shift_report_section(
    shift_report_id: str,
    section_key: str,
    body: SaveShiftSectionRequest,
    tenant: TenantContext = Depends(_require_section_edit),
) -> dict:
    with get_connection() as connection:
        result = ShiftReportService(connection).save_section(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            shift_report_id=shift_report_id,
            section_key=section_key,
            payload=body.payload,
            reason=body.reason,
        )
        return _shift_result(connection, result)


@router.post("/shift-reports/{shift_report_id}/sections/{section_key}/submit")
def submit_shift_report_section(
    shift_report_id: str, section_key: str, tenant: TenantContext = Depends(_require_section_edit)
) -> dict:
    with get_connection() as connection:
        result = ShiftReportService(connection).submit_section(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, shift_report_id=shift_report_id, section_key=section_key
        )
        return _shift_result(connection, result)


class ValidatorEditSectionRequest(BaseModel):
    payload: dict
    reason: str


@router.put("/shift-reports/{shift_report_id}/sections/{section_key}/validator-edit")
def validator_edit_shift_report_section(
    shift_report_id: str,
    section_key: str,
    body: ValidatorEditSectionRequest,
    tenant: TenantContext = Depends(require_permission("production.shift.validate")),
) -> dict:
    with get_connection() as connection:
        result = ShiftValidationService(connection).edit_section_as_validator(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            shift_report_id=shift_report_id,
            section_key=section_key,
            payload=body.payload,
            reason=body.reason,
        )
        return _shift_result(connection, result)


@router.post("/shift-reports/{shift_report_id}/sections/{section_key}/nothing-to-report")
def declare_shift_report_section_empty(
    shift_report_id: str, section_key: str, tenant: TenantContext = Depends(_require_section_edit)
) -> dict:
    with get_connection() as connection:
        result = ShiftReportService(connection).declare_nothing(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, shift_report_id=shift_report_id, section_key=section_key
        )
        return _shift_result(connection, result)


@router.get("/shift-reports/{shift_report_id}/sections/{section_key}/revisions")
def list_shift_report_section_revisions(
    shift_report_id: str,
    section_key: str,
    tenant: TenantContext = Depends(require_permission("production.shift.view")),
) -> list[dict]:
    with get_connection() as connection:
        return _shift_result(
            connection,
            ShiftReportService(connection).list_revisions(
                tenant_id=tenant.tenant_id, shift_report_id=shift_report_id, section_key=section_key
            ),
        )


# --- validating a shift -------------------------------------------------------
#
# One approval for the whole shift. Approving and rejecting need
# production.shift.validate; undoing a validated shift is rarer and heavier, so it
# needs production.admin_reports, the same right that lets a supervisor correct or
# delete a report.


class ValidateShiftRequest(BaseModel):
    # What the validator's screen showed (section key -> revision). If any moved on,
    # validation is refused so nothing is approved unseen.
    seen_revisions: dict[str, int] | None = None
    shortfall_comment: str | None = None
    regrind_work_center_id: str | None = None


class RejectShiftSectionsRequest(BaseModel):
    sections: list[str]
    reason: str


class ReverseShiftRequest(BaseModel):
    reason: str
    force: bool = False


@router.post("/shift-reports/{shift_report_id}/validate")
def validate_shift_report(
    shift_report_id: str,
    body: ValidateShiftRequest,
    tenant: TenantContext = Depends(require_permission("production.shift.validate")),
) -> dict:
    with get_connection() as connection:
        result = ShiftValidationService(connection).validate_shift(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            shift_report_id=shift_report_id,
            seen_revisions=body.seen_revisions,
            shortfall_comment=body.shortfall_comment,
            regrind_work_center_id=body.regrind_work_center_id,
        )
        return _shift_result(connection, result)


@router.post("/shift-reports/{shift_report_id}/reject")
def reject_shift_report_sections(
    shift_report_id: str,
    body: RejectShiftSectionsRequest,
    tenant: TenantContext = Depends(require_permission("production.shift.validate")),
) -> dict:
    with get_connection() as connection:
        result = ShiftValidationService(connection).reject_sections(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            shift_report_id=shift_report_id,
            section_keys=body.sections,
            reason=body.reason,
        )
        return _shift_result(connection, result)


@router.post("/shift-reports/{shift_report_id}/reverse")
def reverse_shift_report(
    shift_report_id: str,
    body: ReverseShiftRequest,
    tenant: TenantContext = Depends(require_permission("production.admin_reports")),
) -> dict:
    with get_connection() as connection:
        result = ShiftValidationService(connection).reverse_shift(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            shift_report_id=shift_report_id,
            reason=body.reason,
            force=body.force,
        )
        return _shift_result(connection, result)
