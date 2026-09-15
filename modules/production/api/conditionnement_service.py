from __future__ import annotations

import dataclasses
import datetime

import psycopg
from ulid import ULID

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from modules.production.api.production_report_service import ProductionReportService, _detail_to_json
from modules.production.api.waste_line_store import load_waste_lines, replace_waste_lines
from modules.production.domain.packaging_estimate import tonnage_from_count
from modules.production.domain.production_report import (
    ConditionnementReportDetail,
    ProductionReport,
    WasteLine,
    validate_conditionnement_detail,
    validate_report_header,
)
from modules.warehouse.api.lot_service import LotService

# Déchets live in production.report_waste_lines -- one row per item lost, so a
# shift can record scotch, a second film, or nothing at all.
#
# The two snapshot columns are deliberately NOT here: they are written once, by
# the validation path, and an editable detail write must never touch them.
_COLUMNS = """
    finished_product_quantity, packets_counted, film_quantity, carton_quantity, waste_carton_quantity, tape_quantity,
    scotch_quantity, ruban_quantity,
    machine_speed,
    production_minutes, downtime_minutes, downtime_reason, lot_number, dlc_date,
    film_product_id, carton_product_id, tape_product_id, scotch_product_id, ruban_product_id,
    packaging_location_id,
    finished_goods_location_id, daily_report_id,
    film_supplier_id, carton_supplier_id, tape_supplier_id, scotch_supplier_id, ruban_supplier_id
"""

_OF_STATUSES_ACCEPTING_REPORTS = {"planned", "ongoing", "suspended"}


def _row_to_detail(row: tuple, waste_lines: tuple[WasteLine, ...] = ()) -> ConditionnementReportDetail:
    return ConditionnementReportDetail(
        finished_product_quantity=float(row[0]),
        packets_counted=float(row[1]),
        film_quantity=float(row[2]),
        carton_quantity=float(row[3]),
        waste_carton_quantity=float(row[4]),
        tape_quantity=float(row[5]),
        scotch_quantity=float(row[6]),
        ruban_quantity=float(row[7]),
        machine_speed=float(row[8]) if row[8] is not None else None,
        production_minutes=int(row[9]),
        downtime_minutes=int(row[10]),
        downtime_reason=row[11],
        lot_number=row[12],
        dlc_date=row[13],
        film_product_id=row[14],
        carton_product_id=row[15],
        tape_product_id=row[16],
        scotch_product_id=row[17],
        ruban_product_id=row[18],
        packaging_location_id=row[19],
        finished_goods_location_id=row[20],
        daily_report_id=row[21],
        film_supplier_id=row[22],
        carton_supplier_id=row[23],
        tape_supplier_id=row[24],
        scotch_supplier_id=row[25],
        ruban_supplier_id=row[26],
        waste_lines=waste_lines,
    )


def _values(detail: ConditionnementReportDetail) -> tuple:
    return (
        detail.finished_product_quantity,
        detail.packets_counted,
        detail.film_quantity,
        detail.carton_quantity,
        detail.waste_carton_quantity,
        detail.tape_quantity,
        detail.scotch_quantity,
        detail.ruban_quantity,
        detail.machine_speed,
        detail.production_minutes,
        detail.downtime_minutes,
        detail.downtime_reason,
        detail.lot_number,
        detail.dlc_date,
        detail.film_product_id,
        detail.carton_product_id,
        detail.tape_product_id,
        detail.scotch_product_id,
        detail.ruban_product_id,
        detail.packaging_location_id,
        detail.finished_goods_location_id,
        detail.daily_report_id,
        detail.film_supplier_id,
        detail.carton_supplier_id,
        detail.tape_supplier_id,
        detail.scotch_supplier_id,
        detail.ruban_supplier_id,
    )


def load_conditionnement_detail(
    connection: psycopg.Connection, *, tenant_id: str, report_id: str
) -> ConditionnementReportDetail | None:
    """Used by ProductionReportService's type dispatch as well as by this service."""
    row = connection.execute(
        f"SELECT {_COLUMNS} FROM production.conditionnement_reports WHERE report_id = %s AND tenant_id = %s",
        (report_id, tenant_id),
    ).fetchone()
    if row is None:
        return None
    return _row_to_detail(row, load_waste_lines(connection, tenant_id=tenant_id, report_id=report_id))


