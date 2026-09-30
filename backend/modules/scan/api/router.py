from __future__ import annotations

import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field

from core.db import get_connection
from core.domain.result import Err, err_detail
from core.tenancy import TenantContext, require_permission, require_session, user_has_permission
from modules.scan.api.alias_service import ScanAliasService
from modules.scan.api.session_service import ScanSessionService
from modules.scan.api.vocabulary_service import build_vocabulary, vocabulary_options
from modules.scan.domain.review import APPLY_ORDER

router = APIRouter(prefix="/scan", tags=["scan"])

_STATUS_BY_CODE = {
    "NOT_FOUND": status.HTTP_404_NOT_FOUND,
    "FORBIDDEN_SECTION": status.HTTP_403_FORBIDDEN,
    "SHIFT_VALIDATED": status.HTTP_409_CONFLICT,
    "SECTION_CHANGED": status.HTTP_409_CONFLICT,
    "SESSION_CLOSED": status.HTTP_409_CONFLICT,
}


class CreateSessionRequest(BaseModel):
    kind: str = "shift"
    work_center_id: str
    report_date: datetime.date
    shift: str
    default_of_id: str | None = None


class PageUpload(BaseModel):
    filename: str | None = None
    content_type: str
    width: int | None = None
    height: int | None = None
    data_base64: str


class UploadPagesRequest(BaseModel):
    files: list[PageUpload]


class RereadRequest(BaseModel):
    form_hint: str | None = None


class ReviewRequest(BaseModel):
    review_state: dict


class ApplyRequest(BaseModel):
    header: dict = Field(default_factory=dict)
    sections: dict = Field(default_factory=dict)
    fingerprints: dict = Field(default_factory=dict)


class AliasUpdateRequest(BaseModel):
    target_value: str


def _forbidden(permission: str) -> HTTPException:
    return HTTPException(
        status.HTTP_403_FORBIDDEN,
        {"code": "FORBIDDEN", "message": f"missing permission: {permission}", "message_fr": f"permission manquante : {permission}"},
    )


def _scanner_or_viewer(tenant: TenantContext = Depends(require_session)) -> TenantContext:
    """The photos behind a shift are open to whoever scans and to whoever only views them."""
    with get_connection() as connection:
        if not any(user_has_permission(connection, user_id=tenant.user_id, permission=p) for p in ("scan.use_scanner", "scan.view_scans")):
            raise _forbidden("scan.view_scans")
    return tenant


def _result(connection, result):
    if isinstance(result, Err):
        connection.rollback()
        raise HTTPException(_STATUS_BY_CODE.get(result.code, status.HTTP_422_UNPROCESSABLE_ENTITY), err_detail(result))
    connection.commit()
    return result.value


USE = require_permission("scan.use_scanner")


@router.post("/sessions", status_code=status.HTTP_201_CREATED)
def create_session(body: CreateSessionRequest, tenant: TenantContext = Depends(USE)) -> dict:
    with get_connection() as connection:
        return _result(connection, ScanSessionService(connection).create_session(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, kind=body.kind, work_center_id=body.work_center_id,
            report_date=body.report_date, shift=body.shift, default_of_id=body.default_of_id,
        ))


@router.get("/sessions")
def list_sessions(status_filter: str | None = Query(default=None, alias="status"), tenant: TenantContext = Depends(USE)) -> list[dict]:
    with get_connection() as connection:
        return ScanSessionService(connection).list_sessions(tenant_id=tenant.tenant_id, status=status_filter)


@router.get("/sessions/{session_id}")
def get_session(session_id: str, tenant: TenantContext = Depends(USE)) -> dict:
    with get_connection() as connection:
        return _result(connection, ScanSessionService(connection).get_session(tenant_id=tenant.tenant_id, session_id=session_id))


@router.post("/sessions/{session_id}/pages", status_code=status.HTTP_201_CREATED)
def add_pages(session_id: str, body: UploadPagesRequest, tenant: TenantContext = Depends(USE)) -> list[dict]:
    with get_connection() as connection:
        return _result(connection, ScanSessionService(connection).add_pages(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, session_id=session_id,
            files=[upload.model_dump() for upload in body.files],
        ))


