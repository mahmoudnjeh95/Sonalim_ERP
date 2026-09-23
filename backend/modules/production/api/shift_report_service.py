"""One report per line, date and shift, saved and submitted section by section.

The service owns what a caller can rely on: section states move only through the
rules in `domain/shift_report.py`, every submit and every edit of a submitted
section freezes a revision, a validated shift takes no more edits, and each state
change is audited. It never commits; the caller does, as with every service here.
"""
from __future__ import annotations

import datetime
from typing import Any

import psycopg
from psycopg.types.json import Jsonb
from ulid import ULID

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from modules.production.api.shift_sections import (
    SECTIONS,
    check_ready_to_submit,
    clear_section_rows,
    load_section,
    save_section_rows,
    section_is_empty,
)
from modules.production.api.waste_type_service import custom_waste_categories
from modules.production.domain.lot_number import default_lot_number
from modules.production.domain.shift_report import (
    SECTION_KEYS,
    can_declare_nothing,
    can_submit,
    derive_shift_status,
    status_after_save,
)

_HEADER = """
    id, work_center_id, report_date, shift, team, conducteur, agent_fabrication, machiniste, aide_machiniste,
    status, revision, created_by, submitted_at, validated_by, validated_at, rejection_reason
"""
_HEADER_NAMES = (
    "id", "work_center_id", "report_date", "shift", "team", "conducteur", "agent_fabrication", "machiniste",
    "aide_machiniste", "status", "revision", "created_by", "submitted_at", "validated_by", "validated_at",
    "rejection_reason",
)
# The header fields a team may edit; status and validation fields are never set from here.
_EDITABLE_HEADER = ("team", "conducteur", "agent_fabrication", "machiniste", "aide_machiniste")

_SECTION_STATE = "section_key, status, revision, revised_after_submit, submitted_by, submitted_at, return_reason"


def _iso(value: Any) -> Any:
    return value.isoformat() if isinstance(value, (datetime.datetime, datetime.date)) else value


def _header_dict(row: tuple) -> dict:
    return {name: _iso(value) for name, value in zip(_HEADER_NAMES, row)}


def _section_dict(row: tuple) -> dict:
    key, status, revision, revised, submitted_by, submitted_at, return_reason = row
    return {
        "key": key,
        "status": status,
        "revision": revision,
        "revised_after_submit": revised,
        "submitted_by": submitted_by,
        "submitted_at": _iso(submitted_at),
        "return_reason": return_reason,
    }


