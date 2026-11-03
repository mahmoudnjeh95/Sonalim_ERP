from __future__ import annotations

import datetime
import json
from decimal import Decimal
from typing import Any

import psycopg
from ulid import ULID

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from modules.treasury.domain.accounts import apply_movement, normalize_iban, validate_account
from modules.treasury.domain.money import check_currency, check_whole

# The manual's offsets, in days relative to the due date. Used until a tenant saves its own;
# nothing is seeded per tenant because the tenant ids do not exist when the migration runs.
DEFAULT_ALERT_OFFSETS: dict[tuple[str, str], int] = {
    ("in", "cheque"): 1,
    ("in", "draft"): 15,
    ("out", "cheque"): -1,
    ("out", "draft"): -15,
}

SETTING_DEFAULTS: dict[str, Any] = {
    "cash_payment_limit": None,
    "prior_year_invoice_cutoff": None,
    # Off until the accountant has confirmed the posting rules and every treasury account's ledger code.
    "ledger_posting_enabled": False,
}

ACCOUNT_COLUMNS = (
    "id, kind, name, currency, account_number, iban, branch_id, operator, phone, opening_balance, "
    "balance, allow_overdraft, ledger_account_code, is_active"
)


def _not_found(what: str, entity_id: str) -> Err:
    return Err("NOT_FOUND", f"{what} {entity_id} not found", f"{what} {entity_id} introuvable")


def _account_dict(row: tuple) -> dict[str, Any]:
    keys = ACCOUNT_COLUMNS.replace(" ", "").split(",")
    return dict(zip(keys, row, strict=True))


class BankService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def list_banks(self, *, tenant_id: str) -> list[dict[str, Any]]:
        banks = self._connection.execute(
            "SELECT id, name, code, swift, country, is_active FROM treasury.banks WHERE tenant_id = %s ORDER BY name",
            (tenant_id,),
        ).fetchall()
        branches = self._connection.execute(
            "SELECT id, bank_id, name, city, address, phone FROM treasury.bank_branches WHERE tenant_id = %s ORDER BY name",
            (tenant_id,),
        ).fetchall()
        by_bank: dict[str, list[dict[str, Any]]] = {}
        for b in branches:
            by_bank.setdefault(b[1], []).append(
                {"id": b[0], "bank_id": b[1], "name": b[2], "city": b[3], "address": b[4], "phone": b[5]}
            )
        return [
            {"id": b[0], "name": b[1], "code": b[2], "swift": b[3], "country": b[4], "is_active": b[5], "branches": by_bank.get(b[0], [])}
            for b in banks
        ]

    def create_bank(self, *, tenant_id: str, actor_id: str, name: str, code: str | None = None,
                    swift: str | None = None, country: str | None = None) -> Result[dict[str, Any]]:
        exists = self._connection.execute(
            "SELECT 1 FROM treasury.banks WHERE tenant_id = %s AND lower(name) = lower(%s)", (tenant_id, name)
        ).fetchone()
        if exists:
            return Err("BANK_DUPLICATE", "a bank with this name already exists", "une banque porte déjà ce nom")
        bank_id = str(ULID())
        self._connection.execute(
            "INSERT INTO treasury.banks (id, tenant_id, name, code, swift, country) VALUES (%s, %s, %s, %s, %s, %s)",
            (bank_id, tenant_id, name, code, swift, country),
        )
        record_audit(self._connection, tenant_id=tenant_id, actor_id=actor_id, action="treasury.bank.created",
                     entity_type="bank", entity_id=bank_id, payload={"name": name})
        return Ok({"id": bank_id, "name": name, "code": code, "swift": swift, "country": country, "is_active": True, "branches": []})

    def set_bank_active(self, *, tenant_id: str, actor_id: str, bank_id: str, is_active: bool) -> Result[None]:
        updated = self._connection.execute(
            "UPDATE treasury.banks SET is_active = %s WHERE id = %s AND tenant_id = %s", (is_active, bank_id, tenant_id)
        ).rowcount
        if not updated:
            return _not_found("bank", bank_id)
        record_audit(self._connection, tenant_id=tenant_id, actor_id=actor_id, action="treasury.bank.active_changed",
                     entity_type="bank", entity_id=bank_id, payload={"is_active": is_active})
        return Ok(None)

    def add_branch(self, *, tenant_id: str, actor_id: str, bank_id: str, name: str, city: str | None = None,
                   address: str | None = None, phone: str | None = None) -> Result[dict[str, Any]]:
        bank = self._connection.execute(
            "SELECT 1 FROM treasury.banks WHERE id = %s AND tenant_id = %s", (bank_id, tenant_id)
        ).fetchone()
        if bank is None:
            return _not_found("bank", bank_id)
        branch_id = str(ULID())
        self._connection.execute(
            "INSERT INTO treasury.bank_branches (id, tenant_id, bank_id, name, city, address, phone) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (branch_id, tenant_id, bank_id, name, city, address, phone),
        )
        record_audit(self._connection, tenant_id=tenant_id, actor_id=actor_id, action="treasury.branch.created",
                     entity_type="bank_branch", entity_id=branch_id, payload={"bank_id": bank_id, "name": name})
        return Ok({"id": branch_id, "bank_id": bank_id, "name": name, "city": city, "address": address, "phone": phone})


