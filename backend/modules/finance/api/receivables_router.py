"""Receivables routes: payment terms, credit limits, the aged balance, customer statements and dunning."""
from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from core.db import get_connection
from core.domain.result import Err, err_detail
from core.payment_terms import PaymentTermService
from core.tabular_export import tabular_response
from core.tenancy import TenantContext, require_permission, require_session, user_has_permission
from modules.finance.api.dunning_service import DunningService
from modules.finance.api.receivables_service import ReceivablesService
from modules.finance.domain.receivables import BUCKETS

router = APIRouter(prefix="/finance", tags=["finance.receivables"])

VIEW = "finance.view_receivables"
MANAGE = "finance.manage_receivables"
ADMIN = "finance.admin_receivables"
DUNNING = "finance.manage_dunning"


def _unwrap(connection, result) -> Any:
    if isinstance(result, Err):
        connection.rollback()
        code = status.HTTP_404_NOT_FOUND if result.code == "NOT_FOUND" else status.HTTP_400_BAD_REQUEST
        raise HTTPException(code, err_detail(result))
    connection.commit()
    return result.value


def _require_any(connection, tenant: TenantContext, *permissions: str) -> None:
    if not any(user_has_permission(connection, user_id=tenant.user_id, permission=p) for p in permissions):
        raise HTTPException(status.HTTP_403_FORBIDDEN, {
            "code": "FORBIDDEN", "message": f"requires one of {', '.join(permissions)}",
            "message_fr": f"nécessite l'une des permissions {', '.join(permissions)}"})


# ---- payment terms -----------------------------------------------------------------------------------------

class InstallmentBody(BaseModel):
    percent: Decimal
    days: int
    end_of_month: bool = False
    day_of_month: int | None = None


class CreateTermRequest(BaseModel):
    code: str
    name_fr: str
    name_en: str = ""
    installments: list[InstallmentBody]


class UpdateTermRequest(BaseModel):
    name_fr: str | None = None
    name_en: str | None = None
    installments: list[InstallmentBody] | None = None
    active: bool | None = None


class PartnerTermRequest(BaseModel):
    side: str
    term_id: str | None = None


@router.get("/payment-terms")
def list_payment_terms(include_inactive: bool = False, tenant: TenantContext = Depends(require_session)) -> list[dict]:
    with get_connection() as connection:
        # Anyone who sees invoices or customers may read the catalog; it is reference data.
        _require_any(connection, tenant, VIEW, "finance.view_invoices", "procurement.view_purchase_invoices", "core.view_partners")
        terms = PaymentTermService(connection).list_terms(tenant_id=tenant.tenant_id, include_inactive=include_inactive)
        connection.commit()
        return terms


@router.post("/payment-terms", status_code=status.HTTP_201_CREATED)
def create_payment_term(body: CreateTermRequest, tenant: TenantContext = Depends(require_permission(MANAGE))) -> dict:
    with get_connection() as connection:
        return _unwrap(connection, PaymentTermService(connection).create_term(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, code=body.code, name_fr=body.name_fr, name_en=body.name_en,
            installments=[i.model_dump() for i in body.installments]))


@router.patch("/payment-terms/{term_id}")
def update_payment_term(term_id: str, body: UpdateTermRequest, tenant: TenantContext = Depends(require_permission(ADMIN))) -> dict:
    with get_connection() as connection:
        return _unwrap(connection, PaymentTermService(connection).update_term(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, term_id=term_id, name_fr=body.name_fr, name_en=body.name_en,
            installments=[i.model_dump() for i in body.installments] if body.installments is not None else None, active=body.active))


@router.get("/partners/{partner_id}/payment-terms")
def get_partner_terms(partner_id: str, tenant: TenantContext = Depends(require_session)) -> dict:
    with get_connection() as connection:
        _require_any(connection, tenant, VIEW, "procurement.view_purchase_invoices", "core.view_partners")
        return PaymentTermService(connection).partner_terms(tenant_id=tenant.tenant_id, partner_id=partner_id)


@router.put("/partners/{partner_id}/payment-terms")
def set_partner_terms(partner_id: str, body: PartnerTermRequest, tenant: TenantContext = Depends(require_permission(MANAGE))) -> dict:
    with get_connection() as connection:
        return _unwrap(connection, PaymentTermService(connection).set_partner_term(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, partner_id=partner_id, side=body.side, term_id=body.term_id))


