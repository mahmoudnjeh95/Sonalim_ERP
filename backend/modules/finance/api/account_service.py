"""The chart of accounts and the journals of a tenant, as the screens list and edit them.

An account's number never changes once created (lines reference it); everything else can be
edited behind finance.admin_accounts."""
from __future__ import annotations

import psycopg

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from modules.finance.domain.ledger import Account, validate_account

ACCOUNT_KEYS = ("code", "name", "class_no", "account_type", "is_postable", "parent_code")
JOURNAL_KEYS = ("code", "name", "journal_type")


def account_dict(account: Account) -> dict:
    return {key: getattr(account, key) for key in ACCOUNT_KEYS}


class AccountService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def list_accounts(self, *, tenant_id: str) -> list[dict]:
        rows = self._connection.execute(
            """
            SELECT code, name, class_no, account_type, is_postable, parent_code
            FROM finance.accounts WHERE tenant_id = %s ORDER BY code
            """,
            (tenant_id,),
        ).fetchall()
        return [dict(zip(ACCOUNT_KEYS, row)) for row in rows]

    def list_journals(self, *, tenant_id: str) -> list[dict]:
        rows = self._connection.execute(
            "SELECT code, name, journal_type FROM finance.journals WHERE tenant_id = %s ORDER BY code", (tenant_id,)
        ).fetchall()
        return [dict(zip(JOURNAL_KEYS, row)) for row in rows]

    def _get(self, tenant_id: str, code: str | None, *, lock: bool = False) -> Account | None:
        if not code:
            return None
        row = self._connection.execute(
            """
            SELECT code, name, class_no, account_type, is_postable, parent_code
            FROM finance.accounts WHERE tenant_id = %s AND code = %s
            """
            + (" FOR UPDATE" if lock else ""),
            (tenant_id, code),
        ).fetchone()
        return None if row is None else Account(*row)

    def create_account(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        code: str,
        name: str,
        account_type: str,
        is_postable: bool = True,
        parent_code: str | None = None,
    ) -> Result[dict]:
        code = code.strip()
        parent_code = (parent_code or "").strip() or None
        candidate = Account(
            code=code,
            name=name.strip(),
            class_no=int(code[0]) if code[:1].isdigit() else 0,
            account_type=account_type,
            is_postable=is_postable,
            parent_code=parent_code,
        )
        checked = validate_account(candidate, self._get(tenant_id, parent_code))
        if isinstance(checked, Err):
            return checked
        if self._get(tenant_id, code) is not None:
            return Err("ACCOUNT_EXISTS", f"account {code} already exists", f"le compte {code} existe déjà")
        self._connection.execute(
            """
            INSERT INTO finance.accounts (tenant_id, code, name, class_no, account_type, is_postable, parent_code)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                tenant_id, candidate.code, candidate.name, candidate.class_no,
                candidate.account_type, candidate.is_postable, candidate.parent_code,
            ),
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="account.created",
            entity_type="account",
            entity_id=code,
            payload=account_dict(candidate),
        )
        return Ok(account_dict(candidate))

    def update_account(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        code: str,
        name: str | None = None,
        account_type: str | None = None,
        is_postable: bool | None = None,
        parent_code: str | None = None,
    ) -> Result[dict]:
        """`None` leaves a field unchanged; `parent_code=""` removes the parent."""
        current = self._get(tenant_id, code, lock=True)
        if current is None:
            return Err("NOT_FOUND", f"account {code} not found", f"compte {code} introuvable")
        new_parent = current.parent_code if parent_code is None else (parent_code.strip() or None)
        updated = Account(
            code=current.code,
            name=current.name if name is None else name.strip(),
            class_no=current.class_no,
            account_type=current.account_type if account_type is None else account_type,
            is_postable=current.is_postable if is_postable is None else is_postable,
            parent_code=new_parent,
        )
        checked = validate_account(updated, self._get(tenant_id, new_parent))
        if isinstance(checked, Err):
            return checked
        self._connection.execute(
            """
            UPDATE finance.accounts
            SET name = %s, account_type = %s, is_postable = %s, parent_code = %s, updated_at = NOW()
            WHERE tenant_id = %s AND code = %s
            """,
            (updated.name, updated.account_type, updated.is_postable, updated.parent_code, tenant_id, code),
        )
        changed = {key: getattr(updated, key) for key in ACCOUNT_KEYS if getattr(updated, key) != getattr(current, key)}
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="account.updated",
            entity_type="account",
            entity_id=code,
            payload=changed,
        )
        return Ok(account_dict(updated))
