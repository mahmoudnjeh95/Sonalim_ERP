from __future__ import annotations

import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from core.api.service import CoreService
from core.db import get_connection
from core.domain.result import Err
from core.tenancy import TenantContext, require_permission
from modules.qc.api.non_conformity_service import NonConformityService
from modules.qc.api.quality_service import FollowUpPolicyService, FollowUpService, QualityReportService
from modules.qc.domain.non_conformity import DispositionLine, NonConformity
from modules.qc.domain.quality import FollowUp, QualityReport, QualityReportDetail

router = APIRouter(prefix="/qc", tags=["qc"])


def _err_status(code: str) -> int:
    if code == "NOT_FOUND":
        return status.HTTP_404_NOT_FOUND
    if code in (
        "INVALID_TRANSITION",
        "NOT_EDITABLE",
        "DUPLICATE_REPORT",
        "OUTSIDE_WINDOW",
        "LOCATION_NOT_BLOCKED",
        "NON_CONFORMITY_ATTACHED",
    ):
        return status.HTTP_409_CONFLICT
    return status.HTTP_400_BAD_REQUEST


class QualityDetailRequest(BaseModel):
    pre_dryer_index: float | None = None
    humidity_percentage: float | None = None
    cooling_index: float | None = None
    pf_index: float | None = None
    sumo_index: float | None = None
    conforming_cartons: float = 0
    non_conforming_cartons: float = 0
    defect_details: str | None = None
    comments: str | None = None
    corrective_action: str | None = None

    def to_detail(self) -> QualityReportDetail:
        return QualityReportDetail(**self.model_dump())


class CreateQualityReportRequest(BaseModel):
    # The conditionnement (packaging) run this report inspects. of_id, the
    # report date, shift and team are all derived from it -- see
    # QualityReportService._resolve_conditionnement -- never asked here.
    conditionnement_report_id: str
    detail: QualityDetailRequest = QualityDetailRequest()


class UpdateQualityReportRequest(BaseModel):
    detail: QualityDetailRequest


class AdminUpdateQualityReportRequest(BaseModel):
    detail: QualityDetailRequest | None = None
    # Re-linking to a different conditionnement report re-derives of_id,
    # team, shift and report_date together -- see admin_update_report.
    conditionnement_report_id: str | None = None
    reason: str | None = None


class ValidateQualityReportRequest(BaseModel):
    correlation_id: str
    # Resolved by the caller from the OF, so qc never reads production's tables.
    product_id: str | None = None


class RejectRequest(BaseModel):
    reason: str


class SetFollowUpPolicyRequest(BaseModel):
    window_days: int
    product_id: str | None = None


class RecordObservationRequest(BaseModel):
    quality_report_id: str
    observed_on: datetime.date
    observation: str | None = None
    result: str | None = None


class TransitionFollowUpRequest(BaseModel):
    status: str
    result: str | None = None


class RaiseNonConformityRequest(BaseModel):
    of_id: str
    product_id: str
    quantity: float
    source_location_id: str
    defect_type: str
    correlation_id: str
    quarantine_location_id: str
    severity: str = "minor"
    quality_report_id: str | None = None
    description: str | None = None


class DispositionLineRequest(BaseModel):
    component: str
    disposition: str
    quantity: float
    note: str | None = None


class DispositionRequest(BaseModel):
    lines: list[DispositionLineRequest]
    correlation_id: str


class CloseNonConformityRequest(BaseModel):
    corrective_action: str


class AdminUpdateNonConformityRequest(BaseModel):
    quantity: float | None = None
    defect_type: str | None = None
    severity: str | None = None
    description: str | None = None
    corrective_action: str | None = None


# --- quality reports --------------------------------------------------------


@router.post("/quality-reports", status_code=status.HTTP_201_CREATED)
def create_quality_report(
    body: CreateQualityReportRequest,
    tenant: TenantContext = Depends(require_permission("qc.manage_quality_reports")),
) -> dict:
    with get_connection() as connection:
        result = QualityReportService(connection).create_report(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            conditionnement_report_id=body.conditionnement_report_id,
            detail=body.detail.to_detail(),
        )
        if isinstance(result, Err):
            connection.rollback()
            raise HTTPException(_err_status(result.code), {"code": result.code, "message": result.message})
        connection.commit()
    return _serialize_report_with_detail(result.value)


