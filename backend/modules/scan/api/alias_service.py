"""The plant's own writing, learned: what a code on the fiche means in the system.

An alias is learned when a user, reviewing a scan, picks a value other than the one the
scan resolved. The next scan resolves the same writing to that value first. Admins can
correct or remove one from the Dictionnaire screen.
"""
from __future__ import annotations

import psycopg
from ulid import ULID

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from modules.scan.domain.text import normalize
from modules.scan.domain.vocabulary import KINDS

_COLUMNS = "id, kind, raw_text_normalized, raw_text_example, target_value, use_count, updated_at"
_NAMES = tuple(n.strip() for n in _COLUMNS.split(","))
_NOT_FOUND = Err("NOT_FOUND", "dictionary entry not found", "entrée du dictionnaire introuvable")


def _row(values) -> dict:
    row = dict(zip(_NAMES, values))
    row["updated_at"] = row["updated_at"].isoformat()
    return row


class ScanAliasService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def alias_map(self, *, tenant_id: str) -> dict[tuple[str, str], str]:
        rows = self._connection.execute(
            "SELECT kind, raw_text_normalized, target_value FROM scan.scan_aliases WHERE tenant_id = %s", (tenant_id,)
        ).fetchall()
        return {(kind, key): value for kind, key, value in rows}

    def list_aliases(self, *, tenant_id: str, kind: str | None = None) -> list[dict]:
        clause, params = ("tenant_id = %s", [tenant_id]) if kind is None else ("tenant_id = %s AND kind = %s", [tenant_id, kind])
        rows = self._connection.execute(
            f"SELECT {_COLUMNS} FROM scan.scan_aliases WHERE {clause} ORDER BY kind, raw_text_normalized", params
        ).fetchall()
        return [_row(r) for r in rows]

    def learn(self, *, tenant_id: str, actor_id: str, kind: str, read_text: str, target_value: str) -> None:
        key = normalize(read_text)
        if kind not in KINDS or not key or not str(target_value).strip():
            return
        alias_id = self._connection.execute(
            """
            INSERT INTO scan.scan_aliases (id, tenant_id, kind, raw_text_normalized, raw_text_example, target_value, created_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (tenant_id, kind, raw_text_normalized) DO UPDATE
            SET target_value = EXCLUDED.target_value, raw_text_example = EXCLUDED.raw_text_example,
                use_count = scan.scan_aliases.use_count + 1, updated_at = NOW()
            RETURNING id
            """,
            (str(ULID()), tenant_id, kind, key, read_text.strip(), str(target_value), actor_id),
        ).fetchone()[0]
        record_audit(
            self._connection, tenant_id=tenant_id, actor_id=actor_id, action="scan_alias.learned",
            entity_type="scan_alias", entity_id=alias_id,
            payload={"kind": kind, "raw_text": read_text.strip(), "target_value": str(target_value)},
        )

    def _read(self, tenant_id: str, alias_id: str) -> dict | None:
        row = self._connection.execute(
            f"SELECT {_COLUMNS} FROM scan.scan_aliases WHERE id = %s AND tenant_id = %s", (alias_id, tenant_id)
        ).fetchone()
        return _row(row) if row else None

    def update_alias(self, *, tenant_id: str, actor_id: str, alias_id: str, target_value: str) -> Result[dict]:
        before = self._read(tenant_id, alias_id)
        if before is None:
            return _NOT_FOUND
        value = (target_value or "").strip()
        if not value:
            return Err("INVALID_VALUE", "a dictionary entry needs a value", "une entrée du dictionnaire a besoin d'une valeur")
        self._connection.execute(
            "UPDATE scan.scan_aliases SET target_value = %s, updated_at = NOW() WHERE id = %s AND tenant_id = %s",
            (value, alias_id, tenant_id),
        )
        record_audit(
            self._connection, tenant_id=tenant_id, actor_id=actor_id, action="scan_alias.updated",
            entity_type="scan_alias", entity_id=alias_id, payload={"from": before["target_value"], "to": value},
        )
        return Ok(self._read(tenant_id, alias_id))

    def delete_alias(self, *, tenant_id: str, actor_id: str, alias_id: str) -> Result[dict]:
        before = self._read(tenant_id, alias_id)
        if before is None:
            return _NOT_FOUND
        self._connection.execute("DELETE FROM scan.scan_aliases WHERE id = %s AND tenant_id = %s", (alias_id, tenant_id))
        record_audit(
            self._connection, tenant_id=tenant_id, actor_id=actor_id, action="scan_alias.deleted",
            entity_type="scan_alias", entity_id=alias_id,
            payload={"kind": before["kind"], "raw_text": before["raw_text_example"], "target_value": before["target_value"]},
        )
        return Ok(before)