def load_snapshot_packets_per_carton(
    connection: psycopg.Connection, *, tenant_id: str, report_id: str
) -> float | None:
    """The packets-per-carton a validated report was frozen against.

    Read separately from `load_conditionnement_detail`, which deliberately never
    touches the two snapshot columns (decision 20) — reversing or correcting a
    validated report must post the same quantity it originally did, even if the
    product's packaging has since changed, so it reads the snapshot directly
    rather than the product's current value.
    """
    row = connection.execute(
        "SELECT snapshot_packets_per_carton FROM production.conditionnement_reports "
        "WHERE report_id = %s AND tenant_id = %s",
        (report_id, tenant_id),
    ).fetchone()
    if row is None or row[0] is None:
        return None
    return float(row[0])


def register_dlc_lot(
    connection: psycopg.Connection, *, tenant_id: str, actor_id: str, header: ProductionReport
) -> Result[str | None]:
    """Turn a validated report's DLC into a real lot, through the warehouse service.

    The DLC on a packing report is not a note — it is the identity and expiry date
    of product that will be sold, so it becomes a `warehouse.lots` row the moment
    the report is validated. Production never writes that table itself; it goes
    through LotService like any other caller, and the lot carries a source pointer
    back to the report that created it.

    Only the lot's identity is registered here. The finished-product quantity that
    lands in it is a stock movement, and stock movements arrive in Phase 5.
    """
    detail = load_conditionnement_detail(connection, tenant_id=tenant_id, report_id=header.id)
    if detail is None or not (detail.lot_number or "").strip():
        return Ok(None)

    product_row = connection.execute(
        "SELECT product_id FROM production.work_orders WHERE id = %s AND tenant_id = %s",
        (header.of_id, tenant_id),
    ).fetchone()
    if product_row is None:
        return Err("NOT_FOUND", f"work order {header.of_id} not found")

    lot = LotService(connection).register_lot(
        tenant_id=tenant_id,
        product_id=product_row[0],
        lot_number=detail.lot_number,  # type: ignore[arg-type]
        actor_id=actor_id,
        expiry_date=detail.dlc_date,
        produced_at=datetime.datetime.combine(header.report_date, datetime.time.min),
        source_type="production.conditionnement_report",
        source_id=header.id,
    )
    if isinstance(lot, Err):
        return lot
    return Ok(lot.value.id)


def freeze_packaging_parameters(
    connection: psycopg.Connection, *, tenant_id: str, report_id: str, product_id: str, detail: ConditionnementReportDetail
) -> dict:
    """Stamp the product's packaging onto the report as it is validated.

    Phase 9, decision 20. The ecart is a judgement made against a specific net
    weight and a specific number of packets to a carton, and both of those are
    editable properties of the product. Without this, correcting a net weight
    next month would silently rewrite the ecart of every report ever signed off
    against the old one -- and an ecart that changes after the fact is not
    evidence of anything.

    Read through CoreService rather than a join: core is a declared dependency
    with a service, and production has no business in its tables.

    The same frozen net weight also settles `finished_product_quantity` here,
    in the same statement: the tonnage a carton/sac count represents (decision
    24's count turned into weight via the product's own net weight), which is
    what OF consolidation sums into `produced_quantity` and yield. Computing it
    now rather than whenever the report was last saved as a draft means it can
    never disagree with the snapshot it is validated against, even if the
    product's packaging was edited in between.
    """
    from core.api.service import CoreService

    product = CoreService(connection).get_product(tenant_id, product_id)
    net_weight_grams = product.net_weight_grams if product is not None else None
    packets_per_carton = product.packets_per_carton if product is not None else None
    finished_product_quantity = tonnage_from_count(
        net_weight_grams=net_weight_grams,
        packets_per_carton=packets_per_carton,
        carton_quantity=detail.carton_quantity,
        packets_counted=detail.packets_counted,
        waste_carton_quantity=detail.waste_carton_quantity,
    )

    connection.execute(
        """
        UPDATE production.conditionnement_reports
        SET snapshot_net_weight_grams = %s, snapshot_packets_per_carton = %s, finished_product_quantity = %s
        WHERE report_id = %s AND tenant_id = %s
        """,
        (net_weight_grams, packets_per_carton, finished_product_quantity, report_id, tenant_id),
    )
    return {"net_weight_grams": net_weight_grams, "packets_per_carton": packets_per_carton}


