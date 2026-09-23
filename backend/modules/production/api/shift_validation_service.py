"""One approval for a whole shift, targeted rejection, and reversal.

Validation posts stock, and it must never post half a shift. The whole act runs in
a savepoint: any refusal from any row rolls the shift back to exactly how it was, no
matter what the caller does with the connection afterwards.

The stock rules live in `ShiftStockService`, reading and writing the shift's own
tables directly -- no old-shaped rows are materialised any more.
"""
from __future__ import annotations

from typing import Any

import psycopg
from psycopg.types.json import Jsonb
from ulid import ULID

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from modules.production.api.report_product import stamp_order_products
from modules.production.api.shift_report_service import ShiftReportService
from modules.production.api.shift_sections import load_section, save_section_rows
from modules.production.api.shift_stock_service import ShiftStockService
from modules.production.api.silo_machine_status import apply_silo_machine_status
from modules.production.api.waste_type_service import custom_waste_categories
from modules.production.domain.shift_report import SECTION_KEYS


class _Abort(Exception):
    """Carries an `Err` out of the savepoint block so the savepoint rolls back."""

    def __init__(self, err: Err) -> None:
        super().__init__(err.message)
        self.err = err


def _rows(connection: psycopg.Connection, tenant_id: str, key: str, table: str, by: str = "shift_report_id") -> list[dict]:
    cursor = connection.execute(
        f"SELECT * FROM production.{table} WHERE {by} = %s AND tenant_id = %s ORDER BY line_order, id", (key, tenant_id)
    )
    names = [d.name for d in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


class ShiftValidationService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection
        self._shifts = ShiftReportService(connection)

    def _locked_status(self, tenant_id: str, shift_report_id: str) -> str | None:
        row = self._connection.execute(
            "SELECT status FROM production.shift_reports WHERE id = %s AND tenant_id = %s FOR UPDATE",
            (shift_report_id, tenant_id),
        ).fetchone()
        return row[0] if row else None

    def _locked_status_and_date(self, tenant_id: str, shift_report_id: str) -> tuple[str, object] | None:
        row = self._connection.execute(
            "SELECT status, report_date FROM production.shift_reports WHERE id = %s AND tenant_id = %s FOR UPDATE",
            (shift_report_id, tenant_id),
        ).fetchone()
        return (row[0], row[1]) if row else None

    # ---- validate ----------------------------------------------------------

    def validate_shift(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        shift_report_id: str,
        seen_revisions: dict[str, int] | None = None,
        shortfall_comment: str | None = None,
        regrind_work_center_id: str | None = None,
        correlation_id: str | None = None,
    ) -> Result[dict]:
        """Approve the whole shift and post its stock, all or nothing.

        `seen_revisions` is what the validator's screen showed (section key -> revision).
        If any section has moved on since, validation is refused, so nothing is
        approved that the validator has not seen.
        """
        locked = self._locked_status_and_date(tenant_id, shift_report_id)
        if locked is None:
            return Err("NOT_FOUND", f"shift report {shift_report_id} not found")
        status, shift_date = locked
        if status != "submitted":
            return Err("INVALID_TRANSITION", f"a shift that is {status} cannot be validated")

        sections = {s["key"]: s for s in self._shifts.list_section_states(tenant_id=tenant_id, shift_report_id=shift_report_id)}
        if seen_revisions:
            moved = sorted(k for k, rev in seen_revisions.items() if k in sections and sections[k]["revision"] != rev)
            if moved:
                return Err("CHANGED_SINCE_OPENED", f"sections changed since you opened the shift: {', '.join(moved)}")

        correlation_id = correlation_id or str(ULID())
        try:
            with self._connection.transaction():
                # An order with no product yet takes its first packing row's, before anything is posted.
                stamp_order_products(self._connection, tenant_id=tenant_id, shift_report_id=shift_report_id)

                runs = _rows(self._connection, tenant_id, shift_report_id, "shift_runs")
                packing = _rows(self._connection, tenant_id, shift_report_id, "shift_packing_rows")
                if not runs and not packing:
                    raise _Abort(Err("NOTHING_TO_VALIDATE", "the shift has no production run and no packing row to validate"))

                open_stop = self._connection.execute(
                    "SELECT 1 FROM production.machine_stops WHERE shift_report_id = %s AND tenant_id = %s AND ended_at IS NULL LIMIT 1",
                    (shift_report_id, tenant_id),
                ).fetchone()
                if open_stop is not None:
                    raise _Abort(Err("OPEN_STOP", "a machine stop is still ongoing; end it before validating the shift"))

                stock = ShiftStockService(self._connection)
                shortfalls: list[dict] = []
                for run in runs:
                    run["semolina_lines"] = _rows(self._connection, tenant_id, run["id"], "shift_run_semolina_lines", by="run_id")
                    shortfalls += stock.run_shortfalls(tenant_id=tenant_id, run=run)
                for row in packing:
                    shortfalls += stock.packing_shortfalls(tenant_id=tenant_id, packing_row=row)
                if shortfalls and not (shortfall_comment or "").strip():
                    raise _Abort(Err(
                        "SHORTFALL_COMMENT_REQUIRED",
                        "this shift consumes more than the stock figure holds; validating it needs a comment explaining why",
                    ))

                for run in runs:
                    posted = stock.post_run(tenant_id=tenant_id, actor_id=actor_id, run=run, correlation_id=correlation_id)
                    if isinstance(posted, Err):
                        raise _Abort(posted)
                    regrind = stock.record_regrind(tenant_id=tenant_id, actor_id=actor_id, run=run, regrind_work_center_id=regrind_work_center_id)
                    if isinstance(regrind, Err):
                        raise _Abort(regrind)

                order_products = {
                    row[0]: row[1]
                    for row in self._connection.execute(
                        "SELECT id, product_id FROM production.work_orders WHERE tenant_id = %s AND id = ANY(%s)",
                        (tenant_id, list({p["of_id"] for p in packing})),
                    ).fetchall()
                } if packing else {}
                for row in packing:
                    finished_product_id = row.get("product_id") or order_products.get(row["of_id"])
                    if finished_product_id is None:
                        raise _Abort(Err("NOT_FOUND", f"work order {row['of_id']} has no product to pack"))
                    snapshot = stock.freeze_packing_snapshot(tenant_id=tenant_id, packing_row=row, finished_product_id=finished_product_id)
                    row["snapshot_packets_per_carton"] = snapshot["packets_per_carton"]
                    posted = stock.post_packing(tenant_id=tenant_id, actor_id=actor_id, packing_row=row, finished_product_id=finished_product_id, correlation_id=correlation_id)
                    if isinstance(posted, Err):
                        raise _Abort(posted)
                    lot = stock.register_lot(tenant_id=tenant_id, actor_id=actor_id, packing_row=row, finished_product_id=finished_product_id, report_date=shift_date)
                    if isinstance(lot, Err):
                        raise _Abort(lot)

                self._connection.execute(
                    "UPDATE production.shift_reports SET status = 'validated', validated_by = %s, validated_at = NOW(), "
                    "rejection_reason = NULL, updated_at = NOW() WHERE id = %s AND tenant_id = %s",
                    (actor_id, shift_report_id, tenant_id),
                )
                apply_silo_machine_status(
                    self._connection, tenant_id=tenant_id, actor_id=actor_id, shift_report_id=shift_report_id
                )
                self._connection.execute(
                    "UPDATE production.shift_report_sections SET revised_after_submit = FALSE, updated_at = NOW() "
                    "WHERE shift_report_id = %s AND tenant_id = %s",
                    (shift_report_id, tenant_id),
                )
                self._freeze_shift(tenant_id, actor_id, shift_report_id)
                record_audit(
                    self._connection,
                    tenant_id=tenant_id,
                    actor_id=actor_id,
                    action="shift_report.validated",
                    entity_type="shift_report",
                    entity_id=shift_report_id,
                    payload={
                        "reports": [r["id"] for r in runs] + [p["id"] for p in packing],
                        "section_revisions": {k: s["revision"] for k, s in sections.items()},
                        "shortfall_comment": shortfall_comment,
                    },
                )
        except _Abort as abort:
            return abort.err
        except psycopg.errors.IntegrityError as exc:
            return Err("INVALID_VALUE", f"the shift cannot be posted as entered: {exc.diag.message_primary or exc}")
        return self._shifts.get_shift(tenant_id=tenant_id, shift_report_id=shift_report_id)

    def _freeze_shift(self, tenant_id: str, actor_id: str, shift_report_id: str) -> None:
        """Snapshot every section as approved, under section key '*'."""
        snapshot: dict[str, Any] = {
            key: load_section(self._connection, tenant_id=tenant_id, shift_report_id=shift_report_id, section_key=key)
            for key in SECTION_KEYS
        }
        revision = self._connection.execute(
            "SELECT COALESCE(MAX(revision), 0) + 1 FROM production.shift_section_revisions "
            "WHERE shift_report_id = %s AND section_key = '*'",
            (shift_report_id,),
        ).fetchone()[0]
        self._connection.execute(
            "INSERT INTO production.shift_section_revisions "
            "(id, tenant_id, shift_report_id, section_key, revision, snapshot, reason, actor_id) "
            "VALUES (%s, %s, %s, '*', %s, %s, 'validated', %s)",
            (str(ULID()), tenant_id, shift_report_id, revision, Jsonb(snapshot), actor_id),
        )

    # ---- a validator's own correction ----------------------------------------

    def edit_section_as_validator(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        shift_report_id: str,
        section_key: str,
        payload: dict,
        reason: str,
    ) -> Result[dict]:
        """A validator's in-place fix to a submitted section, mid-review.

        Distinct from sending the section back (reject_sections) and from the team's own
        save (ShiftReportService.save_section, gated only by `status != 'validated'`): this
        gate is narrower -- only while the shift is `submitted`. The section keeps its
        status; the revision it freezes is tagged `edited_by_validator` at write time.
        """
        if section_key not in SECTION_KEYS:
            return Err("INVALID_SECTION", f"unknown section {section_key!r}")
        if not (reason or "").strip():
            return Err("MISSING_REASON", "editing a section as validator must record why")
        status = self._locked_status(tenant_id, shift_report_id)
        if status is None:
            return Err("NOT_FOUND", f"shift report {shift_report_id} not found")
        if status != "submitted":
            return Err("INVALID_TRANSITION", f"a shift that is {status} cannot be edited by a validator")
        section = next(
            (s for s in self._shifts.list_section_states(tenant_id=tenant_id, shift_report_id=shift_report_id) if s["key"] == section_key),
            None,
        )
        if section is None or section["status"] != "submitted":
            # "Nothing to report" has no rows to correct; giving it rows would contradict its status.
            return Err("INVALID_TRANSITION", "only a section the team submitted with content can be corrected")

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

        revision = self._shifts._freeze_revision(
            tenant_id, actor_id, shift_report_id, section_key, reason.strip(), edited_by_validator=True
        )
        self._connection.execute(
            "UPDATE production.shift_report_sections SET revision = %s, updated_at = NOW() "
            "WHERE shift_report_id = %s AND tenant_id = %s AND section_key = %s",
            (revision, shift_report_id, tenant_id, section_key),
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="shift_report.section_edited_by_validator",
            entity_type="shift_report",
            entity_id=shift_report_id,
            payload={"section": section_key, "revision": revision, "reason": reason.strip()},
        )
        return Ok(self._shifts._section_result(tenant_id, shift_report_id, section_key))

    # ---- reject ------------------------------------------------------------

    def reject_sections(
        self, *, tenant_id: str, actor_id: str, shift_report_id: str, section_keys: list[str], reason: str
    ) -> Result[dict]:
        """Send the named sections back to their team; the rest stay submitted."""
        if not (reason or "").strip():
            return Err("MISSING_REASON", "rejecting a section must record why")
        if not section_keys:
            return Err("INVALID_VALUE", "name at least one section to send back")
        unknown = [k for k in section_keys if k not in SECTION_KEYS]
        if unknown:
            return Err("INVALID_SECTION", f"unknown section {unknown[0]!r}")
        status = self._locked_status(tenant_id, shift_report_id)
        if status is None:
            return Err("NOT_FOUND", f"shift report {shift_report_id} not found")
        if status != "submitted":
            return Err("INVALID_TRANSITION", f"a shift that is {status} cannot be rejected")

        self._connection.execute(
            "UPDATE production.shift_report_sections SET status = 'returned', return_reason = %s, updated_at = NOW() "
            "WHERE shift_report_id = %s AND tenant_id = %s AND section_key = ANY(%s) "
            "AND status IN ('submitted', 'nothing_to_report')",
            (reason.strip(), shift_report_id, tenant_id, list(section_keys)),
        )
        self._shifts.refresh_shift_status(tenant_id=tenant_id, shift_report_id=shift_report_id)
        self._connection.execute(
            "UPDATE production.shift_reports SET rejection_reason = %s WHERE id = %s AND tenant_id = %s",
            (reason.strip(), shift_report_id, tenant_id),
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="shift_report.sections_returned",
            entity_type="shift_report",
            entity_id=shift_report_id,
            payload={"sections": list(section_keys), "reason": reason.strip()},
        )
        return self._shifts.get_shift(tenant_id=tenant_id, shift_report_id=shift_report_id)

    # ---- reverse -----------------------------------------------------------

    def reverse_shift(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        shift_report_id: str,
        reason: str,
        force: bool = False,
        correlation_id: str | None = None,
    ) -> Result[dict]:
        """Undo a validated shift: stock goes back, sections that had data return to their team."""
        if not (reason or "").strip():
            return Err("MISSING_REASON", "reversing a shift must record why")
        status = self._locked_status(tenant_id, shift_report_id)
        if status is None:
            return Err("NOT_FOUND", f"shift report {shift_report_id} not found")
        if status != "validated":
            return Err("INVALID_TRANSITION", f"a shift that is {status} has nothing to reverse")

        correlation_id = correlation_id or str(ULID())
        try:
            with self._connection.transaction():
                stock = ShiftStockService(self._connection)
                packing = _rows(self._connection, tenant_id, shift_report_id, "shift_packing_rows")
                runs = _rows(self._connection, tenant_id, shift_report_id, "shift_runs")
                order_products = {
                    row[0]: row[1]
                    for row in self._connection.execute(
                        "SELECT id, product_id FROM production.work_orders WHERE tenant_id = %s AND id = ANY(%s)",
                        (tenant_id, list({p["of_id"] for p in packing})),
                    ).fetchall()
                } if packing else {}
                # Packing first: mirrors the old ordering ("a packing report points at the daily report it drew from").
                for row in packing:
                    finished_product_id = row.get("product_id") or order_products.get(row["of_id"])
                    result = stock.reverse_packing(
                        tenant_id=tenant_id, actor_id=actor_id, packing_row=row,
                        finished_product_id=finished_product_id, correlation_id=correlation_id,
                    )
                    if isinstance(result, Err):
                        raise _Abort(result)
                for run in runs:
                    result = stock.reverse_run(
                        tenant_id=tenant_id, actor_id=actor_id, run=run, correlation_id=correlation_id, force=force,
                    )
                    if isinstance(result, Err):
                        raise _Abort(result)

                self._connection.execute(
                    "UPDATE production.shift_report_sections SET status = 'returned', return_reason = %s, updated_at = NOW() "
                    "WHERE shift_report_id = %s AND tenant_id = %s AND status = 'submitted'",
                    (f"reversed: {reason.strip()}", shift_report_id, tenant_id),
                )
                self._connection.execute(
                    "UPDATE production.shift_reports SET status = 'returned', validated_by = NULL, validated_at = NULL, "
                    "rejection_reason = %s, updated_at = NOW() WHERE id = %s AND tenant_id = %s",
                    (f"reversed: {reason.strip()}", shift_report_id, tenant_id),
                )
                record_audit(
                    self._connection,
                    tenant_id=tenant_id,
                    actor_id=actor_id,
                    action="shift_report.reversed",
                    entity_type="shift_report",
                    entity_id=shift_report_id,
                    payload={"reason": reason.strip(), "forced": force, "reports": [r["id"] for r in runs] + [p["id"] for p in packing]},
                )
        except _Abort as abort:
            return abort.err
        return self._shifts.get_shift(tenant_id=tenant_id, shift_report_id=shift_report_id)