class AccountService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def list_accounts(self, *, tenant_id: str, kind: str | None = None, currency: str | None = None,
                      include_inactive: bool = False) -> list[dict[str, Any]]:
        clauses, params = ["tenant_id = %s"], [tenant_id]
        if kind:
            clauses.append("kind = %s")
            params.append(kind)
        if currency:
            clauses.append("currency = %s")
            params.append(currency)
        if not include_inactive:
            clauses.append("is_active")
        rows = self._connection.execute(
            f"SELECT {ACCOUNT_COLUMNS} FROM treasury.accounts WHERE {' AND '.join(clauses)} ORDER BY kind, name", params
        ).fetchall()
        return [_account_dict(r) for r in rows]

    def get_account(self, *, tenant_id: str, account_id: str) -> Result[dict[str, Any]]:
        row = self._connection.execute(
            f"SELECT {ACCOUNT_COLUMNS} FROM treasury.accounts WHERE id = %s AND tenant_id = %s", (account_id, tenant_id)
        ).fetchone()
        if row is None:
            return _not_found("account", account_id)
        return Ok(_account_dict(row))

    def create_account(self, *, tenant_id: str, actor_id: str, kind: str, fields: dict[str, Any]) -> Result[dict[str, Any]]:
        fields = {**fields, "iban": normalize_iban(fields.get("iban"))}
        checked = validate_account(kind, fields, self._format_rules(tenant_id))
        if isinstance(checked, Err):
            return checked
        money = _check_account_money(fields["currency"], fields.get("opening_balance") or 0)
        if isinstance(money, Err):
            return money
        taken = self._number_taken(tenant_id, fields.get("account_number"), fields.get("iban"), exclude_id=None)
        if taken:
            return taken
        if fields.get("branch_id") and not self._branch_exists(tenant_id, fields["branch_id"]):
            return _not_found("branch", fields["branch_id"])

        opening = Decimal(str(fields.get("opening_balance") or 0))
        account_id = str(ULID())
        self._connection.execute(
            """
            INSERT INTO treasury.accounts
                (id, tenant_id, kind, name, currency, account_number, iban, branch_id, operator, phone,
                 opening_balance, balance, allow_overdraft, ledger_account_code)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (account_id, tenant_id, kind, fields["name"], fields["currency"], fields.get("account_number"),
             fields.get("iban"), fields.get("branch_id"), fields.get("operator"), fields.get("phone"),
             opening, opening, bool(fields.get("allow_overdraft", False)), fields.get("ledger_account_code")),
        )
        record_audit(self._connection, tenant_id=tenant_id, actor_id=actor_id, action="treasury.account.created",
                     entity_type="treasury_account", entity_id=account_id,
                     payload={"kind": kind, "name": fields["name"], "currency": fields["currency"]})
        return self.get_account(tenant_id=tenant_id, account_id=account_id)

    def update_account(self, *, tenant_id: str, actor_id: str, account_id: str, changes: dict[str, Any]) -> Result[dict[str, Any]]:
        current = self._connection.execute(
            f"SELECT {ACCOUNT_COLUMNS} FROM treasury.accounts WHERE id = %s AND tenant_id = %s FOR UPDATE",
            (account_id, tenant_id),
        ).fetchone()
        if current is None:
            return _not_found("account", account_id)
        account = _account_dict(current)

        if "opening_balance" in changes and Decimal(str(changes["opening_balance"])) != account["opening_balance"]:
            if self._has_movements(account_id):
                return Err("ACCOUNT_LOCKED", "the opening balance cannot change once the account has movements",
                           "le solde d'ouverture ne peut plus changer une fois que le compte a des mouvements")
        if "currency" in changes and changes["currency"] != account["currency"] and self._has_movements(account_id):
            return Err("ACCOUNT_LOCKED", "the currency cannot change once the account has movements",
                       "la devise ne peut plus changer une fois que le compte a des mouvements")

        merged = {**account, **{k: v for k, v in changes.items() if k in account and k not in ("id", "kind", "balance")}}
        merged["iban"] = normalize_iban(merged.get("iban"))
        checked = validate_account(account["kind"], merged, self._format_rules(tenant_id))
        if isinstance(checked, Err):
            return checked
        money = _check_account_money(merged["currency"], merged["opening_balance"])
        if isinstance(money, Err):
            return money
        taken = self._number_taken(tenant_id, merged.get("account_number"), merged.get("iban"), exclude_id=account_id)
        if taken:
            return taken

        opening = Decimal(str(merged["opening_balance"]))
        # Without movements the balance is the opening balance by definition.
        balance = account["balance"] if self._has_movements(account_id) else opening
        self._connection.execute(
            """
            UPDATE treasury.accounts SET name = %s, currency = %s, account_number = %s, iban = %s, branch_id = %s,
                operator = %s, phone = %s, opening_balance = %s, balance = %s, allow_overdraft = %s,
                ledger_account_code = %s, is_active = %s
            WHERE id = %s AND tenant_id = %s
            """,
            (merged["name"], merged["currency"], merged.get("account_number"), merged.get("iban"), merged.get("branch_id"),
             merged.get("operator"), merged.get("phone"), opening, balance, merged["allow_overdraft"],
             merged.get("ledger_account_code"), merged["is_active"], account_id, tenant_id),
        )
        record_audit(self._connection, tenant_id=tenant_id, actor_id=actor_id, action="treasury.account.updated",
                     entity_type="treasury_account", entity_id=account_id,
                     payload={k: str(v) for k, v in changes.items()})
        return self.get_account(tenant_id=tenant_id, account_id=account_id)

    def delete_account(self, *, tenant_id: str, actor_id: str, account_id: str) -> Result[None]:
        if self._connection.execute(
            "SELECT 1 FROM treasury.accounts WHERE id = %s AND tenant_id = %s", (account_id, tenant_id)
        ).fetchone() is None:
            return _not_found("account", account_id)
        if self._has_movements(account_id):
            return Err("ACCOUNT_HAS_MOVEMENTS", "an account with movements cannot be deleted; deactivate it instead",
                       "un compte avec des mouvements ne peut pas être supprimé ; désactivez-le")
        self._connection.execute("DELETE FROM treasury.accounts WHERE id = %s AND tenant_id = %s", (account_id, tenant_id))
        record_audit(self._connection, tenant_id=tenant_id, actor_id=actor_id, action="treasury.account.deleted",
                     entity_type="treasury_account", entity_id=account_id, payload={})
        return Ok(None)

    def list_movements(self, *, tenant_id: str, account_id: str, date_from: datetime.date | None = None,
                       date_to: datetime.date | None = None) -> list[dict[str, Any]]:
        clauses, params = ["tenant_id = %s", "account_id = %s"], [tenant_id, account_id]
        if date_from:
            clauses.append("occurred_on >= %s")
            params.append(date_from)
        if date_to:
            clauses.append("occurred_on <= %s")
            params.append(date_to)
        rows = self._connection.execute(
            "SELECT id, amount, balance_after, source_type, source_id, occurred_on, note, created_at "
            f"FROM treasury.account_movements WHERE {' AND '.join(clauses)} ORDER BY occurred_on, created_at, id",
            params,
        ).fetchall()
        return [
            {"id": r[0], "amount": r[1], "balance_after": r[2], "source_type": r[3], "source_id": r[4],
             "occurred_on": r[5], "note": r[6], "created_at": r[7]}
            for r in rows
        ]

    # ---- helpers ----
    def _has_movements(self, account_id: str) -> bool:
        return self._connection.execute(
            "SELECT 1 FROM treasury.account_movements WHERE account_id = %s LIMIT 1", (account_id,)
        ).fetchone() is not None

    def _branch_exists(self, tenant_id: str, branch_id: str) -> bool:
        return self._connection.execute(
            "SELECT 1 FROM treasury.bank_branches WHERE id = %s AND tenant_id = %s", (branch_id, tenant_id)
        ).fetchone() is not None

    def _format_rules(self, tenant_id: str) -> list[dict[str, str]]:
        rows = self._connection.execute(
            "SELECT kind, regex, hint_en, hint_fr FROM treasury.account_format_rules WHERE tenant_id = %s", (tenant_id,)
        ).fetchall()
        return [{"kind": r[0], "regex": r[1], "hint_en": r[2], "hint_fr": r[3]} for r in rows]

    def _number_taken(self, tenant_id: str, number: str | None, iban: str | None, *, exclude_id: str | None) -> Err | None:
        for column, value in (("account_number", number), ("iban", iban)):
            if not value:
                continue
            row = self._connection.execute(
                f"SELECT 1 FROM treasury.accounts WHERE tenant_id = %s AND {column} = %s AND (%s::text IS NULL OR id <> %s)",
                (tenant_id, value, exclude_id, exclude_id),
            ).fetchone()
            if row:
                return Err("ACCOUNT_NUMBER_DUPLICATE", f"an account with this {column.replace('_', ' ')} already exists",
                           "un compte avec ce numéro existe déjà")
        return None


class AccountMovementService:
    """The only writer of account balances. Receipts, disbursements and instruments all go through here."""

    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def post(self, *, tenant_id: str, actor_id: str, account_id: str, signed_amount: Decimal, source_type: str,
             source_id: str | None, occurred_on: datetime.date, note: str | None = None) -> Result[Decimal]:
        row = self._connection.execute(
            "SELECT kind, balance, allow_overdraft, is_active FROM treasury.accounts WHERE id = %s AND tenant_id = %s FOR UPDATE",
            (account_id, tenant_id),
        ).fetchone()
        if row is None:
            return _not_found("account", account_id)
        kind, balance, allow_overdraft, is_active = row
        if not is_active:
            return Err("ACCOUNT_INACTIVE", "this account is deactivated", "ce compte est désactivé")
        moved = apply_movement(balance, signed_amount, allow_negative=bool(allow_overdraft and kind == "bank"))
        if isinstance(moved, Err):
            return moved
        self._connection.execute(
            "UPDATE treasury.accounts SET balance = %s WHERE id = %s", (moved.value, account_id)
        )
        self._connection.execute(
            "INSERT INTO treasury.account_movements "
            "(id, tenant_id, account_id, amount, balance_after, source_type, source_id, occurred_on, note, created_by) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (str(ULID()), tenant_id, account_id, signed_amount, moved.value, source_type, source_id, occurred_on, note, actor_id),
        )
        record_audit(self._connection, tenant_id=tenant_id, actor_id=actor_id, action="treasury.account.movement",
                     entity_type="treasury_account", entity_id=account_id,
                     payload={"amount": str(signed_amount), "source_type": source_type, "source_id": source_id})
        return Ok(moved.value)


def _check_account_money(currency: str, opening_balance: Any) -> Result[None]:
    checked = check_currency(currency)
    if isinstance(checked, Err):
        return checked
    return check_whole(Decimal(str(opening_balance)))


class SettingsService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def get_settings(self, *, tenant_id: str) -> dict[str, Any]:
        rows = self._connection.execute(
            "SELECT key, value_json FROM treasury.settings WHERE tenant_id = %s", (tenant_id,)
        ).fetchall()
        return {**SETTING_DEFAULTS, **{k: v for k, v in rows}}

    def set_setting(self, *, tenant_id: str, actor_id: str, key: str, value: Any) -> Result[None]:
        if key not in SETTING_DEFAULTS:
            return Err("UNKNOWN_SETTING", f"unknown treasury setting {key}", f"paramètre de trésorerie inconnu {key}")
        if key == "ledger_posting_enabled" and not isinstance(value, bool):
            return Err("INVALID_SETTING", "ledger_posting_enabled must be true or false", "ledger_posting_enabled doit valoir vrai ou faux")
        if key == "cash_payment_limit" and value is not None and Decimal(str(value)) <= 0:
            return Err("INVALID_SETTING", "the cash payment limit must be positive or empty", "le plafond d'espèces doit être positif ou vide")
        if key == "cash_payment_limit" and value is not None:
            whole = check_whole(Decimal(str(value)))
            if isinstance(whole, Err):
                return whole
        self._connection.execute(
            "INSERT INTO treasury.settings (tenant_id, key, value_json) VALUES (%s, %s, %s::jsonb) "
            "ON CONFLICT (tenant_id, key) DO UPDATE SET value_json = EXCLUDED.value_json",
            (tenant_id, key, json.dumps(value)),
        )
        record_audit(self._connection, tenant_id=tenant_id, actor_id=actor_id, action="treasury.setting.changed",
                     entity_type="treasury_setting", entity_id=key, payload={"value": value})
        return Ok(None)

    def list_alert_rules(self, *, tenant_id: str) -> list[dict[str, Any]]:
        saved = {
            (r[0], r[1]): r[2]
            for r in self._connection.execute(
                "SELECT direction, method, offset_days FROM treasury.alert_rules WHERE tenant_id = %s", (tenant_id,)
            ).fetchall()
        }
        return [
            {"direction": d, "method": m, "offset_days": saved.get((d, m), default), "is_default": (d, m) not in saved}
            for (d, m), default in DEFAULT_ALERT_OFFSETS.items()
        ]

    def set_alert_rule(self, *, tenant_id: str, actor_id: str, direction: str, method: str, offset_days: int) -> Result[None]:
        if (direction, method) not in DEFAULT_ALERT_OFFSETS:
            return Err("INVALID_ALERT_RULE", "unknown direction/method pair", "couple sens/mode inconnu")
        self._connection.execute(
            "INSERT INTO treasury.alert_rules (tenant_id, direction, method, offset_days) VALUES (%s, %s, %s, %s) "
            "ON CONFLICT (tenant_id, direction, method) DO UPDATE SET offset_days = EXCLUDED.offset_days",
            (tenant_id, direction, method, offset_days),
        )
        record_audit(self._connection, tenant_id=tenant_id, actor_id=actor_id, action="treasury.alert_rule.changed",
                     entity_type="treasury_alert_rule", entity_id=f"{direction}:{method}", payload={"offset_days": offset_days})
        return Ok(None)
