"""Tax codes, a shared-kernel catalog, and which code each product and partner is taxed under.

Sales, finance and procurement all resolve a line's VAT through `TaxCodeService.resolve_line`, so the service
lives here; the routes are under /core/tax-codes."""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Iterable

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from ulid import ULID

from core.audit import record_audit
from core.db import get_connection
from core.domain.result import Err, Ok, Result, err_detail
from core.domain.tax import (
    DEFAULT_TAX_CODES,
    SIDES,
    ResolvedTax,
    TaxCode,
    check_tax_code,
    codes_from_rows,
    normalize_code,
    resolve_line_tax,
)
from core.tenancy import TenantContext, require_permission, require_session

MANAGE = "core.manage_tax_codes"
_COLUMNS = "id, code, name_fr, name_en, rate, scope, exempt, legal_mention, active"
PRODUCT_COLUMNS = {"sales": "sales_tax_code_id", "purchases": "purchase_tax_code_id"}
PARTNER_COLUMNS = {"sales": "customer_tax_code_id", "purchases": "supplier_tax_code_id"}


def _row(row) -> dict[str, Any]:
    return {"id": row[0], "code": row[1], "name_fr": row[2], "name_en": row[3], "rate": row[4], "scope": row[5],
            "exempt": row[6], "legal_mention": row[7], "active": row[8]}


def _check_side(side: str) -> Result[None]:
    if side not in SIDES:
        return Err("INVALID_SIDE", "side is sales or purchases", "le côté est ventes ou achats")
    return Ok(None)