@router.get("/quality-reports")
def list_quality_reports(
    of_id: str | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    tenant: TenantContext = Depends(require_permission("qc.view_quality_reports")),
) -> list[dict]:
    with get_connection() as connection:
        reports = QualityReportService(connection).list_reports(
            tenant_id=tenant.tenant_id, of_id=of_id, status=status_filter
        )
    return [_serialize_report(report) for report in reports]


@router.get("/conditionnement-reports")
def list_inspectable_conditionnement_reports(
    of_id: str | None = None,
    tenant: TenantContext = Depends(require_permission("qc.view_quality_reports")),
) -> list[dict]:
    """Conditionnement reports with no quality report yet, enriched with the
    hint figures (packets, cartons, regrind) the create-report form shows
    once one is picked."""
    with get_connection() as connection:
        rows = QualityReportService(connection).list_inspectable_conditionnement_reports(
            tenant_id=tenant.tenant_id, of_id=of_id
        )
    return [
        {
            "conditionnement_report_id": row["conditionnement_report_id"],
            "of_id": row["of_id"],
            "report_date": row["report_date"].isoformat(),
            "shift": row["shift"],
            "team": row["team"],
            "status": row["status"],
            "packets_counted": row["packets_counted"],
            "carton_quantity": row["carton_quantity"],
            "finished_product_quantity": row["finished_product_quantity"],
            "regrind_quantity": row["regrind_quantity"],
        }
        for row in rows
    ]


@router.get("/quality-reports/team-performance")
def list_quality_team_performance(
    grain: str = Query(default="week"),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    tenant: TenantContext = Depends(require_permission("qc.view_quality_reports")),
) -> list[dict]:
    """Conformity from validated reports, bucketed by team and period."""
    if grain not in QualityReportService.GRAINS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            {"code": "INVALID_GRAIN", "message": f"grain must be one of {QualityReportService.GRAINS}"},
        )
    with get_connection() as connection:
        return QualityReportService(connection).team_conformity(
            tenant_id=tenant.tenant_id, grain=grain, date_from=date_from, date_to=date_to
        )


@router.get("/quality-reports/inspection-ledger")
def list_quality_inspection_ledger(
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    tenant: TenantContext = Depends(require_permission("qc.view_quality_reports")),
) -> list[dict]:
    """One row per quality report in the window, every status, with its
    verdict, readings and resolved product -- the grain the quality
    dashboards slice by product, team, shift, defect and day."""
    with get_connection() as connection:
        return QualityReportService(connection).inspection_ledger(
            tenant_id=tenant.tenant_id, date_from=date_from, date_to=date_to
        )


@router.get("/quality-reports/index-trend")
def list_quality_index_trend(
    grain: str = Query(default="week"),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    tenant: TenantContext = Depends(require_permission("qc.view_quality_reports")),
) -> list[dict]:
    """Average process indices from validated reports, bucketed by period."""
    if grain not in QualityReportService.GRAINS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            {"code": "INVALID_GRAIN", "message": f"grain must be one of {QualityReportService.GRAINS}"},
        )
    with get_connection() as connection:
        return QualityReportService(connection).index_trend(
            tenant_id=tenant.tenant_id, grain=grain, date_from=date_from, date_to=date_to
        )


@router.get("/quality-reports/{report_id}")
def get_quality_report(
    report_id: str, tenant: TenantContext = Depends(require_permission("qc.view_quality_reports"))
) -> dict:
    with get_connection() as connection:
        report = QualityReportService(connection).get_report(tenant_id=tenant.tenant_id, report_id=report_id)
    if report is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, {"code": "NOT_FOUND", "message": f"quality report {report_id} not found"}
        )
    return _serialize_report_with_detail(report)


