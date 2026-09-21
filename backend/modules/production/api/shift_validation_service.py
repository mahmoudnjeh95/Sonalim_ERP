"""One approval for a whole shift, targeted rejection, and reversal.

Validation posts stock, and it must never post half a shift. The whole act runs in
a savepoint: any refusal from any row rolls the shift back to exactly how it was, no
matter what the caller does with the connection afterwards.

The stock rules themselves are the existing ones (`ProductionReportService`); see
`legacy_report_ledger` for how a shift is presented to them.
"""
from __future__ import annotations

from typing import Any

import psycopg
from psycopg.types.json import Jsonb
from ulid import ULID

from core.audit import record_audit
from core.domain.result import Err, Result
from modules.production.api.legacy_report_ledger import materialize_shift
from modules.production.api.production_report_service import ProductionReportService
from modules.production.api.report_product import stamp_order_products
from modules.production.api.shift_report_service import ShiftReportService
from modules.production.api.shift_sections import load_section
from modules.production.api.silo_machine_status import apply_silo_machine_status
from modules.production.domain.shift_report import SECTION_KEYS


class _Abort(Exception):
    """Carries an `Err` out of the savepoint block so the savepoint rolls back."""

    def __init__(self, err: Err) -> None:
        super().__init__(err.message)
        self.err = err


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

    def _report_ids(self, tenant_id: str, shift_report_id: str) -> tuple[list[str], list[str]]:
        runs = [
            r[0]
            for r in self._connection.execute(
                "SELECT id FROM production.shift_runs WHERE shift_report_id = %s AND tenant_id = %s ORDER BY line_order, id",
                (shift_report_id, tenant_id),
            ).fetchall()
        ]
        packing = [
            r[0]
            for r in self._connection.execute(
                "SELECT id FROM production.shift_packing_rows WHERE shift_report_id = %s AND tenant_id = %s ORDER BY line_order, id",
                (shift_report_id, tenant_id),
            ).fetchall()
        ]
        return runs, packing

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
        status = self._locked_status(tenant_id, shift_report_id)
        if status is None:
            return Err("NOT_FOUND", f"shift report {shift_report_id} not found")
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
                materialised = materialize_shift(
                    self._connection, tenant_id=tenant_id, shift_report_id=shift_report_id, actor_id=actor_id
                )
                if isinstance(materialised, Err):
                    raise _Abort(materialised)
                reports = ProductionReportService(self._connection)
                for report_id, _report_type in materialised.value:
                    result = reports.validate_report(
                        tenant_id=tenant_id,
                        actor_id=actor_id,
                        report_id=report_id,
                        correlation_id=correlation_id,
                        shortfall_comment=shortfall_comment,
                        regrind_work_center_id=regrind_work_center_id,
                    )
                    if isinstance(result, Err):
                        raise _Abort(result)

                # Validation freezes the packaging and settles the packed tonnage in the ledger; copy
                # those figures back so the shift shows exactly what the readers count.
                self._connection.execute(
                    """
                    UPDATE production.shift_packing_rows p
                    SET snapshot_net_weight_grams = c.snapshot_net_weight_grams,
                        snapshot_packets_per_carton = c.snapshot_packets_per_carton,
                        finished_product_quantity = c.finished_product_quantity,
                        finished_goods_location_id = c.finished_goods_location_id
                    FROM production.conditionnement_reports c
                    WHERE c.report_id = p.id AND p.shift_report_id = %s AND p.tenant_id = %s
                    """,
                    (shift_report_id, tenant_id),
                )
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
                        "reports": [report_id for report_id, _ in materialised.value],
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
        runs, packing = self._report_ids(tenant_id, shift_report_id)
        try:
            with self._connection.transaction():
                reports = ProductionReportService(self._connection)
                # Packing first: a packing report points at the daily report it drew from.
                for report_id in [*packing, *runs]:
                    exists = self._connection.execute(
                        "SELECT 1 FROM production.production_reports WHERE id = %s AND tenant_id = %s", (report_id, tenant_id)
                    ).fetchone()
                    if exists is None:
                        continue
                    result = reports.delete_report(
                        tenant_id=tenant_id,
                        actor_id=actor_id,
                        report_id=report_id,
                        reason=reason.strip(),
                        correlation_id=correlation_id,
                        force=force,
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
                    payload={"reason": reason.strip(), "forced": force, "reports": [*runs, *packing]},
                )
        except _Abort as abort:
            return abort.err
        return self._shifts.get_shift(tenant_id=tenant_id, shift_report_id=shift_report_id)