class TaxCodeService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    # ---- catalog ---------------------------------------------------------------------------------------

    def _ensure_defaults(self, tenant_id: str) -> None:
        if self._connection.execute("SELECT 1 FROM core.tax_codes WHERE tenant_id = %s LIMIT 1", (tenant_id,)).fetchone():
            return
        for code, name_fr, name_en, rate, exempt, mention in DEFAULT_TAX_CODES:
            self._connection.execute(
                "INSERT INTO core.tax_codes (id, tenant_id, code, name_fr, name_en, rate, exempt, legal_mention) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (tenant_id, code) DO NOTHING",
                (str(ULID()), tenant_id, code, name_fr, name_en, rate, exempt, mention),
            )

    def list_codes(self, *, tenant_id: str, include_inactive: bool = False) -> list[dict[str, Any]]:
        self._ensure_defaults(tenant_id)
        rows = self._connection.execute(
            f"SELECT {_COLUMNS} FROM core.tax_codes WHERE tenant_id = %s {'' if include_inactive else 'AND active'} "
            "ORDER BY exempt, rate DESC, code",
            (tenant_id,),
        ).fetchall()
        return [_row(row) for row in rows]

    def get_code(self, *, tenant_id: str, tax_code_id: str) -> dict[str, Any] | None:
        row = self._connection.execute(f"SELECT {_COLUMNS} FROM core.tax_codes WHERE tenant_id = %s AND id = %s",
                                       (tenant_id, tax_code_id)).fetchone()
        return _row(row) if row else None

    def find_code(self, *, tenant_id: str, code: str) -> dict[str, Any] | None:
        self._ensure_defaults(tenant_id)
        row = self._connection.execute(f"SELECT {_COLUMNS} FROM core.tax_codes WHERE tenant_id = %s AND code = %s",
                                       (tenant_id, normalize_code(code))).fetchone()
        return _row(row) if row else None

    def create_code(self, *, tenant_id: str, actor_id: str, code: str, name_fr: str, name_en: str | None, rate: object,
                    scope: str = "both", exempt: bool = False, legal_mention: str | None = None) -> Result[dict[str, Any]]:
        code = normalize_code(code)
        checked = check_tax_code(code=code, name_fr=name_fr or "", rate=rate, scope=scope, exempt=exempt)
        if isinstance(checked, Err):
            return checked
        self._ensure_defaults(tenant_id)
        if self._connection.execute("SELECT 1 FROM core.tax_codes WHERE tenant_id = %s AND code = %s", (tenant_id, code)).fetchone():
            return Err("TAX_CODE_EXISTS", f"a tax code {code} already exists", f"un code de taxe {code} existe déjà")
        tax_code_id = str(ULID())
        self._connection.execute(
            "INSERT INTO core.tax_codes (id, tenant_id, code, name_fr, name_en, rate, scope, exempt, legal_mention) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (tax_code_id, tenant_id, code, name_fr.strip(), (name_en or name_fr).strip(), checked.value, scope, exempt,
             (legal_mention or "").strip() or None),
        )
        record_audit(self._connection, tenant_id=tenant_id, actor_id=actor_id, action="tax_code.created", entity_type="tax_code",
                     entity_id=tax_code_id, payload={"code": code, "rate": str(checked.value), "scope": scope, "exempt": exempt})
        return Ok(self.get_code(tenant_id=tenant_id, tax_code_id=tax_code_id))

    def update_code(self, *, tenant_id: str, actor_id: str, tax_code_id: str, name_fr: str | None = None,
                    name_en: str | None = None, rate: object = None, scope: str | None = None, exempt: bool | None = None,
                    legal_mention: str | None = None, active: bool | None = None) -> Result[dict[str, Any]]:
        """The code itself never changes. A new rate applies to lines written from now on: documents keep the
        rate they were given."""
        current = self.get_code(tenant_id=tenant_id, tax_code_id=tax_code_id)
        if current is None:
            return Err("NOT_FOUND", f"tax code {tax_code_id} not found", f"code de taxe {tax_code_id} introuvable")
        values = {
            "name_fr": (name_fr or current["name_fr"]).strip(),
            "name_en": (name_en or current["name_en"]).strip(),
            "rate": current["rate"] if rate is None else rate,
            "scope": scope or current["scope"],
            "exempt": current["exempt"] if exempt is None else exempt,
            "legal_mention": current["legal_mention"] if legal_mention is None else ((legal_mention or "").strip() or None),
            "active": current["active"] if active is None else active,
        }
        checked = check_tax_code(code=current["code"], name_fr=values["name_fr"], rate=values["rate"], scope=values["scope"],
                                 exempt=values["exempt"])
        if isinstance(checked, Err):
            return checked
        values["rate"] = checked.value
        self._connection.execute(
            "UPDATE core.tax_codes SET name_fr = %s, name_en = %s, rate = %s, scope = %s, exempt = %s, legal_mention = %s, active = %s "
            "WHERE tenant_id = %s AND id = %s",
            (values["name_fr"], values["name_en"], values["rate"], values["scope"], values["exempt"], values["legal_mention"],
             values["active"], tenant_id, tax_code_id),
        )
        record_audit(self._connection, tenant_id=tenant_id, actor_id=actor_id, action="tax_code.updated", entity_type="tax_code",
                     entity_id=tax_code_id, payload={k: str(v) if isinstance(v, Decimal) else v for k, v in values.items()})
        return Ok(self.get_code(tenant_id=tenant_id, tax_code_id=tax_code_id))

    def _codes(self, tenant_id: str) -> list[TaxCode]:
        return codes_from_rows(self.list_codes(tenant_id=tenant_id, include_inactive=True))

    # ---- assignments -----------------------------------------------------------------------------------

    def _assignment(self, table: str, columns: dict[str, str], tenant_id: str, entity_id: str) -> dict[str, Any] | None:
        row = self._connection.execute(
            f"SELECT {columns['sales']}, {columns['purchases']} FROM core.{table} WHERE tenant_id = %s AND id = %s",
            (tenant_id, entity_id),
        ).fetchone()
        if row is None:
            return None
        return {"sales_tax_code_id": row[0], "purchases_tax_code_id": row[1]}

    def product_codes(self, *, tenant_id: str, product_id: str) -> dict[str, Any] | None:
        return self._assignment("products", PRODUCT_COLUMNS, tenant_id, product_id)

    def partner_codes(self, *, tenant_id: str, partner_id: str) -> dict[str, Any] | None:
        return self._assignment("partners", PARTNER_COLUMNS, tenant_id, partner_id)

    def _set(self, table: str, columns: dict[str, str], *, tenant_id: str, actor_id: str, entity_id: str,
             values: dict[str, str | None]) -> Result[dict[str, Any]]:
        if self._assignment(table, columns, tenant_id, entity_id) is None:
            return Err("NOT_FOUND", f"{table[:-1]} {entity_id} not found", f"{'produit' if table == 'products' else 'partenaire'} {entity_id} introuvable")
        for side, tax_code_id in values.items():
            checked = _check_side(side)
            if isinstance(checked, Err):
                return checked
            if tax_code_id is not None:
                code = self.get_code(tenant_id=tenant_id, tax_code_id=tax_code_id)
                if code is None or not code["active"]:
                    return Err("NOT_FOUND", f"tax code {tax_code_id} not found", f"code de taxe {tax_code_id} introuvable")
                if code["scope"] not in ("both", side):
                    return Err("TAX_CODE_WRONG_SCOPE", f"tax code {code['code']} is not for {side}",
                               f"le code de taxe {code['code']} ne s'applique pas aux {'ventes' if side == 'sales' else 'achats'}")
            self._connection.execute(f"UPDATE core.{table} SET {columns[side]} = %s WHERE tenant_id = %s AND id = %s",
                                     (tax_code_id, tenant_id, entity_id))
        record_audit(self._connection, tenant_id=tenant_id, actor_id=actor_id, action=f"{table[:-1]}.tax_codes_set",
                     entity_type=table[:-1], entity_id=entity_id, payload=values)
        return Ok(self._assignment(table, columns, tenant_id, entity_id))

    def set_product_codes(self, *, tenant_id: str, actor_id: str, product_id: str, values: dict[str, str | None]) -> Result[dict[str, Any]]:
        return self._set("products", PRODUCT_COLUMNS, tenant_id=tenant_id, actor_id=actor_id, entity_id=product_id, values=values)

    def set_partner_codes(self, *, tenant_id: str, actor_id: str, partner_id: str, values: dict[str, str | None]) -> Result[dict[str, Any]]:
        return self._set("partners", PARTNER_COLUMNS, tenant_id=tenant_id, actor_id=actor_id, entity_id=partner_id, values=values)

    # ---- resolution ------------------------------------------------------------------------------------

    def resolver(self, *, tenant_id: str, side: str, partner_id: str | None, default_rate: Decimal) -> "LineTaxResolver":
        """One resolver per document: the catalog and the partner are read once, the products as lines come."""
        codes = self._codes(tenant_id)
        partner = self.partner_codes(tenant_id=tenant_id, partner_id=partner_id) if partner_id else None
        return LineTaxResolver(self._connection, tenant_id=tenant_id, side=side, codes=codes,
                               partner_code_id=(partner or {}).get(f"{side}_tax_code_id"), default_rate=default_rate)