@router.patch("/quality-reports/{report_id}")
def update_quality_report(
    report_id: str,
    body: UpdateQualityReportRequest,
    tenant: TenantContext = Depends(require_permission("qc.manage_quality_reports")),
) -> dict:
    with get_connection() as connection:
        result = QualityReportService(connection).update_draft(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, report_id=report_id, detail=body.detail.to_detail()
        )
        if isinstance(result, Err):
            connection.rollback()
            raise HTTPException(_err_status(result.code), {"code": result.code, "message": result.message})
        connection.commit()
    return _serialize_report_with_detail(result.value)


@router.patch("/quality-reports/{report_id}/admin")
def admin_update_quality_report(
    report_id: str,
    body: AdminUpdateQualityReportRequest,
    tenant: TenantContext = Depends(require_permission("qc.admin_quality_reports")),
) -> dict:
    """Edit-in-place. A more trusted right than progressing a report through its workflow."""
    with get_connection() as connection:
        result = QualityReportService(connection).admin_update_report(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            report_id=report_id,
            detail=body.detail.to_detail() if body.detail is not None else None,
            conditionnement_report_id=body.conditionnement_report_id,
            reason=body.reason,
        )
        if isinstance(result, Err):
            connection.rollback()
            raise HTTPException(_err_status(result.code), {"code": result.code, "message": result.message})
        connection.commit()
    return _serialize_report_with_detail(result.value)


@router.delete("/quality-reports/{report_id}")
def delete_quality_report(
    report_id: str,
    body: RejectRequest,
    tenant: TenantContext = Depends(require_permission("qc.admin_quality_reports")),
) -> dict:
    """Delete a report. The reason is required and is kept in the audit trail."""
    with get_connection() as connection:
        result = QualityReportService(connection).delete_report(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, report_id=report_id, reason=body.reason
        )
        if isinstance(result, Err):
            connection.rollback()
            raise HTTPException(_err_status(result.code), {"code": result.code, "message": result.message})
        connection.commit()
    return {"deleted": result.value}


@router.post("/quality-reports/{report_id}/submit")
def submit_quality_report(
    report_id: str, tenant: TenantContext = Depends(require_permission("qc.manage_quality_reports"))
) -> dict:
    with get_connection() as connection:
        result = QualityReportService(connection).submit_report(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, report_id=report_id
        )
        if isinstance(result, Err):
            connection.rollback()
            raise HTTPException(_err_status(result.code), {"code": result.code, "message": result.message})
        connection.commit()
    return _serialize_report(result.value)


@router.post("/quality-reports/{report_id}/validate")
def validate_quality_report(
    report_id: str,
    body: ValidateQualityReportRequest,
    tenant: TenantContext = Depends(require_permission("qc.validate_quality_reports")),
) -> dict:
    with get_connection() as connection:
        result = QualityReportService(connection).validate_report(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            report_id=report_id,
            correlation_id=body.correlation_id,
            product_id=body.product_id,
        )
        if isinstance(result, Err):
            connection.rollback()
            raise HTTPException(_err_status(result.code), {"code": result.code, "message": result.message})
        connection.commit()
    value = result.value
    return {
        **_serialize_report_with_detail(value),
        "follow_up_id": value["follow_up_id"],
        "window_ends_on": value["window_ends_on"].isoformat(),
    }


@router.post("/quality-reports/{report_id}/reject")
def reject_quality_report(
    report_id: str,
    body: RejectRequest,
    tenant: TenantContext = Depends(require_permission("qc.validate_quality_reports")),
) -> dict:
    with get_connection() as connection:
        result = QualityReportService(connection).reject_report(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, report_id=report_id, reason=body.reason
        )
        if isinstance(result, Err):
            connection.rollback()
            raise HTTPException(_err_status(result.code), {"code": result.code, "message": result.message})
        connection.commit()
    return _serialize_report(result.value)