def write_conditionnement_detail(
    connection: psycopg.Connection, *, tenant_id: str, report_id: str, detail: ConditionnementReportDetail
) -> None:
    """Overwrite a packing report's figures. Used by the post-validation correction path.

    A validated report already has its packaging frozen (decision 20) — this
    path never calls `freeze_packaging_parameters` again, so `finished_product_
    quantity` is recomputed here instead, off that same snapshot rather than the
    product's possibly-since-edited current values, so a correction stays judged
    against what the report was originally validated with.
    """
    snapshot = connection.execute(
        "SELECT snapshot_net_weight_grams, snapshot_packets_per_carton FROM production.conditionnement_reports "
        "WHERE report_id = %s AND tenant_id = %s",
        (report_id, tenant_id),
    ).fetchone()
    snapshot_weight = float(snapshot[0]) if snapshot is not None and snapshot[0] is not None else None
    snapshot_per_carton = float(snapshot[1]) if snapshot is not None and snapshot[1] is not None else None
    detail = dataclasses.replace(
        detail,
        finished_product_quantity=tonnage_from_count(
            net_weight_grams=snapshot_weight,
            packets_per_carton=snapshot_per_carton,
            carton_quantity=detail.carton_quantity,
            packets_counted=detail.packets_counted,
            waste_carton_quantity=detail.waste_carton_quantity,
        ),
    )

    assignments = ", ".join(f"{column.strip()} = %s" for column in _COLUMNS.split(","))
    connection.execute(
        f"UPDATE production.conditionnement_reports SET {assignments} WHERE report_id = %s AND tenant_id = %s",
        (*_values(detail), report_id, tenant_id),
    )
    replace_waste_lines(connection, tenant_id=tenant_id, report_id=report_id, lines=detail.waste_lines)