class LineTaxResolver:
    def __init__(self, connection: psycopg.Connection, *, tenant_id: str, side: str, codes: list[TaxCode],
                 partner_code_id: str | None, default_rate: Decimal) -> None:
        self._connection = connection
        self._tenant_id = tenant_id
        self.side = side
        self.codes = codes
        self.partner_code_id = partner_code_id
        self.default_rate = default_rate
        self._products: dict[str, str | None] = {}

    def product_code_id(self, product_id: str | None) -> str | None:
        if not product_id:
            return None
        if product_id not in self._products:
            row = self._connection.execute(
                f"SELECT {PRODUCT_COLUMNS[self.side]} FROM core.products WHERE tenant_id = %s AND id = %s",
                (self._tenant_id, product_id),
            ).fetchone()
            self._products[product_id] = row[0] if row else None
        return self._products[product_id]

    def resolve(self, *, product_id: str | None, tax_code: str | None = None, vat_rate: object = None) -> Result[ResolvedTax]:
        return resolve_line_tax(
            side=self.side, codes=self.codes, explicit_code=tax_code, explicit_rate=vat_rate,
            partner_code_id=self.partner_code_id, product_code_id=self.product_code_id(product_id), default_rate=self.default_rate,
        )


# ---- routes --------------------------------------------------------------------------------------------

router = APIRouter(prefix="/core/tax-codes", tags=["core.tax-codes"])


class CreateTaxCodeRequest(BaseModel):
    code: str
    name_fr: str
    name_en: str | None = None
    rate: Decimal
    scope: str = "both"
    exempt: bool = False
    legal_mention: str | None = None


class UpdateTaxCodeRequest(BaseModel):
    name_fr: str | None = None
    name_en: str | None = None
    rate: Decimal | None = None
    scope: str | None = None
    exempt: bool | None = None
    legal_mention: str | None = None
    active: bool | None = None


class AssignmentRequest(BaseModel):
    sales_tax_code_id: str | None = None
    purchases_tax_code_id: str | None = None


def _unwrap(connection, result) -> Any:
    if isinstance(result, Err):
        connection.rollback()
        code = status.HTTP_404_NOT_FOUND if result.code == "NOT_FOUND" else status.HTTP_400_BAD_REQUEST
        raise HTTPException(code, err_detail(result))
    connection.commit()
    return result.value


def _json(value: dict[str, Any]) -> dict[str, Any]:
    return {k: (float(v) if isinstance(v, Decimal) else v) for k, v in value.items()}