@router.post("/quality-reports/{report_id}/revise")
def revise_quality_report(
    report_id: str, tenant: TenantContext = Depends(require_permission("qc.manage_quality_reports"))
) -> dict:
    with get_connection() as connection:
        result = QualityReportService(connection).revise_report(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, report_id=report_id
        )
        if isinstance(result, Err):
            connection.rollback()
            raise HTTPException(_err_status(result.code), {"code": result.code, "message": result.message})
        connection.commit()
    return _serialize_report(result.value)


# --- follow-up window -------------------------------------------------------


@router.get("/follow-up-policies")
def list_follow_up_policies(
    tenant: TenantContext = Depends(require_permission("qc.view_follow_ups")),
) -> list[dict]:
    with get_connection() as connection:
        return FollowUpPolicyService(connection).list_policies(tenant_id=tenant.tenant_id)


@router.put("/follow-up-policies")
def set_follow_up_policy(
    body: SetFollowUpPolicyRequest,
    tenant: TenantContext = Depends(require_permission("qc.admin_follow_up_policies")),
) -> dict:
    """Set the window for one product, or the tenant default when product_id is omitted."""
    with get_connection() as connection:
        result = FollowUpPolicyService(connection).set_policy(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            window_days=body.window_days,
            product_id=body.product_id,
        )
        if isinstance(result, Err):
            connection.rollback()
            raise HTTPException(_err_status(result.code), {"code": result.code, "message": result.message})
        connection.commit()
    return result.value


@router.get("/follow-ups")
def list_follow_ups(
    quality_report_id: str | None = None,
    of_id: str | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    tenant: TenantContext = Depends(require_permission("qc.view_follow_ups")),
) -> list[dict]:
    with get_connection() as connection:
        follow_ups = FollowUpService(connection).list_follow_ups(
            tenant_id=tenant.tenant_id, quality_report_id=quality_report_id, of_id=of_id, status=status_filter
        )
    return [_serialize_follow_up(f) for f in follow_ups]


@router.post("/follow-ups", status_code=status.HTTP_201_CREATED)
def record_observation(
    body: RecordObservationRequest,
    tenant: TenantContext = Depends(require_permission("qc.manage_follow_ups")),
) -> dict:
    with get_connection() as connection:
        result = FollowUpService(connection).record_observation(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            quality_report_id=body.quality_report_id,
            observed_on=body.observed_on,
            observation=body.observation,
            result=body.result,
        )
        if isinstance(result, Err):
            connection.rollback()
            raise HTTPException(_err_status(result.code), {"code": result.code, "message": result.message})
        connection.commit()
    return _serialize_follow_up(result.value)


@router.post("/follow-ups/{follow_up_id}/transition")
def transition_follow_up_status(
    follow_up_id: str,
    body: TransitionFollowUpRequest,
    tenant: TenantContext = Depends(require_permission("qc.manage_follow_ups")),
) -> dict:
    with get_connection() as connection:
        result = FollowUpService(connection).transition(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            follow_up_id=follow_up_id,
            new_status=body.status,
            result=body.result,
        )
        if isinstance(result, Err):
            connection.rollback()
            raise HTTPException(_err_status(result.code), {"code": result.code, "message": result.message})
        connection.commit()
    return _serialize_follow_up(result.value)


# --- non-conformity ---------------------------------------------------------


@router.post("/non-conformities", status_code=status.HTTP_201_CREATED)
def raise_non_conformity(
    body: RaiseNonConformityRequest,
    tenant: TenantContext = Depends(require_permission("qc.manage_non_conformities")),
) -> dict:
    with get_connection() as connection:
        result = NonConformityService(connection).raise_non_conformity(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            of_id=body.of_id,
            product_id=body.product_id,
            quantity=body.quantity,
            source_location_id=body.source_location_id,
            defect_type=body.defect_type,
            correlation_id=body.correlation_id,
            quarantine_location_id=body.quarantine_location_id,
            severity=body.severity,
            quality_report_id=body.quality_report_id,
            description=body.description,
        )
        if isinstance(result, Err):
            connection.rollback()
            raise HTTPException(_err_status(result.code), {"code": result.code, "message": result.message})
        connection.commit()
    return _serialize_nc(result.value)