# ---- credit ----------------------------------------------------------------------------------------------

class CreditLimitRequest(BaseModel):
    credit_limit: Decimal | None = None
    note: str | None = None


@router.get("/customers/{partner_id}/position")
def customer_position(partner_id: str, tenant: TenantContext = Depends(require_permission(VIEW))) -> dict:
    with get_connection() as connection:
        position = ReceivablesService(connection).position(tenant_id=tenant.tenant_id, partner_id=partner_id)
        connection.commit()
        return position


@router.get("/customers/{partner_id}/credit-check")
def credit_check_preview(partner_id: str, order_amount: Decimal = Query(Decimal("0"), ge=0),
                         tenant: TenantContext = Depends(require_session)) -> dict:
    """What confirming an order would meet: shown on the order screen to whoever confirms orders."""
    with get_connection() as connection:
        _require_any(connection, tenant, VIEW, "sales.manage_orders", "sales.view_orders")
        preview = ReceivablesService(connection).credit_preview(tenant_id=tenant.tenant_id, partner_id=partner_id, order_amount=order_amount)
        preview["can_override"] = user_has_permission(connection, user_id=tenant.user_id, permission="finance.admin_credit_override")
        connection.commit()
        return preview


@router.put("/customers/{partner_id}/credit-limit")
def set_credit_limit(partner_id: str, body: CreditLimitRequest, tenant: TenantContext = Depends(require_permission(MANAGE))) -> dict:
    with get_connection() as connection:
        return _unwrap(connection, ReceivablesService(connection).set_credit_limit(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, partner_id=partner_id, credit_limit=body.credit_limit, note=body.note))


STATEMENT_HEADERS = {
    "fr": ["Date", "Type", "Référence", "Échéance", "Débit", "Crédit", "Solde"],
    "en": ["Date", "Type", "Reference", "Due date", "Debit", "Credit", "Balance"],
}
KIND_LABELS = {
    "fr": {"invoice": "Facture", "credit_note": "Avoir", "payment": "Règlement", "payment_reversed": "Règlement annulé"},
    "en": {"invoice": "Invoice", "credit_note": "Credit note", "payment": "Payment", "payment_reversed": "Payment reversed"},
}


@router.get("/customers/{partner_id}/statement", response_model=None)
def customer_statement(partner_id: str, date_from: datetime.date | None = None, date_to: datetime.date | None = None,
                       format: str | None = Query(None, pattern="^(csv|xlsx)$"), lang: str = Query("fr", pattern="^(fr|en)$"),
                       tenant: TenantContext = Depends(require_permission(VIEW))):
    with get_connection() as connection:
        statement = ReceivablesService(connection).statement(tenant_id=tenant.tenant_id, partner_id=partner_id,
                                                             date_from=date_from, date_to=date_to)
        connection.commit()
    if format is None:
        return statement
    labels = KIND_LABELS[lang]
    rows = [[None, "Solde d'ouverture" if lang == "fr" else "Opening balance", "", "", "", "", statement["opening_balance"]]]
    rows += [[line["date"], labels[line["kind"]], line["reference"], line["due_date"] or "", line["debit"] or "", line["credit"] or "",
              line["balance"]] for line in statement["lines"]]
    name = (statement["partner_name"] or partner_id).replace(" ", "_")
    return tabular_response(STATEMENT_HEADERS[lang], rows, format, f"releve_{name}")


AGING_HEADERS = {
    "fr": ["Client", "Limite", "Reste dû", "Non échu", "1-30 j", "31-60 j", "61-90 j", "> 90 j", "Retard max (j)"],
    "en": ["Customer", "Limit", "Remaining", "Not due", "1-30 d", "31-60 d", "61-90 d", "> 90 d", "Max days late"],
}


@router.get("/receivables/aging", response_model=None)
def aging(format: str | None = Query(None, pattern="^(csv|xlsx)$"), lang: str = Query("fr", pattern="^(fr|en)$"),
          tenant: TenantContext = Depends(require_permission(VIEW))):
    with get_connection() as connection:
        rows = ReceivablesService(connection).aging(tenant_id=tenant.tenant_id)
        connection.commit()
    if format is None:
        return rows
    table = [[r["partner_name"], r["credit_limit"] or "", r["remaining"], *[r[f"bucket_{k}"] for k, _, _ in BUCKETS], r["max_days_overdue"]]
             for r in rows]
    return tabular_response(AGING_HEADERS[lang], table, format, "balance_agee")