@router.get("")
def list_tax_codes(include_inactive: bool = False, tenant: TenantContext = Depends(require_session)) -> list[dict]:
    with get_connection() as connection:
        codes = TaxCodeService(connection).list_codes(tenant_id=tenant.tenant_id, include_inactive=include_inactive)
        connection.commit()
    return [_json(code) for code in codes]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_tax_code(body: CreateTaxCodeRequest, tenant: TenantContext = Depends(require_permission(MANAGE))) -> dict:
    with get_connection() as connection:
        return _json(_unwrap(connection, TaxCodeService(connection).create_code(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, **body.model_dump())))


@router.patch("/{tax_code_id}")
def update_tax_code(tax_code_id: str, body: UpdateTaxCodeRequest, tenant: TenantContext = Depends(require_permission(MANAGE))) -> dict:
    with get_connection() as connection:
        return _json(_unwrap(connection, TaxCodeService(connection).update_code(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, tax_code_id=tax_code_id, **body.model_dump(exclude_unset=True))))


def _assignment_values(body: AssignmentRequest) -> dict[str, str | None]:
    sent = body.model_dump(exclude_unset=True)
    return {key.removesuffix("_tax_code_id"): value for key, value in sent.items()}


@router.get("/products/{product_id}")
def get_product_tax_codes(product_id: str, tenant: TenantContext = Depends(require_session)) -> dict:
    with get_connection() as connection:
        found = TaxCodeService(connection).product_codes(tenant_id=tenant.tenant_id, product_id=product_id)
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, {"code": "NOT_FOUND", "message": f"product {product_id} not found",
                                                         "message_fr": f"produit {product_id} introuvable"})
    return found


@router.put("/products/{product_id}")
def set_product_tax_codes(product_id: str, body: AssignmentRequest, tenant: TenantContext = Depends(require_permission(MANAGE))) -> dict:
    with get_connection() as connection:
        return _unwrap(connection, TaxCodeService(connection).set_product_codes(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, product_id=product_id, values=_assignment_values(body)))


@router.get("/partners/{partner_id}")
def get_partner_tax_codes(partner_id: str, tenant: TenantContext = Depends(require_session)) -> dict:
    with get_connection() as connection:
        found = TaxCodeService(connection).partner_codes(tenant_id=tenant.tenant_id, partner_id=partner_id)
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, {"code": "NOT_FOUND", "message": f"partner {partner_id} not found",
                                                         "message_fr": f"partenaire {partner_id} introuvable"})
    return found


@router.put("/partners/{partner_id}")
def set_partner_tax_codes(partner_id: str, body: AssignmentRequest, tenant: TenantContext = Depends(require_permission(MANAGE))) -> dict:
    with get_connection() as connection:
        return _unwrap(connection, TaxCodeService(connection).set_partner_codes(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, partner_id=partner_id, values=_assignment_values(body)))


@router.get("/resolve")
def resolve_line_codes(
    side: str,
    partner_id: str | None = None,
    product_id: list[str] = Query(default=[]),
    default_rate: Decimal = Decimal("0"),
    tenant: TenantContext = Depends(require_session),
) -> dict:
    """The code and rate a new line for each product would get when the user names neither, so a form can
    preselect them. `default_rate` is the module's default (sales or purchase settings)."""
    checked = _check_side(side)
    if isinstance(checked, Err):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, err_detail(checked))
    with get_connection() as connection:
        resolver = TaxCodeService(connection).resolver(tenant_id=tenant.tenant_id, side=side, partner_id=partner_id, default_rate=default_rate)
        result: dict[str, Any] = {}
        for pid in [*product_id, ""]:
            resolved = resolver.resolve(product_id=pid or None)
            if isinstance(resolved, Err):
                raise HTTPException(status.HTTP_400_BAD_REQUEST, err_detail(resolved))
            result[pid or "*"] = {"tax_code": resolved.value.tax_code, "rate": float(resolved.value.rate)}
        connection.commit()
    return result


def resolve_lines(connection: psycopg.Connection, *, tenant_id: str, side: str, partner_id: str | None, default_rate: Decimal,
                  lines: Iterable[dict[str, Any]]) -> Result[list[ResolvedTax]]:
    """Resolves each line (`product_id`, `tax_code`, `vat_rate`); the first refusal names the line."""
    resolver = TaxCodeService(connection).resolver(tenant_id=tenant_id, side=side, partner_id=partner_id, default_rate=default_rate)
    resolved: list[ResolvedTax] = []
    for index, line in enumerate(lines, start=1):
        result = resolver.resolve(product_id=line.get("product_id"), tax_code=line.get("tax_code"), vat_rate=line.get("vat_rate"))
        if isinstance(result, Err):
            return Err(result.code, f"line {index}: {result.message}", f"ligne {index} : {result.message_fr or result.message}")
        resolved.append(result.value)
    return Ok(resolved)
