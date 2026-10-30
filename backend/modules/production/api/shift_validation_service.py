"""One approval for a whole shift, targeted rejection, and reversal.

Validation posts stock, and it must never post half a shift. The whole act runs in
a savepoint: any refusal from any row rolls the shift back to exactly how it was, no
matter what the caller does with the connection afterwards.

The stock rules live in `ShiftStockService`, reading and writing the shift's own
tables directly. ~18 reader services still query the old production_reports/
daily_reports/conditionnement_reports tables directly; until each is ported to the
shift tables, validation also writes a read-only copy there via
`legacy_report_ledger.materialize_shift`, marked validated straight away (no
'submitted' step, since nothing here reads that status) -- it posts no stock of its
own, ShiftStockService already did. Reversal deletes the copy. Task 8 drops these
tables once every reader has moved.
"""
from __future__ import annotations

from typing import Any

import psycopg
from psycopg.types.json import Jsonb
from ulid import ULID

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from modules.production.api.legacy_report_ledger import materialize_shift
from modules.production.api.report_product import stamp_order_products
from modules.production.api.shift_report_service import ShiftReportService
from modules.production.api.shift_sections import load_section, save_section_rows
from modules.production.api.shift_stock_service import ShiftStockService
from modules.production.api.silo_machine_status import apply_silo_machine_status
from modules.production.api.waste_type_service import custom_waste_categories
from modules.production.domain.shift_report import SECTION_KEYS, split_proportionally


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


def _runs(connection: psycopg.Connection, tenant_id: str, shift_report_id: str) -> list[dict]:
    """The shift's runs with their semoule lines attached -- the shape ShiftStockService posts
    and reverses. Validation and reversal must read runs the same way, or a reversal puts back
    less than validation took."""
    runs = _rows(connection, tenant_id, shift_report_id, "shift_runs")
    for run in runs:
        run["semolina_lines"] = _rows(connection, tenant_id, run["id"], "shift_run_semolina_lines", by="run_id")
    return runs