@router.get("/non-conformities")
def list_non_conformities(
    of_id: str | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    tenant: TenantContext = Depends(require_permission("qc.view_non_conformities")),
) -> list[dict]:
    with get_connection() as connection:
        items = NonConformityService(connection).list_non_conformities(
            tenant_id=tenant.tenant_id, of_id=of_id, status=status_filter
        )
    return [_serialize_nc(item) for item in items]


@router.get("/non-conformities/disposition-summary")
def get_disposition_summary(
    of_id: str | None = Query(default=None),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    tenant: TenantContext = Depends(require_permission("qc.view_non_conformities")),
) -> list[dict]:
    """Where rejected product ended up — regrind, déchet, rework, back to stock."""
    with get_connection() as connection:
        return NonConformityService(connection).disposition_summary(
            tenant_id=tenant.tenant_id, of_id=of_id, date_from=date_from, date_to=date_to
        )


@router.get("/non-conformities/{non_conformity_id}")
def get_non_conformity(
    non_conformity_id: str, tenant: TenantContext = Depends(require_permission("qc.view_non_conformities"))
) -> dict:
    with get_connection() as connection:
        value = NonConformityService(connection).get_non_conformity(
            tenant_id=tenant.tenant_id, non_conformity_id=non_conformity_id
        )
    if value is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            {"code": "NOT_FOUND", "message": f"non-conformity {non_conformity_id} not found"},
        )
    with get_connection() as connection:
        product_uom_label = _product_uom_label(connection, tenant.tenant_id, value["non_conformity"].product_id)
    return {
        **_serialize_nc(value["non_conformity"]),
        "dispositions": [_serialize_disposition(line, product_uom_label=product_uom_label) for line in value["dispositions"]],
    }


@router.post("/non-conformities/{non_conformity_id}/disposition")
def disposition_non_conformity(
    non_conformity_id: str,
    body: DispositionRequest,
    tenant: TenantContext = Depends(require_permission("qc.manage_non_conformities")),
) -> dict:
    with get_connection() as connection:
        result = NonConformityService(connection).disposition(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            non_conformity_id=non_conformity_id,
            lines=tuple(
                DispositionLine(
                    component=line.component,
                    disposition=line.disposition,
                    quantity=line.quantity,
                    note=line.note,
                )
                for line in body.lines
            ),
            correlation_id=body.correlation_id,
        )
        if isinstance(result, Err):
            connection.rollback()
            raise HTTPException(_err_status(result.code), {"code": result.code, "message": result.message})
        connection.commit()
        value = result.value
        product_uom_label = _product_uom_label(connection, tenant.tenant_id, value["non_conformity"].product_id)
    return {
        **_serialize_nc(value["non_conformity"]),
        "dispositions": [_serialize_disposition(line, product_uom_label=product_uom_label) for line in value["dispositions"]],
    }


@router.post("/non-conformities/{non_conformity_id}/close")
def close_non_conformity(
    non_conformity_id: str,
    body: CloseNonConformityRequest,
    tenant: TenantContext = Depends(require_permission("qc.manage_non_conformities")),
) -> dict:
    with get_connection() as connection:
        result = NonConformityService(connection).close(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            non_conformity_id=non_conformity_id,
            corrective_action=body.corrective_action,
        )
        if isinstance(result, Err):
            connection.rollback()
            raise HTTPException(_err_status(result.code), {"code": result.code, "message": result.message})
        connection.commit()
    return _serialize_nc(result.value)


@router.patch("/non-conformities/{non_conformity_id}")
def admin_update_non_conformity(
    non_conformity_id: str,
    body: AdminUpdateNonConformityRequest,
    tenant: TenantContext = Depends(require_permission("qc.admin_non_conformities")),
) -> dict:
    with get_connection() as connection:
        result = NonConformityService(connection).admin_update_non_conformity(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            non_conformity_id=non_conformity_id,
            quantity=body.quantity,
            defect_type=body.defect_type,
            severity=body.severity,
            description=body.description,
            corrective_action=body.corrective_action,
        )
        if isinstance(result, Err):
            connection.rollback()
            raise HTTPException(_err_status(result.code), {"code": result.code, "message": result.message})
        connection.commit()
    return _serialize_nc(result.value)