@router.delete("/sessions/{session_id}/pages/{page_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_page(session_id: str, page_id: str, tenant: TenantContext = Depends(USE)) -> Response:
    with get_connection() as connection:
        _result(connection, ScanSessionService(connection).delete_page(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, session_id=session_id, page_id=page_id,
        ))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/sessions/{session_id}/pages/{page_id}/reread")
def reread_page(session_id: str, page_id: str, body: RereadRequest, tenant: TenantContext = Depends(USE)) -> dict:
    with get_connection() as connection:
        return _result(connection, ScanSessionService(connection).reread_page(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, session_id=session_id, page_id=page_id, form_hint=body.form_hint,
        ))


@router.get("/pages/{page_id}/image")
def page_image(page_id: str, tenant: TenantContext = Depends(_scanner_or_viewer)) -> Response:
    with get_connection() as connection:
        image, content_type = _result(connection, ScanSessionService(connection).page_image(tenant_id=tenant.tenant_id, page_id=page_id))
    return Response(content=image, media_type=content_type, headers={"Cache-Control": "private, max-age=3600"})


@router.get("/sessions/{session_id}/proposal")
def proposal(session_id: str, tenant: TenantContext = Depends(USE)) -> dict:
    with get_connection() as connection:
        return _result(connection, ScanSessionService(connection).proposal(tenant_id=tenant.tenant_id, session_id=session_id))


@router.put("/sessions/{session_id}/review", status_code=status.HTTP_204_NO_CONTENT)
def save_review(session_id: str, body: ReviewRequest, tenant: TenantContext = Depends(USE)) -> Response:
    with get_connection() as connection:
        _result(connection, ScanSessionService(connection).save_review(
            tenant_id=tenant.tenant_id, session_id=session_id, review_state=body.review_state,
        ))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/sessions/{session_id}/apply")
def apply(session_id: str, body: ApplyRequest, tenant: TenantContext = Depends(USE)) -> dict:
    with get_connection() as connection:
        # The production module's own per-section edit rights (declared in its module.json).
        allowed = {
            key for key in APPLY_ORDER
            if user_has_permission(connection, user_id=tenant.user_id, permission=f"production.shift.edit.{key}")
        }
        return _result(connection, ScanSessionService(connection).apply(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, session_id=session_id, header=body.header,
            sections=body.sections, fingerprints=body.fingerprints, allowed_sections=allowed,
        ))


@router.post("/sessions/{session_id}/discard")
def discard(session_id: str, tenant: TenantContext = Depends(USE)) -> dict:
    with get_connection() as connection:
        return _result(connection, ScanSessionService(connection).discard_session(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, session_id=session_id,
        ))


@router.get("/shifts/{shift_report_id}/pages")
def shift_pages(shift_report_id: str, tenant: TenantContext = Depends(_scanner_or_viewer)) -> list[dict]:
    with get_connection() as connection:
        return ScanSessionService(connection).shift_pages(tenant_id=tenant.tenant_id, shift_report_id=shift_report_id)


@router.get("/aliases")
def list_aliases(kind: str | None = None, tenant: TenantContext = Depends(USE)) -> list[dict]:
    with get_connection() as connection:
        return ScanAliasService(connection).list_aliases(tenant_id=tenant.tenant_id, kind=kind)


@router.patch("/aliases/{alias_id}")
def update_alias(alias_id: str, body: AliasUpdateRequest, tenant: TenantContext = Depends(require_permission("scan.admin_aliases"))) -> dict:
    with get_connection() as connection:
        return _result(connection, ScanAliasService(connection).update_alias(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, alias_id=alias_id, target_value=body.target_value,
        ))


@router.delete("/aliases/{alias_id}")
def delete_alias(alias_id: str, tenant: TenantContext = Depends(require_permission("scan.admin_aliases"))) -> dict:
    with get_connection() as connection:
        return _result(connection, ScanAliasService(connection).delete_alias(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, alias_id=alias_id,
        ))


@router.get("/vocabulary")
def vocabulary(work_center_id: str | None = None, tenant: TenantContext = Depends(USE)) -> dict:
    with get_connection() as connection:
        return vocabulary_options(build_vocabulary(connection, tenant_id=tenant.tenant_id, work_center_id=work_center_id))