class ConditionnementReportService:
    """The packing report's own figures.

    Everything about status, revisions and the validation desk is
    ProductionReportService's — submit, validate, reject and revise are shared with
    the daily report and are not duplicated here. This class owns only what is
    specific to conditionnement: its detail row, and the DLC that becomes a lot.
    """

    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection
        self._reports = ProductionReportService(connection)

    def create_report(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        of_id: str,
        report_date: datetime.date,
        detail: ConditionnementReportDetail | None = None,
        team: str | None = None,
        work_center_id: str | None = None,
        equipment_id: str | None = None,
        shift: str | None = None,
        # Only consulted when the order has no product yet — its first
        # packaging report is what names one. Ignored once it's set: an OF
        # does not change what it packs partway through.
        product_id: str | None = None,
    ) -> Result[dict]:
        header_validation = validate_report_header(report_type="conditionnement", of_id=of_id)
        if isinstance(header_validation, Err):
            return header_validation

        detail = detail or ConditionnementReportDetail()
        detail_validation = validate_conditionnement_detail(detail)
        if isinstance(detail_validation, Err):
            return detail_validation

        work_order = self._connection.execute(
            "SELECT status, work_center_id, product_id FROM production.work_orders WHERE id = %s AND tenant_id = %s",
            (of_id, tenant_id),
        ).fetchone()
        if work_order is None:
            return Err("NOT_FOUND", f"work order {of_id} not found")
        of_status, of_work_center_id, of_product_id = work_order
        if of_status not in _OF_STATUSES_ACCEPTING_REPORTS:
            return Err("OF_NOT_OPEN", f"work order {of_id} is {of_status} and accepts no new reports")

        if of_product_id is None:
            if not (product_id or "").strip():
                return Err(
                    "MISSING_PRODUCT",
                    "this work order has no product yet — name one to file its first packaging report",
                )
            self._connection.execute(
                "UPDATE production.work_orders SET product_id = %s WHERE id = %s AND tenant_id = %s AND product_id IS NULL",
                (product_id, of_id, tenant_id),
            )

        if self._reports._duplicate_report_exists(
            tenant_id=tenant_id, of_id=of_id, report_type="conditionnement", report_date=report_date, shift=shift
        ):
            return Err(
                "DUPLICATE_REPORT", "a conditionnement report already exists for this work order, date and shift"
            )

        if detail.daily_report_id is not None:
            daily = self._connection.execute(
                "SELECT of_id, report_type FROM production.production_reports WHERE id = %s AND tenant_id = %s",
                (detail.daily_report_id, tenant_id),
            ).fetchone()
            if daily is None:
                return Err("NOT_FOUND", f"daily report {detail.daily_report_id} not found")
            daily_of_id, daily_report_type = daily
            if daily_report_type != "daily":
                return Err("WRONG_REPORT_TYPE", f"report {detail.daily_report_id} is not a daily report")
            if daily_of_id != of_id:
                return Err("MISMATCHED_OF", "the daily report must belong to the same work order")

        report_id = str(ULID())
        self._connection.execute(
            """
            INSERT INTO production.production_reports
                (id, tenant_id, of_id, report_type, report_date, status, revision, team, work_center_id,
                 equipment_id, shift, created_by)
            VALUES (%s, %s, %s, 'conditionnement', %s, 'draft', 1, %s, %s, %s, %s, %s)
            """,
            (
                report_id,
                tenant_id,
                of_id,
                report_date,
                team,
                work_center_id if work_center_id is not None else of_work_center_id,
                equipment_id,
                shift,
                actor_id,
            ),
        )
        values = _values(detail)
        # Derived from the values rather than typed out, so the placeholder
        # count cannot drift away from the column list.
        placeholders = ", ".join(["%s"] * (2 + len(values)))
        self._connection.execute(
            f"""
            INSERT INTO production.conditionnement_reports (report_id, tenant_id, {_COLUMNS})
            VALUES ({placeholders})
            """,
            (report_id, tenant_id, *values),
        )
        replace_waste_lines(
            self._connection, tenant_id=tenant_id, report_id=report_id, lines=detail.waste_lines
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="production_report.created",
            entity_type="production_report",
            entity_id=report_id,
            payload={"of_id": of_id, "report_type": "conditionnement", "report_date": report_date.isoformat()},
        )
        return Ok(self._read(tenant_id=tenant_id, report_id=report_id))

    def update_draft(
        self, *, tenant_id: str, actor_id: str, report_id: str, detail: ConditionnementReportDetail
    ) -> Result[dict]:
        header = self._reports._load_header(tenant_id=tenant_id, report_id=report_id, for_update=True)
        if header is None:
            return Err("NOT_FOUND", f"report {report_id} not found")
        if header.report_type != "conditionnement":
            return Err("WRONG_REPORT_TYPE", f"report {report_id} is not a conditionnement report")
        if header.status != "draft":
            return Err("NOT_EDITABLE", f"a {header.status} report cannot be edited as a draft")

        validation = validate_conditionnement_detail(detail)
        if isinstance(validation, Err):
            return validation

        self._write_detail(tenant_id=tenant_id, report_id=report_id, detail=detail)
        self._connection.execute(
            "UPDATE production.production_reports SET updated_at = NOW() WHERE id = %s", (report_id,)
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="production_report.draft_updated",
            entity_type="production_report",
            entity_id=report_id,
            payload=_detail_to_json(detail),
        )
        return Ok(self._read(tenant_id=tenant_id, report_id=report_id))

    def correct_report(
        self, *, tenant_id: str, actor_id: str, report_id: str, detail: ConditionnementReportDetail, reason: str
    ) -> Result[dict]:
        """A validator changes what the team packed, before approving it.

        Same contract as the daily report's correction: gated by
        production.admin_reports, appends a new revision with its reason, and never
        touches the snapshot the team submitted.
        """
        if not reason.strip():
            return Err("MISSING_REASON", "a correction must record why the figures were changed")

        header = self._reports._load_header(tenant_id=tenant_id, report_id=report_id, for_update=True)
        if header is None:
            return Err("NOT_FOUND", f"report {report_id} not found")
        if header.report_type != "conditionnement":
            return Err("WRONG_REPORT_TYPE", f"report {report_id} is not a conditionnement report")
        if header.status != "submitted":
            return Err("NOT_CORRECTABLE", f"only a submitted report can be corrected, not a {header.status} one")

        validation = validate_conditionnement_detail(detail)
        if isinstance(validation, Err):
            return validation

        before = load_conditionnement_detail(self._connection, tenant_id=tenant_id, report_id=report_id)
        new_revision = header.revision + 1
        self._write_detail(tenant_id=tenant_id, report_id=report_id, detail=detail)
        self._reports._write_revision(
            tenant_id=tenant_id,
            report_id=report_id,
            revision=new_revision,
            detail=detail,
            reason=reason,
            actor_id=actor_id,
        )
        self._connection.execute(
            "UPDATE production.production_reports SET revision = %s, updated_at = NOW() WHERE id = %s",
            (new_revision, report_id),
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="production_report.corrected",
            entity_type="production_report",
            entity_id=report_id,
            payload={
                "revision": new_revision,
                "reason": reason,
                "before": _detail_to_json(before) if before is not None else None,
                "after": _detail_to_json(detail),
            },
        )
        return Ok(self._read(tenant_id=tenant_id, report_id=report_id))

    def _write_detail(self, *, tenant_id: str, report_id: str, detail: ConditionnementReportDetail) -> None:
        assignments = ", ".join(f"{column.strip()} = %s" for column in _COLUMNS.split(","))
        self._connection.execute(
            f"UPDATE production.conditionnement_reports SET {assignments} WHERE report_id = %s AND tenant_id = %s",
            (*_values(detail), report_id, tenant_id),
        )
        replace_waste_lines(
            self._connection, tenant_id=tenant_id, report_id=report_id, lines=detail.waste_lines
        )

    def _read(self, *, tenant_id: str, report_id: str) -> dict:
        return {
            "report": self._reports._load_header(tenant_id=tenant_id, report_id=report_id),
            "detail": load_conditionnement_detail(self._connection, tenant_id=tenant_id, report_id=report_id),
        }