# --- serialization ----------------------------------------------------------


def _serialize_report(report: QualityReport) -> dict:
    return {
        "id": report.id,
        "of_id": report.of_id,
        "product_id": report.product_id,
        "conditionnement_report_id": report.conditionnement_report_id,
        "report_date": report.report_date.isoformat(),
        "status": report.status,
        "revision": report.revision,
        "team": report.team,
        "shift": report.shift,
        "created_by": report.created_by,
        "submitted_at": report.submitted_at.isoformat() if report.submitted_at is not None else None,
        "validated_by": report.validated_by,
        "validated_at": report.validated_at.isoformat() if report.validated_at is not None else None,
        "rejection_reason": report.rejection_reason,
    }


def _serialize_detail(detail: QualityReportDetail) -> dict:
    return {
        "pre_dryer_index": detail.pre_dryer_index,
        "humidity_percentage": detail.humidity_percentage,
        "cooling_index": detail.cooling_index,
        "pf_index": detail.pf_index,
        "sumo_index": detail.sumo_index,
        "conforming_cartons": detail.conforming_cartons,
        "non_conforming_cartons": detail.non_conforming_cartons,
        "defect_details": detail.defect_details,
        "comments": detail.comments,
        "corrective_action": detail.corrective_action,
    }


def _serialize_report_with_detail(value: dict) -> dict:
    detail = value.get("detail")
    return {**_serialize_report(value["report"]), "detail": _serialize_detail(detail) if detail is not None else None}


def _serialize_follow_up(follow_up: FollowUp) -> dict:
    return {
        "id": follow_up.id,
        "quality_report_id": follow_up.quality_report_id,
        "of_id": follow_up.of_id,
        "window_ends_on": follow_up.window_ends_on.isoformat(),
        "observed_on": follow_up.observed_on.isoformat(),
        "status": follow_up.status,
        "result": follow_up.result,
        "observation": follow_up.observation,
        "actor_id": follow_up.actor_id,
    }


def _serialize_nc(non_conformity: NonConformity) -> dict:
    return {
        "id": non_conformity.id,
        "reference": non_conformity.reference,
        "of_id": non_conformity.of_id,
        "quality_report_id": non_conformity.quality_report_id,
        "product_id": non_conformity.product_id,
        "quantity": non_conformity.quantity,
        "source_location_id": non_conformity.source_location_id,
        "quarantine_location_id": non_conformity.quarantine_location_id,
        "defect_type": non_conformity.defect_type,
        "severity": non_conformity.severity,
        "status": non_conformity.status,
        "description": non_conformity.description,
        "corrective_action": non_conformity.corrective_action,
        "raised_by": non_conformity.raised_by,
        "raised_at": non_conformity.raised_at.isoformat() if non_conformity.raised_at is not None else None,
        "closed_by": non_conformity.closed_by,
        "closed_at": non_conformity.closed_at.isoformat() if non_conformity.closed_at is not None else None,
    }


# Film, carton and tape are never product-tracked per disposition line -- they
# come off the same fixed packaging vocabulary every plant uses, so their unit
# is a fixed label rather than something resolved per line. Only "product"
# resolves dynamically, from the non-conformity's own product.
_COMPONENT_FIXED_UNIT = {"film": "kg", "carton": "pièce", "tape": "pièce"}


def _product_uom_label(connection, tenant_id: str, product_id: str) -> str | None:
    uom = CoreService(connection).get_product_uom(tenant_id, product_id)
    return uom.display if uom is not None else None


def _serialize_disposition(line: DispositionLine, *, product_uom_label: str | None) -> dict:
    unit = product_uom_label if line.component == "product" else _COMPONENT_FIXED_UNIT.get(line.component)
    return {
        "component": line.component,
        "disposition": line.disposition,
        "quantity": line.quantity,
        "unit": unit,
        "note": line.note,
    }