class ShiftReportService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    # ---- reading -----------------------------------------------------------

    def _load_header(self, tenant_id: str, shift_report_id: str) -> dict | None:
        row = self._connection.execute(
            f"SELECT {_HEADER} FROM production.shift_reports WHERE id = %s AND tenant_id = %s",
            (shift_report_id, tenant_id),
        ).fetchone()
        return _header_dict(row) if row else None

    def _load_sections(self, tenant_id: str, shift_report_id: str) -> list[dict]:
        rows = self._connection.execute(
            f"SELECT {_SECTION_STATE} FROM production.shift_report_sections "
            f"WHERE shift_report_id = %s AND tenant_id = %s",
            (shift_report_id, tenant_id),
        ).fetchall()
        by_key = {r[0]: _section_dict(r) for r in rows}
        # The screen's order, and only sections this code knows about.
        return [by_key[k] for k in SECTION_KEYS if k in by_key]

    def get_shift(self, *, tenant_id: str, shift_report_id: str) -> Result[dict]:
        header = self._load_header(tenant_id, shift_report_id)
        if header is None:
            return Err("NOT_FOUND", f"shift report {shift_report_id} not found")
        sections = self._load_sections(tenant_id, shift_report_id)
        for section in sections:
            section["payload"] = load_section(
                self._connection, tenant_id=tenant_id, shift_report_id=shift_report_id, section_key=section["key"]
            )
        report_date = datetime.date.fromisoformat(header["report_date"])
        default_lot = default_lot_number(team=header["team"], report_date=report_date)
        return Ok({**header, "default_lot_number": default_lot, "sections": sections})

    def list_shifts(
        self,
        *,
        tenant_id: str,
        report_date: datetime.date | None = None,
        work_center_id: str | None = None,
        status: str | None = None,
        of_id: str | None = None,
    ) -> list[dict]:
        clauses, params = ["tenant_id = %s"], [tenant_id]
        for column, value in (("report_date", report_date), ("work_center_id", work_center_id), ("status", status)):
            if value is not None:
                clauses.append(f"{column} = %s")
                params.append(value)
        if of_id is not None:
            # The shifts that hold a production or packing row of this order.
            clauses.append(
                "id IN (SELECT shift_report_id FROM production.shift_runs WHERE tenant_id = %s AND of_id = %s "
                "UNION SELECT shift_report_id FROM production.shift_packing_rows WHERE tenant_id = %s AND of_id = %s)"
            )
            params.extend([tenant_id, of_id, tenant_id, of_id])
        rows = self._connection.execute(
            f"SELECT {_HEADER} FROM production.shift_reports WHERE {' AND '.join(clauses)} "
            f"ORDER BY report_date DESC, shift, id",
            tuple(params),
        ).fetchall()
        shifts = []
        for row in rows:
            header = _header_dict(row)
            shifts.append({**header, "sections": self._load_sections(tenant_id, header["id"])})
        return shifts

    def list_revisions(self, *, tenant_id: str, shift_report_id: str, section_key: str) -> Result[list[dict]]:
        if self._load_header(tenant_id, shift_report_id) is None:
            return Err("NOT_FOUND", f"shift report {shift_report_id} not found")
        rows = self._connection.execute(
            """
            SELECT revision, snapshot, reason, actor_id, created_at, edited_by_validator
            FROM production.shift_section_revisions
            WHERE shift_report_id = %s AND tenant_id = %s AND section_key = %s
            ORDER BY revision DESC
            """,
            (shift_report_id, tenant_id, section_key),
        ).fetchall()
        return Ok(
            [
                {
                    "revision": rev, "snapshot": snap, "reason": reason, "actor_id": actor, "created_at": _iso(at),
                    "edited_by_validator": by_validator,
                }
                for rev, snap, reason, actor, at, by_validator in rows
            ]
        )

    # ---- opening and header ------------------------------------------------

    def open_shift(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        work_center_id: str,
        report_date: datetime.date,
        shift: str,
        team: str | None = None,
    ) -> Result[dict]:
        """Find or create the report for this line, date and shift, with all its sections empty."""
        shift = (shift or "").strip()
        if not shift:
            return Err("INVALID_VALUE", "a shift is required")
        line = self._connection.execute(
            "SELECT 1 FROM production.work_centers WHERE id = %s AND tenant_id = %s", (work_center_id, tenant_id)
        ).fetchone()
        if line is None:
            return Err("NOT_FOUND", f"work center {work_center_id} not found")

        existing = self._connection.execute(
            "SELECT id FROM production.shift_reports WHERE tenant_id = %s AND work_center_id = %s "
            "AND report_date = %s AND shift = %s",
            (tenant_id, work_center_id, report_date, shift),
        ).fetchone()
        if existing is not None:
            return Ok(self._load_header(tenant_id, existing[0]))

        shift_id = str(ULID())
        self._connection.execute(
            """
            INSERT INTO production.shift_reports (id, tenant_id, work_center_id, report_date, shift, team, created_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (shift_id, tenant_id, work_center_id, report_date, shift, team, actor_id),
        )
        for key in SECTION_KEYS:
            self._connection.execute(
                "INSERT INTO production.shift_report_sections (shift_report_id, tenant_id, section_key) VALUES (%s, %s, %s)",
                (shift_id, tenant_id, key),
            )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="shift_report.opened",
            entity_type="shift_report",
            entity_id=shift_id,
            payload={"work_center_id": work_center_id, "report_date": report_date.isoformat(), "shift": shift},
        )
        return Ok(self._load_header(tenant_id, shift_id))

    def update_header(self, *, tenant_id: str, actor_id: str, shift_report_id: str, fields: dict) -> Result[dict]:
        header = self._load_header(tenant_id, shift_report_id)
        if header is None:
            return Err("NOT_FOUND", f"shift report {shift_report_id} not found")
        if header["status"] == "validated":
            return Err("NOT_EDITABLE", "a validated shift report can no longer be edited")
        changes = {k: (str(v).strip() or None) if v is not None else None for k, v in fields.items() if k in _EDITABLE_HEADER}
        if changes:
            self._connection.execute(
                f"UPDATE production.shift_reports SET {', '.join(f'{k} = %s' for k in changes)}, updated_at = NOW() "
                f"WHERE id = %s AND tenant_id = %s",
                (*changes.values(), shift_report_id, tenant_id),
            )
            record_audit(
                self._connection,
                tenant_id=tenant_id,
                actor_id=actor_id,
                action="shift_report.header_updated",
                entity_type="shift_report",
                entity_id=shift_report_id,
                payload={"fields": sorted(changes)},
            )
        return Ok(self._load_header(tenant_id, shift_report_id))

    # ---- sections ----------------------------------------------------------

    def _editable_section(
        self, tenant_id: str, shift_report_id: str, section_key: str
    ) -> Result[tuple[dict, dict]]:
        """(header, section) for a section that may be changed, or the reason it may not."""
        if section_key not in SECTIONS:
            return Err("INVALID_SECTION", f"unknown section {section_key!r}")
        header = self._load_header(tenant_id, shift_report_id)
        if header is None:
            return Err("NOT_FOUND", f"shift report {shift_report_id} not found")
        if header["status"] == "validated":
            return Err("NOT_EDITABLE", "a validated shift report can no longer be edited")
        row = self._connection.execute(
            f"SELECT {_SECTION_STATE} FROM production.shift_report_sections "
            f"WHERE shift_report_id = %s AND tenant_id = %s AND section_key = %s",
            (shift_report_id, tenant_id, section_key),
        ).fetchone()
        if row is None:
            # A section added to the code after this shift was opened.
            self._connection.execute(
                "INSERT INTO production.shift_report_sections (shift_report_id, tenant_id, section_key) VALUES (%s, %s, %s)",
                (shift_report_id, tenant_id, section_key),
            )
            row = self._connection.execute(
                f"SELECT {_SECTION_STATE} FROM production.shift_report_sections "
                f"WHERE shift_report_id = %s AND tenant_id = %s AND section_key = %s",
                (shift_report_id, tenant_id, section_key),
            ).fetchone()
        return Ok((header, _section_dict(row)))

    def _freeze_revision(
        self, tenant_id: str, actor_id: str, shift_report_id: str, section_key: str, reason: str | None,
        edited_by_validator: bool = False
    ) -> int:
        """Snapshot the section as it stands now under the next revision number."""
        revision = self._connection.execute(
            "SELECT COALESCE(MAX(revision), 0) + 1 FROM production.shift_section_revisions "
            "WHERE shift_report_id = %s AND section_key = %s",
            (shift_report_id, section_key),
        ).fetchone()[0]
        snapshot = load_section(
            self._connection, tenant_id=tenant_id, shift_report_id=shift_report_id, section_key=section_key
        )
        self._connection.execute(
            """
            INSERT INTO production.shift_section_revisions
                (id, tenant_id, shift_report_id, section_key, revision, snapshot, reason, actor_id, edited_by_validator)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (str(ULID()), tenant_id, shift_report_id, section_key, revision, Jsonb(snapshot), reason, actor_id, edited_by_validator),
        )
        return revision

    def _refresh_shift_status(self, tenant_id: str, shift_report_id: str) -> None:
        header = self._load_header(tenant_id, shift_report_id)
        statuses = [s["status"] for s in self._load_sections(tenant_id, shift_report_id)]
        new_status = derive_shift_status(header["status"], statuses)
        if new_status == header["status"]:
            return
        self._connection.execute(
            "UPDATE production.shift_reports SET status = %s, updated_at = NOW(), "
            "submitted_at = CASE WHEN %s = 'submitted' THEN NOW() ELSE submitted_at END "
            "WHERE id = %s AND tenant_id = %s",
            (new_status, new_status, shift_report_id, tenant_id),
        )

    def list_section_states(self, *, tenant_id: str, shift_report_id: str) -> list[dict]:
        """Each section's state (status, revision, flags) without its rows, in screen order."""
        return self._load_sections(tenant_id, shift_report_id)

    def refresh_shift_status(self, *, tenant_id: str, shift_report_id: str) -> None:
        """Re-derive the shift's status from its sections (used after a validator returns some)."""
        self._refresh_shift_status(tenant_id, shift_report_id)

    def _section_result(self, tenant_id: str, shift_report_id: str, section_key: str) -> dict:
        section = next(s for s in self._load_sections(tenant_id, shift_report_id) if s["key"] == section_key)
        shift_status = self._load_header(tenant_id, shift_report_id)["status"]
        return {**section, "shift_status": shift_status}

    def save_section(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        shift_report_id: str,
        section_key: str,
        payload: dict,
        reason: str | None = None,
    ) -> Result[dict]:
        """Store a section's rows. A submitted section stays submitted and gains a revision."""
        found = self._editable_section(tenant_id, shift_report_id, section_key)
        if isinstance(found, Err):
            return found
        _, section = found.value
        saved = save_section_rows(
            self._connection,
            tenant_id=tenant_id,
            shift_report_id=shift_report_id,
            section_key=section_key,
            payload=payload,
            custom_waste_categories={
                report_type: custom_waste_categories(self._connection, tenant_id=tenant_id, report_type=report_type)
                for report_type in ("daily", "conditionnement")
            },
        )
        if isinstance(saved, Err):
            return saved

        new_status, edited_after_submit = status_after_save(section["status"])
        revision = section["revision"]
        if edited_after_submit:
            revision = self._freeze_revision(tenant_id, actor_id, shift_report_id, section_key, reason)
        self._connection.execute(
            """
            UPDATE production.shift_report_sections
            SET status = %s, revision = %s, revised_after_submit = revised_after_submit OR %s, updated_at = NOW()
            WHERE shift_report_id = %s AND tenant_id = %s AND section_key = %s
            """,
            (new_status, revision, edited_after_submit, shift_report_id, tenant_id, section_key),
        )
        self._refresh_shift_status(tenant_id, shift_report_id)
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="shift_report.section_saved",
            entity_type="shift_report",
            entity_id=shift_report_id,
            payload={"section": section_key, "revision": revision, "edited_after_submit": edited_after_submit},
        )
        return Ok(self._section_result(tenant_id, shift_report_id, section_key))

    def submit_section(
        self, *, tenant_id: str, actor_id: str, shift_report_id: str, section_key: str
    ) -> Result[dict]:
        found = self._editable_section(tenant_id, shift_report_id, section_key)
        if isinstance(found, Err):
            return found
        _, section = found.value
        if not can_submit(section["status"]):
            return Err(
                "INVALID_TRANSITION",
                f"a section that is {section['status']} cannot be submitted"
                + (" - save it, or say there is nothing to report" if section["status"] == "empty" else ""),
            )
        payload = load_section(
            self._connection, tenant_id=tenant_id, shift_report_id=shift_report_id, section_key=section_key
        )
        if section_is_empty(payload):
            return Err("EMPTY_SECTION", "an empty section is submitted as 'nothing to report'")
        ready = check_ready_to_submit(section_key, payload)
        if isinstance(ready, Err):
            return ready

        revision = self._freeze_revision(tenant_id, actor_id, shift_report_id, section_key, None)
        self._connection.execute(
            """
            UPDATE production.shift_report_sections
            SET status = 'submitted', revision = %s, revised_after_submit = FALSE, return_reason = NULL,
                submitted_by = %s, submitted_at = NOW(), updated_at = NOW()
            WHERE shift_report_id = %s AND tenant_id = %s AND section_key = %s
            """,
            (revision, actor_id, shift_report_id, tenant_id, section_key),
        )
        self._refresh_shift_status(tenant_id, shift_report_id)
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="shift_report.section_submitted",
            entity_type="shift_report",
            entity_id=shift_report_id,
            payload={"section": section_key, "revision": revision},
        )
        return Ok(self._section_result(tenant_id, shift_report_id, section_key))

    def declare_nothing(
        self, *, tenant_id: str, actor_id: str, shift_report_id: str, section_key: str
    ) -> Result[dict]:
        """Say the section has nothing in it. Any rows it held are removed."""
        found = self._editable_section(tenant_id, shift_report_id, section_key)
        if isinstance(found, Err):
            return found
        _, section = found.value
        if not can_declare_nothing(section["status"]):
            return Err("INVALID_TRANSITION", f"a section that is {section['status']} cannot be emptied")
        if section["status"] == "nothing_to_report":
            return Ok(self._section_result(tenant_id, shift_report_id, section_key))

        was_submitted = section["status"] == "submitted"
        clear_section_rows(self._connection, tenant_id=tenant_id, shift_report_id=shift_report_id, section_key=section_key)
        revision = section["revision"]
        if was_submitted:
            revision = self._freeze_revision(tenant_id, actor_id, shift_report_id, section_key, "nothing to report")
        self._connection.execute(
            """
            UPDATE production.shift_report_sections
            SET status = 'nothing_to_report', revision = %s, revised_after_submit = revised_after_submit OR %s,
                return_reason = NULL, submitted_by = %s, submitted_at = NOW(), updated_at = NOW()
            WHERE shift_report_id = %s AND tenant_id = %s AND section_key = %s
            """,
            (revision, was_submitted, actor_id, shift_report_id, tenant_id, section_key),
        )
        self._refresh_shift_status(tenant_id, shift_report_id)
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="shift_report.section_nothing_to_report",
            entity_type="shift_report",
            entity_id=shift_report_id,
            payload={"section": section_key},
        )
        return Ok(self._section_result(tenant_id, shift_report_id, section_key))