class SettingsRequest(BaseModel):
    block_overdue_days: int | None = None
    warn_ratio: Decimal | None = None
    company_name: str | None = None
    company_address: str | None = None
    company_phone: str | None = None
    signatory: str | None = None
    signatory_title: str | None = None
    company_email: str | None = None
    company_tax_id: str | None = None
    company_rccm: str | None = None
    chase_from: datetime.date | None = None


@router.get("/receivables/settings")
def get_settings(tenant: TenantContext = Depends(require_permission(VIEW))) -> dict:
    with get_connection() as connection:
        return ReceivablesService(connection).settings(tenant_id=tenant.tenant_id)


@router.put("/receivables/settings")
def put_settings(body: SettingsRequest, tenant: TenantContext = Depends(require_permission(ADMIN))) -> dict:
    with get_connection() as connection:
        changes = body.model_dump(exclude_unset=True)
        if changes.get("warn_ratio") is None:
            changes.pop("warn_ratio", None)
        return _unwrap(connection, ReceivablesService(connection).update_settings(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, changes=changes))


# ---- dunning ---------------------------------------------------------------------------------------------

class LevelBody(BaseModel):
    days_after_due: int
    name_fr: str
    name_en: str = ""
    letter_fr: str = ""
    letter_en: str = ""
    blocks_orders: bool = False


class LevelsRequest(BaseModel):
    levels: list[LevelBody]


class ActionRequest(BaseModel):
    partner_id: str
    kind: str
    level: int | None = None
    note: str | None = None
    invoice_ids: list[str] | None = None
    promise_date: datetime.date | None = None
    promise_amount: Decimal | None = None


class PromiseStatusRequest(BaseModel):
    status: str


@router.get("/dunning")
def dunning_worklist(tenant: TenantContext = Depends(require_permission(VIEW))) -> list[dict]:
    with get_connection() as connection:
        rows = DunningService(connection).worklist(tenant_id=tenant.tenant_id)
        connection.commit()
        return rows


@router.get("/dunning/levels")
def dunning_levels(tenant: TenantContext = Depends(require_permission(VIEW))) -> list[dict]:
    with get_connection() as connection:
        levels = DunningService(connection).levels(tenant_id=tenant.tenant_id)
        connection.commit()
        return levels


@router.put("/dunning/levels")
def save_dunning_levels(body: LevelsRequest, tenant: TenantContext = Depends(require_permission(ADMIN))) -> list[dict]:
    with get_connection() as connection:
        return _unwrap(connection, DunningService(connection).save_levels(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, levels=[l.model_dump() for l in body.levels]))


@router.get("/dunning/actions")
def dunning_actions(partner_id: str, tenant: TenantContext = Depends(require_permission(VIEW))) -> list[dict]:
    with get_connection() as connection:
        return DunningService(connection).history(tenant_id=tenant.tenant_id, partner_id=partner_id)


@router.post("/dunning/actions", status_code=status.HTTP_201_CREATED)
def record_dunning_action(body: ActionRequest, tenant: TenantContext = Depends(require_permission(DUNNING))) -> dict:
    with get_connection() as connection:
        return _unwrap(connection, DunningService(connection).record_action(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, partner_id=body.partner_id, kind=body.kind, level=body.level,
            note=body.note, invoice_ids=body.invoice_ids, promise_date=body.promise_date, promise_amount=body.promise_amount))


@router.patch("/dunning/actions/{action_id}/promise")
def set_promise_status(action_id: str, body: PromiseStatusRequest, tenant: TenantContext = Depends(require_permission(DUNNING))) -> dict:
    with get_connection() as connection:
        return _unwrap(connection, DunningService(connection).set_promise_status(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, action_id=action_id, status=body.status))


@router.post("/dunning/run")
def run_dunning(tenant: TenantContext = Depends(require_permission(DUNNING))) -> dict:
    with get_connection() as connection:
        result = DunningService(connection).run(tenant_id=tenant.tenant_id, actor_id=tenant.user_id)
        connection.commit()
        return result


@router.get("/dunning/letter/{partner_id}")
def dunning_letter(partner_id: str, level: int | None = None, tenant: TenantContext = Depends(require_permission(VIEW))) -> dict:
    with get_connection() as connection:
        return _unwrap(connection, DunningService(connection).letter(tenant_id=tenant.tenant_id, partner_id=partner_id, level=level))
