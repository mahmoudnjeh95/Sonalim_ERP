"""Tax codes, a shared-kernel catalogue of named VAT rates, and which one is the default for sales and purchases.

Sales, finance and procurement all read the default rate, so the service lives here; the screens that manage
the codes belong to finance and are served by its router."""
from __future__ import annotations

from decimal import Decimal
from typing import Any

import psycopg
from ulid import ULID

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from core.domain.tax import DEFAULT_CODES, SIDES, applies_to_side, validate

_COLUMNS = "id, code, name_fr, name_en, rate, applies_to, exempt, active, is_default_sales, is_default_purchase"
_DEFAULT_COLUMN = {"sales": "is_default_sales", "purchase": "is_default_purchase"}


def _row(row) -> dict[str, Any]:
    keys = ("id", "code", "name_fr", "name_en", "rate", "applies_to", "exempt", "active", "is_default_sales", "is_default_purchase")
    return dict(zip(keys, row))


class TaxCodeService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def _ensure_defaults(self, tenant_id: str, legacy_rates: dict[str, Decimal] | None = None) -> None:
        """Fill an empty catalogue. `legacy_rates` ({side: rate}) are the default rates a module stored before
        codes existed: a tenant that had changed one keeps it, as a code made the default for that side."""
        if self._connection.execute("SELECT 1 FROM core.tax_codes WHERE tenant_id = %s LIMIT 1", (tenant_id,)).fetchone():
            return
        for index, (code, name_fr, name_en, rate, applies_to, exempt) in enumerate(DEFAULT_CODES):
            first = index == 0
            self._connection.execute(
                "INSERT INTO core.tax_codes (id, tenant_id, code, name_fr, name_en, rate, applies_to, exempt, is_default_sales, is_default_purchase) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (tenant_id, code) DO NOTHING",
                (str(ULID()), tenant_id, code, name_fr, name_en, rate, applies_to, exempt, first, first),
            )
        standard = DEFAULT_CODES[0][3]
        for side, legacy in (legacy_rates or {}).items():
            legacy = Decimal(str(legacy)).quantize(Decimal("0.01"))
            if side not in SIDES or legacy == standard:
                continue
            row = self._connection.execute("SELECT id FROM core.tax_codes WHERE tenant_id = %s AND rate = %s AND NOT exempt "
                                           "AND applies_to IN ('both', %s) ORDER BY created_at LIMIT 1", (tenant_id, legacy, side)).fetchone()
            if row is None:
                label = f"{legacy.normalize():f}"
                row = (str(ULID()),)
                self._connection.execute(
                    "INSERT INTO core.tax_codes (id, tenant_id, code, name_fr, name_en, rate, applies_to) VALUES (%s, %s, %s, %s, %s, %s, 'both') "
                    "ON CONFLICT (tenant_id, code) DO NOTHING",
                    (row[0], tenant_id, f"TVA{label}", f"TVA {label} %", f"VAT {label} %", legacy))
            column = _DEFAULT_COLUMN[side]
            self._connection.execute(f"UPDATE core.tax_codes SET {column} = FALSE WHERE tenant_id = %s AND {column}", (tenant_id,))
            self._connection.execute(f"UPDATE core.tax_codes SET {column} = TRUE WHERE tenant_id = %s AND id = %s", (tenant_id, row[0]))

    def list_codes(self, *, tenant_id: str, include_inactive: bool = False, side: str | None = None) -> list[dict[str, Any]]:
        self._ensure_defaults(tenant_id)
        rows = self._connection.execute(
            f"SELECT {_COLUMNS} FROM core.tax_codes WHERE tenant_id = %s {'' if include_inactive else 'AND active'} ORDER BY exempt, rate DESC, code",
            (tenant_id,),
        ).fetchall()
        codes = [_row(row) for row in rows]
        return [c for c in codes if applies_to_side(c["applies_to"], side)] if side in SIDES else codes

    def get_code(self, *, tenant_id: str, code_id: str) -> dict[str, Any] | None:
        row = self._connection.execute(f"SELECT {_COLUMNS} FROM core.tax_codes WHERE tenant_id = %s AND id = %s",
                                       (tenant_id, code_id)).fetchone()
        return _row(row) if row else None

    def get_by_code(self, *, tenant_id: str, code: str) -> dict[str, Any] | None:
        self._ensure_defaults(tenant_id)
        row = self._connection.execute(f"SELECT {_COLUMNS} FROM core.tax_codes WHERE tenant_id = %s AND code = %s",
                                       (tenant_id, (code or "").strip().upper())).fetchone()
        return _row(row) if row else None

    def default_code(self, *, tenant_id: str, side: str) -> dict[str, Any] | None:
        if side not in SIDES:
            return None
        self._ensure_defaults(tenant_id)
        row = self._connection.execute(
            f"SELECT {_COLUMNS} FROM core.tax_codes WHERE tenant_id = %s AND {_DEFAULT_COLUMN[side]} AND active", (tenant_id,)).fetchone()
        return _row(row) if row else None

    def default_rate(self, *, tenant_id: str, side: str, legacy_rate: Decimal | None = None) -> Decimal | None:
        """The rate new lines take on this side, or None when the tenant has no default code (callers then
        keep their own stored default). `legacy_rate` is the caller's stored rate, adopted if the catalogue
        is still empty."""
        if legacy_rate is not None and side in SIDES:
            self._ensure_defaults(tenant_id, {side: legacy_rate})
        code = self.default_code(tenant_id=tenant_id, side=side)
        return code["rate"] if code else None

    def create_code(self, *, tenant_id: str, actor_id: str, code: str, name_fr: str, name_en: str = "", rate: object = 0,
                    applies_to: str = "both", exempt: bool = False) -> Result[dict[str, Any]]:
        valid = validate(code, name_fr, name_en, rate, applies_to, exempt)
        if isinstance(valid, Err):
            return valid
        v = valid.value
        self._ensure_defaults(tenant_id)
        if self._connection.execute("SELECT 1 FROM core.tax_codes WHERE tenant_id = %s AND code = %s", (tenant_id, v.code)).fetchone():
            return Err("TAX_CODE_EXISTS", f"a tax code {v.code} already exists", f"un code de taxe {v.code} existe déjà")
        code_id = str(ULID())
        self._connection.execute(
            "INSERT INTO core.tax_codes (id, tenant_id, code, name_fr, name_en, rate, applies_to, exempt) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (code_id, tenant_id, v.code, v.name_fr, v.name_en, v.rate, v.applies_to, v.exempt),
        )
        record_audit(self._connection, tenant_id=tenant_id, actor_id=actor_id, action="tax_code.created", entity_type="tax_code",
                     entity_id=code_id, payload={"code": v.code, "rate": str(v.rate), "applies_to": v.applies_to, "exempt": v.exempt})
        return Ok(self.get_code(tenant_id=tenant_id, code_id=code_id))

    def update_code(self, *, tenant_id: str, actor_id: str, code_id: str, name_fr: str | None = None, name_en: str | None = None,
                    rate: object | None = None, applies_to: str | None = None, exempt: bool | None = None,
                    active: bool | None = None) -> Result[dict[str, Any]]:
        """Changing a code never rewrites documents already issued: their lines keep the rate they were given."""
        current = self.get_code(tenant_id=tenant_id, code_id=code_id)
        if current is None:
            return Err("NOT_FOUND", f"tax code {code_id} not found", f"code de taxe {code_id} introuvable")
        valid = validate(current["code"], name_fr or current["name_fr"], name_en or current["name_en"],
                         current["rate"] if rate is None else rate, applies_to or current["applies_to"],
                         current["exempt"] if exempt is None else exempt)
        if isinstance(valid, Err):
            return valid
        v = valid.value
        new_active = current["active"] if active is None else active
        for side in SIDES:
            if current[_DEFAULT_COLUMN[side]] and (not new_active or not applies_to_side(v.applies_to, side)):
                return Err("TAX_CODE_IS_DEFAULT", f"{v.code} is the default for {side}; pick another default first",
                           f"{v.code} est le code par défaut ({'ventes' if side == 'sales' else 'achats'}) ; choisissez-en un autre d'abord")
        self._connection.execute(
            "UPDATE core.tax_codes SET name_fr = %s, name_en = %s, rate = %s, applies_to = %s, exempt = %s, active = %s "
            "WHERE tenant_id = %s AND id = %s",
            (v.name_fr, v.name_en, v.rate, v.applies_to, v.exempt, new_active, tenant_id, code_id),
        )
        record_audit(self._connection, tenant_id=tenant_id, actor_id=actor_id, action="tax_code.updated", entity_type="tax_code",
                     entity_id=code_id, payload={"code": v.code, "rate": str(v.rate), "applies_to": v.applies_to,
                                                 "exempt": v.exempt, "active": new_active})
        return Ok(self.get_code(tenant_id=tenant_id, code_id=code_id))

    def set_default(self, *, tenant_id: str, actor_id: str, code_id: str, side: str) -> Result[dict[str, Any]]:
        if side not in SIDES:
            return Err("INVALID_SIDE", "side is sales or purchase", "le côté est ventes ou achats")
        code = self.get_code(tenant_id=tenant_id, code_id=code_id)
        if code is None:
            return Err("NOT_FOUND", f"tax code {code_id} not found", f"code de taxe {code_id} introuvable")
        if not code["active"] or not applies_to_side(code["applies_to"], side):
            return Err("INVALID_TAX_CODE", f"{code['code']} cannot be the default for {side}",
                       f"{code['code']} ne peut pas être le code par défaut ({'ventes' if side == 'sales' else 'achats'})")
        column = _DEFAULT_COLUMN[side]
        # Clear first: the partial unique index allows one default per side.
        self._connection.execute(f"UPDATE core.tax_codes SET {column} = FALSE WHERE tenant_id = %s AND {column}", (tenant_id,))
        self._connection.execute(f"UPDATE core.tax_codes SET {column} = TRUE WHERE tenant_id = %s AND id = %s", (tenant_id, code_id))
        record_audit(self._connection, tenant_id=tenant_id, actor_id=actor_id, action="tax_code.default_set", entity_type="tax_code",
                     entity_id=code_id, payload={"side": side, "code": code["code"], "rate": str(code["rate"])})
        return Ok(self.get_code(tenant_id=tenant_id, code_id=code_id))

    def set_default_rate(self, *, tenant_id: str, actor_id: str, side: str, rate: Decimal) -> Result[dict[str, Any]]:
        """Make `rate` the default for `side`: the active non-exempt code with that rate, or a new one. This is
        how a module's older 'default VAT rate' setting stays the same truth as the catalogue."""
        self._ensure_defaults(tenant_id)
        rate = Decimal(str(rate)).quantize(Decimal("0.01"))
        existing = next((c for c in self.list_codes(tenant_id=tenant_id, side=side)
                         if c["rate"] == rate and not c["exempt"]), None)
        if existing is None:
            label = f"{rate.normalize():f}"
            made = self.create_code(tenant_id=tenant_id, actor_id=actor_id, code=f"TVA{label}", name_fr=f"TVA {label} %",
                                    name_en=f"VAT {label} %", rate=rate, applies_to="both")
            if isinstance(made, Err):
                return made
            existing = made.value
        return self.set_default(tenant_id=tenant_id, actor_id=actor_id, code_id=existing["id"], side=side)