# Sections whose rows are what validation posted to stock. Correcting one after validation
# takes back what the old rows posted and posts the new ones; any other section moves no stock.
_RUN_SECTIONS = frozenset({"runs"})
# The packing-waste section feeds each packing row's empty cartons, hence its packets.
_PACKING_SECTIONS = frozenset({"packing", "waste_packing"})


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
            return Err("NOT_FOUND", f"shift report {shift_report_id} not found", f"shift {shift_report_id} introuvable")
        status, shift_date = locked
        if status != "submitted":
            return Err("INVALID_TRANSITION", f"a shift that is {status} cannot be validated", f"un shift {status} ne peut pas être validé")

        sections = {s["key"]: s for s in self._shifts.list_section_states(tenant_id=tenant_id, shift_report_id=shift_report_id)}
        if seen_revisions:
            moved = sorted(k for k, rev in seen_revisions.items() if k in sections and sections[k]["revision"] != rev)
            if moved:
                return Err(
                    "CHANGED_SINCE_OPENED",
                    f"sections changed since you opened the shift: {', '.join(moved)}",
                    f"des sections ont changé depuis l'ouverture du shift : {', '.join(moved)}",
                )

        correlation_id = correlation_id or str(ULID())
        try:
            with self._connection.transaction():
                # An order with no product yet takes its first packing row's, before anything is posted.
                stamp_order_products(self._connection, tenant_id=tenant_id, shift_report_id=shift_report_id)

                runs = _runs(self._connection, tenant_id, shift_report_id)
                packing = _rows(self._connection, tenant_id, shift_report_id, "shift_packing_rows")
                if not runs and not packing:
                    raise _Abort(Err(
                        "NOTHING_TO_VALIDATE",
                        "the shift has no production run and no packing row to validate",
                        "le shift n'a ni passage de production ni ligne de conditionnement à valider",
                    ))

                open_stop = self._connection.execute(
                    "SELECT 1 FROM production.machine_stops WHERE shift_report_id = %s AND tenant_id = %s AND ended_at IS NULL LIMIT 1",
                    (shift_report_id, tenant_id),
                ).fetchone()
                if open_stop is not None:
                    raise _Abort(Err(
                        "OPEN_STOP",
                        "a machine stop is still ongoing; end it before validating the shift",
                        "un arrêt machine est toujours en cours ; terminez-le avant de valider le shift",
                    ))

                stock = ShiftStockService(self._connection)
                shortfalls = stock.shift_shortfalls(tenant_id=tenant_id, runs=runs, packing_rows=packing)
                if shortfalls and not (shortfall_comment or "").strip():
                    raise _Abort(Err(
                        "SHORTFALL_COMMENT_REQUIRED",
                        "this shift consumes more than the stock figure holds; validating it needs a comment explaining why",
                        "ce shift consomme plus que ce que le stock indique ; le valider nécessite un commentaire expliquant pourquoi",
                    ))

                for run in runs:
                    posted = stock.post_run(tenant_id=tenant_id, actor_id=actor_id, run=run, correlation_id=correlation_id)
                    if isinstance(posted, Err):
                        raise _Abort(posted)
                    regrind = stock.record_regrind(tenant_id=tenant_id, actor_id=actor_id, run=run, regrind_work_center_id=regrind_work_center_id)
                    if isinstance(regrind, Err):
                        raise _Abort(regrind)

                self._post_packing_rows(
                    stock, tenant_id=tenant_id, actor_id=actor_id, packing=packing, shift_date=shift_date,
                    correlation_id=correlation_id,
                )
                self._write_legacy_copy(tenant_id, actor_id, shift_report_id)

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
            return Err(
                "INVALID_VALUE",
                f"the shift cannot be posted as entered: {exc.diag.message_primary or exc}",
                f"le shift ne peut pas être versé en stock tel que saisi : {exc.diag.message_primary or exc}",
            )
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

    # ---- posting helpers, shared by validation, correction and reversal -------

    def _order_products(self, tenant_id: str, packing: list[dict]) -> dict[str, str | None]:
        if not packing:
            return {}
        return {
            row[0]: row[1]
            for row in self._connection.execute(
                "SELECT id, product_id FROM production.work_orders WHERE tenant_id = %s AND id = ANY(%s)",
                (tenant_id, list({p["of_id"] for p in packing})),
            ).fetchall()
        }

    def _post_packing_rows(
        self, stock: ShiftStockService, *, tenant_id: str, actor_id: str, packing: list[dict], shift_date,
        correlation_id: str, frozen: dict[str, tuple] | None = None,
    ) -> None:
        """Post every packing row: settle its store, pin its packaging, move the stock, register its lot.

        `frozen` maps a row id to the packaging an earlier validation already pinned on it.
        """
        order_products = self._order_products(tenant_id, packing)
        products: dict[str, str] = {}
        for row in packing:
            finished_product_id = row.get("product_id") or order_products.get(row["of_id"])
            if finished_product_id is None:
                raise _Abort(Err(
                    "NOT_FOUND",
                    f"work order {row['of_id']} has no product to pack",
                    f"l'OF {row['of_id']} n'a pas de produit à conditionner",
                ))
            products[row["id"]] = finished_product_id
            # The store is settled once, here, and kept on the row: reversal reads it back
            # and must hand the goods back from exactly where they were posted.
            row["finished_goods_location_id"] = stock.finished_goods_store(
                tenant_id=tenant_id, packing_row=row, finished_product_id=finished_product_id
            )
            self._connection.execute(
                "UPDATE production.shift_packing_rows SET finished_goods_location_id = %s WHERE id = %s AND tenant_id = %s",
                (row["finished_goods_location_id"], row["id"], tenant_id),
            )
            snapshot = stock.freeze_packing_snapshot(
                tenant_id=tenant_id, packing_row=row, finished_product_id=finished_product_id,
                frozen=(frozen or {}).get(row["id"]),
            )
            row["snapshot_net_weight_grams"] = snapshot["net_weight_grams"]
            row["snapshot_packets_per_carton"] = snapshot["packets_per_carton"]
            row["finished_product_quantity"] = snapshot["finished_product_quantity"]

        # Every row's tonnage is settled above before any is costed: rows share their order's material by it.
        material_costs = self._material_costs(stock, tenant_id=tenant_id, packing=packing)
        for row in packing:
            finished_product_id = products[row["id"]]
            posted = stock.post_packing(
                tenant_id=tenant_id, actor_id=actor_id, packing_row=row, finished_product_id=finished_product_id,
                correlation_id=correlation_id, material_cost=material_costs.get(row["id"]),
            )
            if isinstance(posted, Err):
                raise _Abort(posted)
            lot = stock.register_lot(
                tenant_id=tenant_id, actor_id=actor_id, packing_row=row, finished_product_id=finished_product_id,
                report_date=shift_date,
            )
            if isinstance(lot, Err):
                raise _Abort(lot)

    def _material_costs(self, stock: ShiftStockService, *, tenant_id: str, packing: list[dict]) -> dict[str, float | None]:
        """Each packing row's share of the raw material its order consumed, at FIFO cost.

        An order's runs on this shift are what its packed goods were made of, so their net
        consumption is shared across the order's packing rows by tonnage (by units when no
        row has a net weight). An order packed on a shift where it did not run takes its
        running cost per tonne from its other validated shifts instead.
        """
        if not packing:
            return {}
        shift_report_id = packing[0]["shift_report_id"]
        runs_of_order: dict[str, list[str]] = {}
        for run_id, of_id in self._connection.execute(
            "SELECT id, of_id FROM production.shift_runs WHERE tenant_id = %s AND shift_report_id = %s",
            (tenant_id, shift_report_id),
        ).fetchall():
            runs_of_order.setdefault(of_id, []).append(run_id)
        rows_of_order: dict[str, list[dict]] = {}
        for row in packing:
            rows_of_order.setdefault(row["of_id"], []).append(row)

        costs: dict[str, float | None] = {}
        for of_id, rows in rows_of_order.items():
            tonnages = [float(row.get("finished_product_quantity") or 0) for row in rows]
            if runs_of_order.get(of_id):
                total = stock.consumed_cost(
                    tenant_id=tenant_id, references=[f"shift_run:{run_id}" for run_id in runs_of_order[of_id]]
                )["cost"]
                weights = tonnages if sum(tonnages) > 0 else [stock.finished_quantity(row) for row in rows]
                shares = split_proportionally(total, weights) if sum(weights) > 0 else [0.0 for _ in rows]
                costs.update({row["id"]: share for row, share in zip(rows, shares)})
            else:
                per_tonne = stock.order_material_cost_per_tonne(
                    tenant_id=tenant_id, of_id=of_id, exclude_shift_report_id=shift_report_id
                )
                costs.update({row["id"]: per_tonne * tonnage if per_tonne else None for row, tonnage in zip(rows, tonnages)})
        return costs

    def _reverse_packing_rows(
        self, stock: ShiftStockService, *, tenant_id: str, actor_id: str, packing: list[dict], correlation_id: str
    ) -> None:
        order_products = self._order_products(tenant_id, packing)
        for row in packing:
            finished_product_id = row.get("product_id") or order_products.get(row["of_id"])
            result = stock.reverse_packing(
                tenant_id=tenant_id, actor_id=actor_id, packing_row=row,
                finished_product_id=finished_product_id, correlation_id=correlation_id,
            )
            if isinstance(result, Err):
                raise _Abort(result)

    def _drop_legacy_copy(self, tenant_id: str, report_ids: list[str]) -> None:
        # The copy is validated, not submitted, so _delete_old_rows' own guard (refusing to
        # delete a validated row out from under a caller) would trip on our own rows here;
        # reversal and correction are the callers allowed to remove a validated copy.
        for table in ("report_waste_lines", "report_semolina_lines", "report_downtime_lines"):
            self._connection.execute(f"DELETE FROM production.{table} WHERE tenant_id = %s AND report_id = ANY(%s)", (tenant_id, report_ids))
        self._connection.execute("DELETE FROM production.conditionnement_reports WHERE tenant_id = %s AND report_id = ANY(%s)", (tenant_id, report_ids))
        self._connection.execute("DELETE FROM production.daily_reports WHERE tenant_id = %s AND report_id = ANY(%s)", (tenant_id, report_ids))
        self._connection.execute("DELETE FROM production.report_revisions WHERE tenant_id = %s AND report_id = ANY(%s)", (tenant_id, report_ids))
        self._connection.execute("DELETE FROM production.production_reports WHERE tenant_id = %s AND id = ANY(%s)", (tenant_id, report_ids))

    def _write_legacy_copy(self, tenant_id: str, actor_id: str, shift_report_id: str) -> None:
        materialized = materialize_shift(
            self._connection, tenant_id=tenant_id, shift_report_id=shift_report_id, actor_id=actor_id,
        )
        if isinstance(materialized, Err):
            raise _Abort(materialized)
        self._connection.execute(
            "UPDATE production.production_reports SET status = 'validated', validated_by = %s, validated_at = NOW() "
            "WHERE tenant_id = %s AND id = ANY(%s)",
            (actor_id, tenant_id, [report_id for report_id, _report_type in materialized.value]),
        )

    def _repost_after_correction(
        self, stock: ShiftStockService, *, tenant_id: str, actor_id: str, shift_report_id: str, shift_date,
        section_key: str, old_runs: list[dict], old_packing: list[dict], force: bool, reason: str | None,
        correlation_id: str,
    ) -> list[dict]:
        """Take back what the old rows posted and post the corrected ones; return any shortfalls.

        A runs correction re-posts the runs (settling their rebroyat against what was already
        ground, see `_reconcile_closed_regrind_batch`) and then the packing rows, whose value
        follows the runs' material; a packing correction re-posts the packing rows only. Each
        surviving packing row keeps the packaging it had pinned.
        """
        if section_key in _RUN_SECTIONS:
            new_runs = _runs(self._connection, tenant_id, shift_report_id)
            new_regrind = {run["id"]: float(run.get("regrind_quantity") or 0) for run in new_runs}
            regrind_kept: set[str] = set()
            for run in old_runs:
                undone = stock.reverse_run(
                    tenant_id=tenant_id, actor_id=actor_id, run=run, correlation_id=correlation_id, force=force,
                    new_regrind_quantity=new_regrind.get(run["id"], 0.0), reason=reason or "shift correction after validation",
                )
                if isinstance(undone, Err):
                    raise _Abort(undone)
                if undone.value["skip_regrind_rebuild"]:
                    regrind_kept.add(run["id"])
            shortfalls = stock.shift_shortfalls(tenant_id=tenant_id, runs=new_runs, packing_rows=[])
            for run in new_runs:
                posted = stock.post_run(tenant_id=tenant_id, actor_id=actor_id, run=run, correlation_id=correlation_id)
                if isinstance(posted, Err):
                    raise _Abort(posted)
                if run["id"] not in regrind_kept:
                    regrind = stock.record_regrind(tenant_id=tenant_id, actor_id=actor_id, run=run)
                    if isinstance(regrind, Err):
                        raise _Abort(regrind)
            if not old_packing:
                return shortfalls

        # The packed goods are re-posted on a runs correction too: they are valued at the runs'
        # material cost, which has just changed. Their quantities do not move.
        self._reverse_packing_rows(stock, tenant_id=tenant_id, actor_id=actor_id, packing=old_packing, correlation_id=correlation_id)
        new_packing = _rows(self._connection, tenant_id, shift_report_id, "shift_packing_rows")
        if section_key not in _RUN_SECTIONS:
            shortfalls = stock.shift_shortfalls(tenant_id=tenant_id, runs=[], packing_rows=new_packing)
        frozen = {
            row["id"]: tuple(
                float(value) if value is not None else None
                for value in (row.get("snapshot_net_weight_grams"), row.get("snapshot_packets_per_carton"))
            )
            for row in old_packing
            # A row validated before packaging was pinned has nothing frozen to keep.
            if row.get("snapshot_net_weight_grams") is not None or row.get("snapshot_packets_per_carton") is not None
        }
        self._post_packing_rows(
            stock, tenant_id=tenant_id, actor_id=actor_id, packing=new_packing, shift_date=shift_date,
            correlation_id=correlation_id, frozen=frozen,
        )
        return shortfalls

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
            return Err("INVALID_SECTION", f"unknown section {section_key!r}", f"section {section_key!r} inconnue")
        if not (reason or "").strip():
            return Err("MISSING_REASON", "editing a section as validator must record why", "modifier une section en tant que validateur doit enregistrer pourquoi")
        status = self._locked_status(tenant_id, shift_report_id)
        if status is None:
            return Err("NOT_FOUND", f"shift report {shift_report_id} not found", f"shift {shift_report_id} introuvable")
        if status != "submitted":
            return Err("INVALID_TRANSITION", f"a shift that is {status} cannot be edited by a validator", f"un shift {status} ne peut pas être modifié par un validateur")
        section = next(
            (s for s in self._shifts.list_section_states(tenant_id=tenant_id, shift_report_id=shift_report_id) if s["key"] == section_key),
            None,
        )
        if section is None or section["status"] != "submitted":
            # "Nothing to report" has no rows to correct; giving it rows would contradict its status.
            return Err(
                "INVALID_TRANSITION",
                "only a section the team submitted with content can be corrected",
                "seule une section que l'équipe a rendue avec du contenu peut être corrigée",
            )

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

    # ---- an admin's correction after validation ------------------------------

    def edit_section_after_validation(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        shift_report_id: str,
        section_key: str,
        payload: dict,
        reason: str | None,
        force: bool = False,
        correlation_id: str | None = None,
    ) -> Result[dict]:
        """An admin's in-place fix to a section after the shift was already validated.

        Gated by `production.admin_unlock_validated` at the router, not here. The shift
        and section keep their status (this corrects data, it does not reopen a workflow);
        the revision it freezes is tagged `edited_after_validation` at write time.

        Stock follows the correction, all or nothing: a section validation posted from (runs,
        packing, packing waste) has its old rows' movements taken back and the corrected rows
        posted, and the read-only report copy is rewritten. Otherwise stock would keep the old
        figures, and a later reversal -- which reads the corrected rows -- would take back a
        quantity validation never posted. `force` confirms opening a second rebroyat order when
        the corrected rebroyat exceeds a batch already ground.
        """
        if section_key not in SECTION_KEYS:
            return Err("INVALID_SECTION", f"unknown section {section_key!r}", f"section {section_key!r} inconnue")
        locked = self._locked_status_and_date(tenant_id, shift_report_id)
        if locked is None:
            return Err("NOT_FOUND", f"shift report {shift_report_id} not found", f"shift {shift_report_id} introuvable")
        status, shift_date = locked
        if status != "validated":
            return Err(
                "INVALID_TRANSITION",
                f"a shift that is {status} does not need an unlock to be edited",
                f"un shift {status} n'a pas besoin d'être déverrouillé pour être modifié",
            )

        clean_reason = (reason or "").strip() or None
        correlation_id = correlation_id or str(ULID())
        moves_stock = section_key in _RUN_SECTIONS | _PACKING_SECTIONS
        try:
            with self._connection.transaction():
                old_runs = _runs(self._connection, tenant_id, shift_report_id)
                old_packing = _rows(self._connection, tenant_id, shift_report_id, "shift_packing_rows")

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
                    raise _Abort(saved)

                shortfalls: list[dict] = []
                if moves_stock:
                    shortfalls = self._repost_after_correction(
                        ShiftStockService(self._connection), tenant_id=tenant_id, actor_id=actor_id,
                        shift_report_id=shift_report_id, shift_date=shift_date, section_key=section_key,
                        old_runs=old_runs, old_packing=old_packing, force=force, reason=clean_reason,
                        correlation_id=correlation_id,
                    )
                self._drop_legacy_copy(tenant_id, [r["id"] for r in old_runs] + [p["id"] for p in old_packing])
                self._write_legacy_copy(tenant_id, actor_id, shift_report_id)
                if section_key == "silo":
                    apply_silo_machine_status(
                        self._connection, tenant_id=tenant_id, actor_id=actor_id, shift_report_id=shift_report_id
                    )

                revision = self._shifts._freeze_revision(
                    tenant_id, actor_id, shift_report_id, section_key, clean_reason, edited_after_validation=True
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
                    action="shift_report.section_edited_after_validation",
                    entity_type="shift_report",
                    entity_id=shift_report_id,
                    payload={
                        "section": section_key, "revision": revision, "reason": clean_reason,
                        "stock_reposted": moves_stock, "forced": force, "shortfalls": shortfalls,
                    },
                )
        except _Abort as abort:
            return abort.err
        except psycopg.errors.IntegrityError as exc:
            return Err(
                "INVALID_VALUE",
                f"the correction cannot be posted as entered: {exc.diag.message_primary or exc}",
                f"la correction ne peut pas être versée en stock telle que saisie : {exc.diag.message_primary or exc}",
            )
        return Ok(self._shifts._section_result(tenant_id, shift_report_id, section_key))

    # ---- reject ------------------------------------------------------------

    def reject_sections(
        self, *, tenant_id: str, actor_id: str, shift_report_id: str, section_keys: list[str], reason: str
    ) -> Result[dict]:
        """Send the named sections back to their team; the rest stay submitted."""
        if not (reason or "").strip():
            return Err("MISSING_REASON", "rejecting a section must record why", "renvoyer une section doit enregistrer pourquoi")
        if not section_keys:
            return Err("INVALID_VALUE", "name at least one section to send back", "nommez au moins une section à renvoyer")
        unknown = [k for k in section_keys if k not in SECTION_KEYS]
        if unknown:
            return Err("INVALID_SECTION", f"unknown section {unknown[0]!r}", f"section {unknown[0]!r} inconnue")
        status = self._locked_status(tenant_id, shift_report_id)
        if status is None:
            return Err("NOT_FOUND", f"shift report {shift_report_id} not found", f"shift {shift_report_id} introuvable")
        if status != "submitted":
            return Err("INVALID_TRANSITION", f"a shift that is {status} cannot be rejected", f"un shift {status} ne peut pas être renvoyé")

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
            return Err("MISSING_REASON", "reversing a shift must record why", "annuler un shift doit enregistrer pourquoi")
        status = self._locked_status(tenant_id, shift_report_id)
        if status is None:
            return Err("NOT_FOUND", f"shift report {shift_report_id} not found", f"shift {shift_report_id} introuvable")
        if status != "validated":
            return Err("INVALID_TRANSITION", f"a shift that is {status} has nothing to reverse", f"un shift {status} n'a rien à annuler")

        correlation_id = correlation_id or str(ULID())
        try:
            with self._connection.transaction():
                stock = ShiftStockService(self._connection)
                packing = _rows(self._connection, tenant_id, shift_report_id, "shift_packing_rows")
                runs = _runs(self._connection, tenant_id, shift_report_id)
                # Packing first: mirrors the old ordering ("a packing report points at the daily report it drew from").
                self._reverse_packing_rows(stock, tenant_id=tenant_id, actor_id=actor_id, packing=packing, correlation_id=correlation_id)
                for run in runs:
                    result = stock.reverse_run(
                        tenant_id=tenant_id, actor_id=actor_id, run=run, correlation_id=correlation_id, force=force,
                    )
                    if isinstance(result, Err):
                        raise _Abort(result)

                self._drop_legacy_copy(tenant_id, [r["id"] for r in runs] + [p["id"] for p in packing])

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
