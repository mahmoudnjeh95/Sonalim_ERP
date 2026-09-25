from __future__ import annotations

import datetime
from dataclasses import asdict

import psycopg
from psycopg.types.json import Jsonb
from ulid import ULID

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from core.events.outbox import publish_event
from modules.production.api.downtime_line_store import (
    delete_downtime_lines,
    load_downtime_lines,
    replace_downtime_lines,
)
from modules.production.api.report_product import finished_product_of_report
from modules.production.api.report_stock_service import ReportStockService
from modules.production.api.semolina_line_store import (
    delete_semolina_lines,
    load_semolina_lines,
    replace_semolina_lines,
)
from modules.production.api.waste_line_store import (
    delete_waste_lines,
    load_waste_lines,
    replace_waste_lines,
)
from modules.production.api.waste_type_service import custom_waste_categories
from modules.production.domain.production_report import (
    DailyReportDetail,
    DowntimeLine,
    ProductionReport,
    SemolinaLine,
    WasteLine,
    transition_report,
    validate_conditionnement_stock_targets,
    validate_daily_detail,
    validate_daily_stock_targets,
    validate_report_header,
)
from modules.warehouse.api.service import StockService

_HEADER_COLUMNS = """
    id, of_id, report_type, report_date, status, revision, team, work_center_id, equipment_id, shift,
    created_by, submitted_at, validated_by, validated_at, rejection_reason
"""

# Déchets, semoule and arrêts are deliberately absent: they live in
# production.report_waste_lines, production.report_semolina_lines and
# production.report_downtime_lines, one row per item, and are attached to the
# detail on load.
_DAILY_COLUMNS = """
    dough_quantity, finished_product_quantity,
    regrind_quantity, water_quantity, fuel_quantity, gasoil_quantity, electricity_quantity,
    start_time, end_time, production_minutes,
    raw_material_location_id, regrind_input_quantity, regrind_input_product_id,
    regrind_product_id, mold_id, water_percentage, semolina_flow_rate,
    fuel_supplier_id, gasoil_supplier_id, gasoil_flow_rate, generator_hours
"""

# An OF that has been closed or written off takes no new reports: closure is the
# point after which production data stops arriving. Quality is the exception, and
# it lives in the qc module precisely so it can keep writing against a closed OF.
_OF_STATUSES_ACCEPTING_REPORTS = {"planned", "ongoing", "suspended"}


def _row_to_header(row: tuple) -> ProductionReport:
    (
        report_id,
        of_id,
        report_type,
        report_date,
        status,
        revision,
        team,
        work_center_id,
        equipment_id,
        shift,
        created_by,
        submitted_at,
        validated_by,
        validated_at,
        rejection_reason,
    ) = row
    return ProductionReport(
        id=report_id,
        of_id=of_id,
        report_type=report_type,
        report_date=report_date,
        status=status,
        revision=revision,
        team=team,
        work_center_id=work_center_id,
        equipment_id=equipment_id,
        shift=shift,
        created_by=created_by,
        submitted_at=submitted_at,
        validated_by=validated_by,
        validated_at=validated_at,
        rejection_reason=rejection_reason,
    )


def _row_to_daily_detail(
    row: tuple,
    waste_lines: tuple[WasteLine, ...] = (),
    semolina_lines: tuple[SemolinaLine, ...] = (),
    downtime_lines: tuple[DowntimeLine, ...] = (),
) -> DailyReportDetail:
    return DailyReportDetail(
        dough_quantity=float(row[0]),
        finished_product_quantity=float(row[1]),
        regrind_quantity=float(row[2]),
        water_quantity=float(row[3]),
        fuel_quantity=float(row[4]),
        gasoil_quantity=float(row[5]),
        electricity_quantity=float(row[6]),
        start_time=row[7],
        end_time=row[8],
        production_minutes=int(row[9]),
        raw_material_location_id=row[10],
        regrind_input_quantity=float(row[11]),
        regrind_input_product_id=row[12],
        regrind_product_id=row[13],
        mold_id=row[14],
        water_percentage=float(row[15]),
        semolina_flow_rate=float(row[16]),
        fuel_supplier_id=row[17],
        gasoil_supplier_id=row[18],
        gasoil_flow_rate=float(row[19]),
        generator_hours=float(row[20]),
        waste_lines=waste_lines,
        semolina_lines=semolina_lines,
        downtime_lines=downtime_lines,
    )


def _detail_to_json(detail: object) -> dict:
    """Freeze any report detail into the shape stored in report_revisions.

    Plain JSON-safe values only, so a snapshot stays readable long after the
    dataclass has gained or lost fields.
    """
    payload = asdict(detail)  # type: ignore[call-overload]
    for key, value in payload.items():
        if isinstance(value, (datetime.time, datetime.date, datetime.datetime)):
            payload[key] = value.isoformat()
    return payload


class ProductionReportService:
    """The operational record of a shift, and the desk it is approved at.

    A report is the team's claim until a supervisor validates it. Nothing here
    posts stock yet — validation becomes the only door inventory moves through in
    Phase 5 — but the guarantees that make that safe are established now: a
    row-locked status transition so a retried validate cannot pass twice, and a
    revision snapshot so a validator's correction can always be told apart from
    what the team actually entered.
    """

    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    # ---- reads -----------------------------------------------------------

    def _load_header(self, *, tenant_id: str, report_id: str, for_update: bool = False) -> ProductionReport | None:
        row = self._connection.execute(
            f"""
            SELECT {_HEADER_COLUMNS} FROM production.production_reports
            WHERE id = %s AND tenant_id = %s
            {'FOR UPDATE' if for_update else ''}
            """,
            (report_id, tenant_id),
        ).fetchone()
        return _row_to_header(row) if row is not None else None

    def _load_daily_detail(self, *, tenant_id: str, report_id: str) -> DailyReportDetail | None:
        row = self._connection.execute(
            f"SELECT {_DAILY_COLUMNS} FROM production.daily_reports WHERE report_id = %s AND tenant_id = %s",
            (report_id, tenant_id),
        ).fetchone()
        if row is None:
            return None
        return _row_to_daily_detail(
            row,
            load_waste_lines(self._connection, tenant_id=tenant_id, report_id=report_id),
            load_semolina_lines(self._connection, tenant_id=tenant_id, report_id=report_id),
            load_downtime_lines(self._connection, tenant_id=tenant_id, report_id=report_id),
        )

    def _load_detail(self, *, tenant_id: str, report_id: str, report_type: str):
        """Load whichever detail table this report type keeps its figures in.

        Imported lazily: the conditionnement service builds on this one, so a
        top-level import would close the cycle.
        """
        if report_type == "daily":
            return self._load_daily_detail(tenant_id=tenant_id, report_id=report_id)
        if report_type == "conditionnement":
            from modules.production.api.conditionnement_service import load_conditionnement_detail

            return load_conditionnement_detail(self._connection, tenant_id=tenant_id, report_id=report_id)
        return None

    @staticmethod
    def _validate_stock_targets(report_type: str, detail) -> Result[None]:
        """What a report must name before it is allowed to move stock."""
        if report_type == "conditionnement":
            return validate_conditionnement_stock_targets(detail)
        return validate_daily_stock_targets(detail)

    def _validate_detail(self, report_type: str, detail, *, tenant_id: str) -> Result[None]:
        waste_categories = custom_waste_categories(self._connection, tenant_id=tenant_id, report_type=report_type)
        if report_type == "conditionnement":
            from modules.production.domain.production_report import validate_conditionnement_detail

            return validate_conditionnement_detail(detail, waste_categories=waste_categories)
        return validate_daily_detail(detail, waste_categories=waste_categories)

    def get_report(self, *, tenant_id: str, report_id: str) -> dict | None:
        header = self._load_header(tenant_id=tenant_id, report_id=report_id)
        if header is None:
            return None
        detail = self._load_detail(tenant_id=tenant_id, report_id=report_id, report_type=header.report_type)
        return {"report": header, "detail": detail}

    def list_reports(
        self,
        *,
        tenant_id: str,
        of_id: str | None = None,
        status: str | None = None,
        report_type: str | None = None,
    ) -> list[ProductionReport]:
        clauses = ["tenant_id = %s"]
        params: list[object] = [tenant_id]
        if of_id is not None:
            clauses.append("of_id = %s")
            params.append(of_id)
        if status is not None:
            clauses.append("status = %s")
            params.append(status)
        if report_type is not None:
            clauses.append("report_type = %s")
            params.append(report_type)

        rows = self._connection.execute(
            f"""
            SELECT {_HEADER_COLUMNS} FROM production.production_reports
            WHERE {' AND '.join(clauses)}
            ORDER BY report_date DESC, created_at DESC
            """,
            params,
        ).fetchall()
        return [_row_to_header(row) for row in rows]

    def list_stage_signals(self, *, tenant_id: str, of_id: str) -> dict[str, dict[str, bool]]:
        """Whether each of an OF's reports carries figures, keyed by report id.

        The production-flow card (deriveStageStates on the frontend) only ever
        asks a report's detail three yes/no questions: did it pour semoule
        (melange), weigh finished product (petrissage), or count packets
        (extrusion/conditionnement/stockage, all the same figure). Fetching a
        full detail per report to answer that -- report_id -> GET
        /reports/{id}, once per report -- turned a long-running OF's page load
        into as many round trips as it has reports (OF-000085: 138, one per
        daily/conditionnement report). One query against both detail tables,
        restated to these three booleans, replaces every one of those trips.
        """
        rows = self._connection.execute(
            """
            SELECT r.id,
                   EXISTS (
                       SELECT 1 FROM production.report_semolina_lines sl
                       WHERE sl.report_id = r.id AND sl.tenant_id = r.tenant_id AND sl.quantity > 0
                   ) AS poured_semoule,
                   COALESCE(d.finished_product_quantity, 0) > 0 AS weighed_finished_product,
                   COALESCE(c.packets_counted, 0) > 0 AS counted_packets
            FROM production.production_reports r
            LEFT JOIN production.daily_reports d ON d.report_id = r.id AND d.tenant_id = r.tenant_id
            LEFT JOIN production.conditionnement_reports c ON c.report_id = r.id AND c.tenant_id = r.tenant_id
            WHERE r.tenant_id = %s AND r.of_id = %s AND r.status != 'rejected'
            """,
            (tenant_id, of_id),
        ).fetchall()
        return {
            report_id: {
                "poured_semoule": bool(poured_semoule),
                "weighed_finished_product": bool(weighed_finished_product),
                "counted_packets": bool(counted_packets),
            }
            for report_id, poured_semoule, weighed_finished_product, counted_packets in rows
        }

    def list_revisions(self, *, tenant_id: str, report_id: str) -> list[dict]:
        rows = self._connection.execute(
            """
            SELECT revision, detail, reason, actor_id, created_at
            FROM production.report_revisions
            WHERE report_id = %s AND tenant_id = %s
            ORDER BY revision
            """,
            (report_id, tenant_id),
        ).fetchall()
        return [
            {
                "revision": revision,
                "detail": detail,
                "reason": reason,
                "actor_id": actor_id,
                "created_at": created_at.isoformat(),
            }
            for revision, detail, reason, actor_id, created_at in rows
        ]

    # ---- draft lifecycle -------------------------------------------------

    def create_daily_report(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        of_id: str,
        report_date: datetime.date,
        detail: DailyReportDetail | None = None,
        team: str | None = None,
        work_center_id: str | None = None,
        equipment_id: str | None = None,
        shift: str | None = None,
    ) -> Result[dict]:
        header_validation = validate_report_header(report_type="daily", of_id=of_id)
        if isinstance(header_validation, Err):
            return header_validation

        detail = detail or DailyReportDetail()
        detail_validation = validate_daily_detail(
            detail, waste_categories=custom_waste_categories(self._connection, tenant_id=tenant_id, report_type="daily")
        )
        if isinstance(detail_validation, Err):
            return detail_validation

        work_order = self._connection.execute(
            "SELECT status, work_center_id FROM production.work_orders WHERE id = %s AND tenant_id = %s",
            (of_id, tenant_id),
        ).fetchone()
        if work_order is None:
            return Err("NOT_FOUND", f"work order {of_id} not found", f"OF {of_id} introuvable")
        of_status, of_work_center_id = work_order
        if of_status not in _OF_STATUSES_ACCEPTING_REPORTS:
            return Err(
                "OF_NOT_OPEN",
                f"work order {of_id} is {of_status} and accepts no new reports",
                f"l'OF {of_id} est {of_status} et n'accepte plus de nouveaux rapports",
            )

        if self._duplicate_report_exists(
            tenant_id=tenant_id, of_id=of_id, report_type="daily", report_date=report_date, shift=shift
        ):
            return Err(
                "DUPLICATE_REPORT",
                "a daily report already exists for this work order, date and shift",
                "un rapport journalier existe déjà pour cet OF, cette date et ce shift",
            )

        report_id = str(ULID())
        self._connection.execute(
            """
            INSERT INTO production.production_reports
                (id, tenant_id, of_id, report_type, report_date, status, revision, team, work_center_id,
                 equipment_id, shift, created_by)
            VALUES (%s, %s, %s, 'daily', %s, 'draft', 1, %s, %s, %s, %s, %s)
            """,
            (
                report_id,
                tenant_id,
                of_id,
                report_date,
                team,
                # The OF's own work center is the default: the report is about the
                # machine the order runs on, so it should never have to be re-picked.
                work_center_id if work_center_id is not None else of_work_center_id,
                equipment_id,
                shift,
                actor_id,
            ),
        )
        self._insert_daily_detail(tenant_id=tenant_id, report_id=report_id, detail=detail)
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="production_report.created",
            entity_type="production_report",
            entity_id=report_id,
            payload={"of_id": of_id, "report_type": "daily", "report_date": report_date.isoformat()},
        )
        return Ok(
            {
                "report": self._load_header(tenant_id=tenant_id, report_id=report_id),
                "detail": self._load_daily_detail(tenant_id=tenant_id, report_id=report_id),
            }
        )

    def update_daily_draft(
        self, *, tenant_id: str, actor_id: str, report_id: str, detail: DailyReportDetail
    ) -> Result[dict]:
        """Edit a report the team still owns. Allowed only while it is a draft."""
        header = self._load_header(tenant_id=tenant_id, report_id=report_id, for_update=True)
        if header is None:
            return Err("NOT_FOUND", f"report {report_id} not found", f"rapport {report_id} introuvable")
        if header.report_type != "daily":
            return Err(
                "WRONG_REPORT_TYPE",
                f"report {report_id} is not a daily report",
                f"le rapport {report_id} n'est pas un rapport journalier",
            )
        if header.status != "draft":
            return Err(
                "NOT_EDITABLE",
                f"a {header.status} report cannot be edited as a draft",
                f"un rapport {header.status} ne peut pas être modifié comme brouillon",
            )

        validation = validate_daily_detail(
            detail, waste_categories=custom_waste_categories(self._connection, tenant_id=tenant_id, report_type="daily")
        )
        if isinstance(validation, Err):
            return validation

        self._update_daily_detail(tenant_id=tenant_id, report_id=report_id, detail=detail)
        self._touch(report_id)
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="production_report.draft_updated",
            entity_type="production_report",
            entity_id=report_id,
            payload=_detail_to_json(detail),
        )
        return Ok(
            {
                "report": self._load_header(tenant_id=tenant_id, report_id=report_id),
                "detail": self._load_daily_detail(tenant_id=tenant_id, report_id=report_id),
            }
        )

    # ---- validation desk -------------------------------------------------

    def submit_report(self, *, tenant_id: str, actor_id: str, report_id: str) -> Result[ProductionReport]:
        """Hand the report to the validation desk, freezing the team's figures.

        The snapshot written here is the team's record. Nothing overwrites it —
        a validator's later correction appends a new revision instead.
        """
        header = self._load_header(tenant_id=tenant_id, report_id=report_id, for_update=True)
        if header is None:
            return Err("NOT_FOUND", f"report {report_id} not found", f"rapport {report_id} introuvable")

        result = transition_report(header, "submitted")
        if isinstance(result, Err):
            return result

        # A draft may be saved before the shift knows which machine it ran on,
        # but a report handed to the validation desk without one can never be
        # attributed to a machine again -- so this is enforced here, not at
        # creation, the same way stock targets are.
        if not header.equipment_id:
            return Err(
                "MISSING_MACHINE",
                "a report must name the machine it ran on before it can be submitted",
                "un rapport doit nommer la machine sur laquelle il a tourné avant de pouvoir être rendu",
            )

        detail = self._load_detail(tenant_id=tenant_id, report_id=report_id, report_type=header.report_type)
        if detail is None:
            return Err(
                "NOT_FOUND",
                f"report {report_id} has no detail to submit",
                f"le rapport {report_id} n'a pas de détail à rendre",
            )
        validation = self._validate_detail(header.report_type, detail, tenant_id=tenant_id)
        if isinstance(validation, Err):
            return validation

        # A draft may be saved half-finished, but a report handed to the
        # validation desk must already say what it moves and where — otherwise the
        # gap only surfaces at validation, when a supervisor can do least about it.
        targets = self._validate_stock_targets(header.report_type, detail)
        if isinstance(targets, Err):
            return targets

        self._write_revision(
            tenant_id=tenant_id,
            report_id=report_id,
            revision=header.revision,
            detail=detail,
            reason=None,
            actor_id=actor_id,
        )
        self._connection.execute(
            "UPDATE production.production_reports SET status = 'submitted', submitted_at = NOW(), updated_at = NOW() WHERE id = %s",
            (report_id,),
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="production_report.submitted",
            entity_type="production_report",
            entity_id=report_id,
            payload={"revision": header.revision},
        )
        return Ok(self._load_header(tenant_id=tenant_id, report_id=report_id))  # type: ignore[arg-type]

    def correct_daily_report(
        self, *, tenant_id: str, actor_id: str, report_id: str, detail: DailyReportDetail, reason: str
    ) -> Result[dict]:
        """A validator changes what the team entered, before approving it.

        Gated in the router by production.admin_reports, deliberately separate
        from the right to validate: a supervisor who may approve a report but not
        rewrite it is a permission change, not a code change. The correction is
        appended as a new revision with its reason, so the submitted originals
        stay one query away.
        """
        if not reason.strip():
            return Err(
                "MISSING_REASON",
                "a correction must record why the figures were changed",
                "une correction doit enregistrer pourquoi les chiffres ont changé",
            )

        header = self._load_header(tenant_id=tenant_id, report_id=report_id, for_update=True)
        if header is None:
            return Err("NOT_FOUND", f"report {report_id} not found", f"rapport {report_id} introuvable")
        if header.report_type != "daily":
            return Err(
                "WRONG_REPORT_TYPE",
                f"report {report_id} is not a daily report",
                f"le rapport {report_id} n'est pas un rapport journalier",
            )
        if header.status != "submitted":
            # Correcting a validated report means reversing stock that was already
            # posted against its figures; that path ships with Phase 5, not here.
            return Err(
                "NOT_CORRECTABLE",
                f"only a submitted report can be corrected, not a {header.status} one",
                f"seul un rapport rendu peut être corrigé, pas un rapport {header.status}",
            )

        validation = validate_daily_detail(
            detail, waste_categories=custom_waste_categories(self._connection, tenant_id=tenant_id, report_type="daily")
        )
        if isinstance(validation, Err):
            return validation

        before = self._load_daily_detail(tenant_id=tenant_id, report_id=report_id)
        new_revision = header.revision + 1
        self._update_daily_detail(tenant_id=tenant_id, report_id=report_id, detail=detail)
        self._write_revision(
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
        return Ok(
            {
                "report": self._load_header(tenant_id=tenant_id, report_id=report_id),
                "detail": self._load_daily_detail(tenant_id=tenant_id, report_id=report_id),
            }
        )

    def validate_report(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        report_id: str,
        correlation_id: str | None = None,
        shortfall_comment: str | None = None,
        regrind_work_center_id: str | None = None,
    ) -> Result[ProductionReport]:
        """Make a report official — and post the stock it moved.

        This is the only door inventory moves through in production. The row lock
        plus the transition check is what stops a retried call posting the same
        stock twice, and only a `submitted` report can reach here, so draft and
        rejected reports never post as a matter of enforcement rather than
        convention.

        A raw-material shortfall does not block anything: the movement goes
        through and the balance may go negative. What it does require is an
        explanation, so a negative balance always carries an account of itself
        rather than becoming background noise.
        """
        correlation_id = correlation_id or str(ULID())

        header = self._load_header(tenant_id=tenant_id, report_id=report_id, for_update=True)
        if header is None:
            return Err("NOT_FOUND", f"report {report_id} not found", f"rapport {report_id} introuvable")

        result = transition_report(header, "validated")
        if isinstance(result, Err):
            return result

        detail = self._load_detail(tenant_id=tenant_id, report_id=report_id, report_type=header.report_type)
        if detail is None:
            return Err(
                "NOT_FOUND",
                f"report {report_id} has no detail to validate",
                f"le rapport {report_id} n'a pas de détail à valider",
            )

        targets = self._validate_stock_targets(header.report_type, detail)
        if isinstance(targets, Err):
            return targets

        # Look before writing anything: if a withdrawal would go negative the
        # validator has to explain it, and refusing up front is better than
        # posting half a report and then complaining.
        stock = ReportStockService(self._connection)
        if header.report_type == "daily":
            shortfalls = stock.daily_shortfalls(tenant_id=tenant_id, detail=detail)
        elif header.report_type == "conditionnement":
            shortfalls = stock.conditionnement_shortfalls(tenant_id=tenant_id, detail=detail)
        else:
            shortfalls = []
        if shortfalls and not (shortfall_comment or "").strip():
            return Err(
                "SHORTFALL_COMMENT_REQUIRED",
                "this report consumes more than the stock figure holds; validating it needs a comment explaining why",
                "ce rapport consomme plus que ce que le stock détient ; le valider nécessite un commentaire expliquant pourquoi",
            )

        self._connection.execute(
            """
            UPDATE production.production_reports
            SET status = 'validated', validated_by = %s, validated_at = NOW(), rejection_reason = NULL,
                shortfall_comment = %s, updated_at = NOW()
            WHERE id = %s
            """,
            (actor_id, shortfall_comment, report_id),
        )

        effects: dict[str, object] = {}
        if header.report_type == "daily":
            posted = stock.post_daily_report(
                tenant_id=tenant_id,
                actor_id=actor_id,
                header=header,
                detail=detail,
                correlation_id=correlation_id,
            )
            if isinstance(posted, Err):
                return posted
            effects["movements"] = posted.value

            scrap = self._record_regrind_scrap(tenant_id=tenant_id, actor_id=actor_id, header=header)
            if isinstance(scrap, Err):
                return scrap
            effects["scrap_record_id"] = scrap.value

            if scrap.value is not None:
                batch = self._open_regrind_order(
                    tenant_id=tenant_id,
                    actor_id=actor_id,
                    header=header,
                    scrap_record_id=scrap.value,
                    regrind_work_center_id=regrind_work_center_id,
                )
                if isinstance(batch, Err):
                    return batch
                effects["regrind_work_order_id"] = batch.value

        elif header.report_type == "conditionnement":
            work_order = self._connection.execute(
                "SELECT product_id FROM production.work_orders WHERE id = %s AND tenant_id = %s",
                (header.of_id, tenant_id),
            ).fetchone()
            if work_order is None:
                return Err("NOT_FOUND", f"work order {header.of_id} not found", f"OF {header.of_id} introuvable")

            from modules.production.api.conditionnement_service import freeze_packaging_parameters

            # The report's own product: one work order can pack several.
            finished_product_id = finished_product_of_report(self._connection, tenant_id=tenant_id, report_id=report_id)

            # Before anything is posted: the ecart this report will be judged on
            # has to be pinned to the packaging it was actually validated against.
            effects["packaging_parameters"] = freeze_packaging_parameters(
                self._connection, tenant_id=tenant_id, report_id=report_id, product_id=finished_product_id, detail=detail
            )

            posted = stock.post_conditionnement_report(
                tenant_id=tenant_id,
                actor_id=actor_id,
                header=header,
                detail=detail,
                finished_product_id=finished_product_id,
                correlation_id=correlation_id,
                packets_per_carton=effects["packaging_parameters"]["packets_per_carton"],  # type: ignore[index]
            )
            if isinstance(posted, Err):
                return posted
            effects["movements"] = posted.value

            from modules.production.api.conditionnement_service import register_dlc_lot

            lot = register_dlc_lot(self._connection, tenant_id=tenant_id, actor_id=actor_id, header=header)
            if isinstance(lot, Err):
                return lot
            effects["lot_id"] = lot.value

        publish_event(
            self._connection,
            event_type="production.report.validated",
            producer="production",
            tenant_id=tenant_id,
            correlation_id=correlation_id,
            payload={
                "report_id": report_id,
                "of_id": header.of_id,
                "report_type": header.report_type,
                "report_date": header.report_date.isoformat(),
            },
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="production_report.validated",
            entity_type="production_report",
            entity_id=report_id,
            payload={
                "of_id": header.of_id,
                "revision": header.revision,
                "shortfalls": shortfalls,
                "shortfall_comment": shortfall_comment,
                **effects,
            },
        )
        return Ok(self._load_header(tenant_id=tenant_id, report_id=report_id))  # type: ignore[arg-type]

    # ---- undoing a validated report --------------------------------------

    def _reverse_validated_effects(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        header: ProductionReport,
        correlation_id: str,
        force: bool = False,
        new_regrind_quantity: float | None = None,
        reason: str | None = None,
    ) -> Result[dict]:
        """Undo everything validating this report caused.

        Stock is reversed by posting the mirror movements rather than editing the
        ledger, so the original and its correction both stay visible.

        The rebroyat chain is the awkward part: validating a daily report can open
        a regrind OF, and if that batch has already been ground and received into
        stock there is no honest way to unwind it — the material physically
        exists. That case is refused unless `force` is set, in which case the
        receipt itself is reversed too (see `_unwind_regrind`) rather than left
        to silently disagree with a report that no longer exists.
        """
        detail = self._load_detail(tenant_id=tenant_id, report_id=header.id, report_type=header.report_type)
        if detail is None:
            return Err("NOT_FOUND", f"report {header.id} has no detail", f"le rapport {header.id} n'a pas de détail")

        stock = ReportStockService(self._connection)
        if header.report_type == "daily":
            undone = stock.post_daily_report(
                tenant_id=tenant_id, actor_id=actor_id, header=header, detail=detail,
                correlation_id=correlation_id, reverse=True,
            )
        else:
            work_order = self._connection.execute(
                "SELECT product_id FROM production.work_orders WHERE id = %s AND tenant_id = %s",
                (header.of_id, tenant_id),
            ).fetchone()
            if work_order is None:
                return Err("NOT_FOUND", f"work order {header.of_id} not found", f"OF {header.of_id} introuvable")

            from modules.production.api.conditionnement_service import load_snapshot_packets_per_carton

            snapshot_packets_per_carton = load_snapshot_packets_per_carton(
                self._connection, tenant_id=tenant_id, report_id=header.id
            )
            undone = stock.post_conditionnement_report(
                tenant_id=tenant_id, actor_id=actor_id, header=header, detail=detail,
                finished_product_id=finished_product_of_report(self._connection, tenant_id=tenant_id, report_id=header.id),
                correlation_id=correlation_id, reverse=True,
                packets_per_carton=snapshot_packets_per_carton,
            )
        if isinstance(undone, Err):
            return undone

        removed_scrap = 0
        reversed_regrind_stock: list[dict] = []
        skip_regrind_rebuild = False
        if header.report_type == "daily":
            unwound = self._unwind_regrind(
                tenant_id=tenant_id, actor_id=actor_id, header=header, correlation_id=correlation_id, force=force,
                new_regrind_quantity=new_regrind_quantity, reason=reason,
            )
            if isinstance(unwound, Err):
                return unwound
            removed_scrap = unwound.value["removed_scrap_records"]
            reversed_regrind_stock = unwound.value["reversed_regrind_stock"]
            skip_regrind_rebuild = unwound.value.get("skip_regrind_rebuild", False)

        return Ok(
            {
                "reversed_movements": undone.value,
                "removed_scrap_records": removed_scrap,
                "reversed_regrind_stock": reversed_regrind_stock,
                "skip_regrind_rebuild": skip_regrind_rebuild,
            }
        )

    def _unwind_regrind(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        header: ProductionReport,
        correlation_id: str,
        force: bool = False,
        new_regrind_quantity: float | None = None,
        reason: str | None = None,
    ) -> Result[dict]:
        """Remove the scrap and regrind OF this report's validation created.

        A batch already ground and received into stock is refused unless `force`
        is set — its output physically exists, so silently deleting the order
        underneath it would leave stock nobody can explain. `force` posts the
        mirror movement that undoes the receipt (the same "reverse by posting
        the opposite" rule every other report reversal follows) before removing
        the batch, its inputs and the work order itself.

        `new_regrind_quantity` marks the other caller, `correct_validated_report`:
        there, a closed batch isn't refused outright — it's reconciled against
        the corrected figure instead, see `_reconcile_closed_regrind_batch`.
        `delete_report` never passes it, so its behavior here is unchanged.
        """
        scrap_rows = self._connection.execute(
            """
            SELECT id FROM production.scrap_records
            WHERE tenant_id = %s AND work_order_id = %s AND scrap_type = 'daily_report'
              AND source_note LIKE %s
            """,
            (tenant_id, header.of_id, f"daily report {header.id}%"),
        ).fetchall()
        if not scrap_rows:
            return Ok({"removed_scrap_records": 0, "reversed_regrind_stock": [], "skip_regrind_rebuild": False})
        scrap_ids = [row[0] for row in scrap_rows]

        batch_rows = self._connection.execute(
            """
            SELECT DISTINCT rbi.regrind_batch_work_order_id, wo.status, wo.product_id, rb.actual_output_quantity,
                   rb.input_quantity_total
            FROM production.regrind_batch_inputs rbi
            JOIN production.work_orders wo ON wo.id = rbi.regrind_batch_work_order_id
            JOIN production.regrind_batches rb ON rb.work_order_id = rbi.regrind_batch_work_order_id
            WHERE rbi.scrap_record_id = ANY(%s)
            """,
            (scrap_ids,),
        ).fetchall()

        if new_regrind_quantity is not None:
            return self._reconcile_closed_regrind_batch(
                tenant_id=tenant_id, actor_id=actor_id, header=header, force=force, reason=reason,
                new_regrind_quantity=new_regrind_quantity, batch_rows=batch_rows,
            )

        if not force:
            for _, batch_status, _, _, _ in batch_rows:
                if batch_status == "closed":
                    return Err(
                        "REGRIND_ALREADY_COMPLETED",
                        "the rebroyat order this report opened has already been ground and received into stock;"
                        " it cannot be unwound automatically",
                        "l'OF de rebroyat ouvert par ce rapport a déjà été broyé et reçu en stock ;"
                        " il ne peut pas être défait automatiquement",
                    )

        stock = StockService(self._connection)
        reversed_regrind_stock: list[dict] = []
        for batch_of_id, batch_status, product_id, actual_output_quantity, _ in batch_rows:
            if batch_status != "closed" or actual_output_quantity is None or float(actual_output_quantity) <= 0:
                continue
            # The batch's own receipt is the only record of which location it
            # landed in -- regrind_batches never stores one, so it is looked up
            # from the stock move `complete_batch` posted rather than guessed at.
            receipt = stock.list_stock_moves(
                tenant_id=tenant_id, product_id=product_id, move_type="production",
                reference=f"work_order:{batch_of_id}", limit=1,
            )
            if not receipt:
                return Err(
                    "REGRIND_STOCK_MOVE_NOT_FOUND",
                    f"no stock receipt found for regrind order {batch_of_id}; refusing to force-delete blind",
                    f"aucune réception de stock trouvée pour l'OF de rebroyat {batch_of_id} ; suppression forcée refusée à l'aveugle",
                )
            location_id = receipt[0]["location_id"]
            quantity = float(actual_output_quantity)
            reversed_move = stock.post_production_movement(
                tenant_id=tenant_id, product_id=product_id, location_id=location_id, quantity=quantity,
                direction="out", correlation_id=correlation_id, reference=f"work_order:{batch_of_id}:reversed",
                move_type="production_reversal", actor_id=actor_id,
                source_type="production.regrind_batch", source_id=batch_of_id, of_id=batch_of_id,
            )
            if isinstance(reversed_move, Err):
                return reversed_move
            reversed_regrind_stock.append(
                {"work_order_id": batch_of_id, "product_id": product_id, "location_id": location_id, "quantity": quantity}
            )

        for batch_of_id, _, _, _, _ in batch_rows:
            self._connection.execute(
                "DELETE FROM production.regrind_batch_inputs WHERE regrind_batch_work_order_id = %s", (batch_of_id,)
            )
            self._connection.execute(
                "DELETE FROM production.regrind_batches WHERE work_order_id = %s AND tenant_id = %s",
                (batch_of_id, tenant_id),
            )
            self._connection.execute(
                "DELETE FROM production.work_orders WHERE id = %s AND tenant_id = %s", (batch_of_id, tenant_id)
            )

        self._connection.execute("DELETE FROM production.scrap_records WHERE id = ANY(%s)", (scrap_ids,))
        return Ok(
            {
                "removed_scrap_records": len(scrap_ids),
                "reversed_regrind_stock": reversed_regrind_stock,
                "skip_regrind_rebuild": False,
            }
        )

    def _reconcile_closed_regrind_batch(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        header: ProductionReport,
        force: bool,
        reason: str | None,
        new_regrind_quantity: float,
        batch_rows: list,
    ) -> Result[dict]:
        """Compare a correction's rebroyat figure against a closed batch instead of refusing it outright.

        Only a closed batch needs this: an open one never received stock, so it
        can still be unwound and rebuilt exactly like the normal path. A closed
        one's output physically exists, so the three ways the figure can move
        are handled instead of blocked:
          - unchanged: leave the batch alone.
          - higher: the batch can't retroactively absorb more input, so a
            second, independent order is opened for just the difference —
            confirmed first via `force`, the same gate `delete_report` uses.
          - lower: the batch already produced and received the larger amount,
            so on-hand is reduced by the difference instead, carrying the
            correction's own reason for the audit trail. No confirmation
            needed: nothing is being destroyed, only reconciled.
        """
        closed = [row for row in batch_rows if row[1] == "closed"]
        other = [row for row in batch_rows if row[1] != "closed"]

        if len(closed) > 1:
            return Err(
                "REGRIND_MULTIPLE_CLOSED_BATCHES",
                "more than one closed rebroyat order is tied to this report; resolve manually",
                "plus d'un OF de rebroyat clôturé est lié à ce rapport ; à résoudre manuellement",
            )

        # Any other (non-closed) batch this report opened -- e.g. a still-open
        # delta order from an earlier correction -- never received stock, so it
        # is unwound exactly like the normal path.
        removed_scrap = 0
        if other:
            other_scrap_rows = self._connection.execute(
                """
                SELECT scrap_record_id FROM production.regrind_batch_inputs
                WHERE regrind_batch_work_order_id = ANY(%s)
                """,
                ([row[0] for row in other],),
            ).fetchall()
            other_scrap_ids = [row[0] for row in other_scrap_rows]
            for batch_of_id, _, _, _, _ in other:
                self._connection.execute(
                    "DELETE FROM production.regrind_batch_inputs WHERE regrind_batch_work_order_id = %s",
                    (batch_of_id,),
                )
                self._connection.execute(
                    "DELETE FROM production.regrind_batches WHERE work_order_id = %s AND tenant_id = %s",
                    (batch_of_id, tenant_id),
                )
                self._connection.execute(
                    "DELETE FROM production.work_orders WHERE id = %s AND tenant_id = %s", (batch_of_id, tenant_id)
                )
            if other_scrap_ids:
                self._connection.execute("DELETE FROM production.scrap_records WHERE id = ANY(%s)", (other_scrap_ids,))
            removed_scrap = len(other_scrap_ids)

        if not closed:
            return Ok({"removed_scrap_records": removed_scrap, "reversed_regrind_stock": [], "skip_regrind_rebuild": False})

        batch_of_id, _, product_id, _, input_quantity_total = closed[0]
        input_quantity_total = float(input_quantity_total)
        delta = new_regrind_quantity - input_quantity_total

        if abs(delta) < 1e-6:
            return Ok({"removed_scrap_records": removed_scrap, "reversed_regrind_stock": [], "skip_regrind_rebuild": True})

        if delta > 0:
            if not force:
                return Err(
                    "REGRIND_DELTA_REQUIRES_NEW_ORDER",
                    f"the rebroyat order this report opened already ground {input_quantity_total:g} kg and is"
                    f" closed; the corrected {new_regrind_quantity:g} kg is {delta:g} kg more — confirm to open a"
                    " new rebroyat order for the difference",
                    f"l'OF de rebroyat ouvert par ce rapport a déjà broyé {input_quantity_total:g} kg et est"
                    f" clôturé ; les {new_regrind_quantity:g} kg corrigés sont {delta:g} kg de plus — confirmez pour"
                    " ouvrir un nouvel OF de rebroyat pour la différence",
                )
            scrap = self._record_regrind_scrap(
                tenant_id=tenant_id, actor_id=actor_id, header=header, quantity_override=delta
            )
            if isinstance(scrap, Err):
                return scrap
            if scrap.value is not None:
                opened = self._open_regrind_order(
                    tenant_id=tenant_id, actor_id=actor_id, header=header, scrap_record_id=scrap.value
                )
                if isinstance(opened, Err):
                    return opened
            return Ok({"removed_scrap_records": removed_scrap, "reversed_regrind_stock": [], "skip_regrind_rebuild": True})

        # delta < 0: the closed batch already produced more than the corrected figure calls for.
        stock = StockService(self._connection)
        receipt = stock.list_stock_moves(
            tenant_id=tenant_id, product_id=product_id, move_type="production",
            reference=f"work_order:{batch_of_id}", limit=1,
        )
        if not receipt:
            return Err(
                "REGRIND_STOCK_MOVE_NOT_FOUND",
                f"no stock receipt found for regrind order {batch_of_id}; refusing to adjust stock blind",
                f"aucune réception de stock trouvée pour l'OF de rebroyat {batch_of_id} ; ajustement de stock refusé à l'aveugle",
            )
        location_id = receipt[0]["location_id"]
        adjusted = stock.adjust_stock(
            tenant_id=tenant_id, product_id=product_id, location_id=location_id, delta=delta,
            reason=reason or "production report correction", actor_id=actor_id,
            reference=f"work_order:{batch_of_id}:report_correction:{header.id}",
        )
        if isinstance(adjusted, Err):
            return adjusted
        return Ok(
            {
                "removed_scrap_records": removed_scrap,
                "reversed_regrind_stock": [
                    {"work_order_id": batch_of_id, "product_id": product_id, "location_id": location_id, "quantity": delta}
                ],
                "skip_regrind_rebuild": True,
            }
        )

    def delete_report(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        report_id: str,
        reason: str,
        correlation_id: str | None = None,
        force: bool = False,
    ) -> Result[dict]:
        """Delete a report, undoing whatever it posted.

        A reason is mandatory. The row itself is gone afterwards, so the audit
        entry is the only record that it ever existed — it carries the full detail
        and the reason, which is exactly what the audit rule asks of a delete.

        `force` is for the one case that is otherwise refused outright: a daily
        report whose rebroyat has already been ground and received into stock.
        Forcing also reverses that receipt and removes the regrind order with the
        report, rather than leaving stock and a now-deleted report disagreeing.
        """
        if not reason.strip():
            return Err("MISSING_REASON", "deleting a report must record why", "supprimer un rapport doit enregistrer pourquoi")

        header = self._load_header(tenant_id=tenant_id, report_id=report_id, for_update=True)
        if header is None:
            return Err("NOT_FOUND", f"report {report_id} not found", f"rapport {report_id} introuvable")

        detail = self._load_detail(tenant_id=tenant_id, report_id=report_id, report_type=header.report_type)
        effects: dict = {}
        if header.status == "validated":
            reversed_effects = self._reverse_validated_effects(
                tenant_id=tenant_id, actor_id=actor_id, header=header,
                correlation_id=correlation_id or str(ULID()), force=force,
            )
            if isinstance(reversed_effects, Err):
                return reversed_effects
            effects = reversed_effects.value

        table = "daily_reports" if header.report_type == "daily" else "conditionnement_reports"
        delete_waste_lines(self._connection, tenant_id=tenant_id, report_id=report_id)
        delete_semolina_lines(self._connection, tenant_id=tenant_id, report_id=report_id)
        delete_downtime_lines(self._connection, tenant_id=tenant_id, report_id=report_id)

        self._connection.execute(f"DELETE FROM production.{table} WHERE report_id = %s", (report_id,))
        self._connection.execute("DELETE FROM production.report_revisions WHERE report_id = %s", (report_id,))
        self._connection.execute("DELETE FROM production.production_reports WHERE id = %s", (report_id,))

        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="production_report.deleted",
            entity_type="production_report",
            entity_id=report_id,
            payload={
                "reason": reason,
                "of_id": header.of_id,
                "report_type": header.report_type,
                "report_date": header.report_date.isoformat(),
                "status_at_deletion": header.status,
                "forced": force,
                "detail": _detail_to_json(detail) if detail is not None else None,
                **effects,
            },
        )
        return Ok({"deleted": report_id, **effects})

    def correct_validated_report(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        report_id: str,
        detail,
        reason: str,
        correlation_id: str | None = None,
        force: bool = False,
    ) -> Result[dict]:
        """Change a validated report's figures, reversing and re-posting stock.

        The old movements are undone and the new ones posted, so inventory always
        matches the figures that justify it. The correction is appended as a new
        revision with its reason — the team's original submission is never touched.

        `force` only matters for a daily report whose rebroyat opened a regrind
        order that's already closed, and only when the corrected figure is
        *higher* than what that order ground — see `_reconcile_closed_regrind_batch`.
        Everywhere else it's a no-op, same as `delete_report`'s own `force`.
        """
        if not reason.strip():
            return Err(
                "MISSING_REASON",
                "a correction must record why the figures were changed",
                "une correction doit enregistrer pourquoi les chiffres ont changé",
            )

        correlation_id = correlation_id or str(ULID())
        header = self._load_header(tenant_id=tenant_id, report_id=report_id, for_update=True)
        if header is None:
            return Err("NOT_FOUND", f"report {report_id} not found", f"rapport {report_id} introuvable")
        if header.status != "validated":
            return Err(
                "NOT_CORRECTABLE",
                "this path is for validated reports; a submitted one is corrected in place",
                "ce chemin est pour les rapports validés ; un rapport rendu se corrige directement",
            )

        targets = self._validate_stock_targets(header.report_type, detail)
        if isinstance(targets, Err):
            return targets
        validation = self._validate_detail(header.report_type, detail, tenant_id=tenant_id)
        if isinstance(validation, Err):
            return validation

        before = self._load_detail(tenant_id=tenant_id, report_id=report_id, report_type=header.report_type)
        reversed_effects = self._reverse_validated_effects(
            tenant_id=tenant_id, actor_id=actor_id, header=header, correlation_id=correlation_id, force=force,
            new_regrind_quantity=detail.regrind_quantity if header.report_type == "daily" else None,
            reason=reason,
        )
        if isinstance(reversed_effects, Err):
            return reversed_effects

        if header.report_type == "daily":
            self._update_daily_detail(tenant_id=tenant_id, report_id=report_id, detail=detail)
        else:
            from modules.production.api.conditionnement_service import write_conditionnement_detail

            write_conditionnement_detail(self._connection, tenant_id=tenant_id, report_id=report_id, detail=detail)

        stock = ReportStockService(self._connection)
        if header.report_type == "daily":
            posted = stock.post_daily_report(
                tenant_id=tenant_id, actor_id=actor_id, header=header, detail=detail, correlation_id=correlation_id
            )
        else:
            work_order = self._connection.execute(
                "SELECT product_id FROM production.work_orders WHERE id = %s AND tenant_id = %s",
                (header.of_id, tenant_id),
            ).fetchone()
            from modules.production.api.conditionnement_service import load_snapshot_packets_per_carton

            snapshot_packets_per_carton = load_snapshot_packets_per_carton(
                self._connection, tenant_id=tenant_id, report_id=report_id
            )
            posted = stock.post_conditionnement_report(
                tenant_id=tenant_id, actor_id=actor_id, header=header, detail=detail,
                finished_product_id=finished_product_of_report(self._connection, tenant_id=tenant_id, report_id=report_id),
                correlation_id=correlation_id,
                packets_per_carton=snapshot_packets_per_carton,
            )
        if isinstance(posted, Err):
            return posted

        # The rebroyat chain is rebuilt from the corrected figures -- unless
        # _reverse_validated_effects already reconciled a closed batch itself
        # (unchanged, a new delta order, or a stock adjustment), in which case
        # rebuilding it here from scratch would double it up.
        if header.report_type == "daily" and not reversed_effects.value.get("skip_regrind_rebuild"):
            scrap = self._record_regrind_scrap(tenant_id=tenant_id, actor_id=actor_id, header=header)
            if isinstance(scrap, Err):
                return scrap
            if scrap.value is not None:
                opened = self._open_regrind_order(
                    tenant_id=tenant_id, actor_id=actor_id, header=header, scrap_record_id=scrap.value
                )
                if isinstance(opened, Err):
                    return opened

        new_revision = header.revision + 1
        self._write_revision(
            tenant_id=tenant_id, report_id=report_id, revision=new_revision,
            detail=detail, reason=reason, actor_id=actor_id,
        )
        self._connection.execute(
            "UPDATE production.production_reports SET revision = %s, updated_at = NOW() WHERE id = %s",
            (new_revision, report_id),
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="production_report.corrected_after_validation",
            entity_type="production_report",
            entity_id=report_id,
            payload={
                "revision": new_revision,
                "reason": reason,
                "before": _detail_to_json(before) if before is not None else None,
                "after": _detail_to_json(detail),
                **reversed_effects.value,
            },
        )
        return Ok(
            {
                "report": self._load_header(tenant_id=tenant_id, report_id=report_id),
                "detail": self._load_detail(
                    tenant_id=tenant_id, report_id=report_id, report_type=header.report_type
                ),
            }
        )

    def _open_regrind_order(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        header: ProductionReport,
        scrap_record_id: str,
        regrind_work_center_id: str | None = None,
    ) -> Result[str | None]:
        """Open the rebroyat OF this report's waste calls for.

        Decision 11: nobody should have to remember to raise it. Blocked rather
        than skipped when no default output product is configured — silently not
        creating the OF would lose the rebroyat entirely, which is worse than a
        clear refusal pointing at the missing configuration.

        The regrind OF runs on its own line, not necessarily the one that filed
        the report, so the validator may name the rebroyeur machine explicitly
        (`regrind_work_center_id`). Left unset, it falls back to decision 15's
        original default: the validating report's own work center.
        """
        from modules.production.api.regrind_service import RegrindService

        scrap_row = self._connection.execute(
            "SELECT id FROM production.scrap_records WHERE id = %s AND tenant_id = %s",
            (scrap_record_id, tenant_id),
        ).fetchone()
        if scrap_row is None:
            return Err("NOT_FOUND", f"scrap record {scrap_record_id} not found", f"rebut {scrap_record_id} introuvable")

        # The output product itself is resolved inside create_regrind_batch, from
        # the tenant-wide regrind default only — never per-input — so this and the
        # manual "create batch" screen can never diverge onto different products.
        work_center_id = regrind_work_center_id or header.work_center_id
        if work_center_id is None:
            row = self._connection.execute(
                "SELECT work_center_id FROM production.work_orders WHERE id = %s AND tenant_id = %s",
                (header.of_id, tenant_id),
            ).fetchone()
            work_center_id = row[0] if row is not None else None
        if work_center_id is None:
            return Err(
                "MISSING_WORK_CENTER",
                "cannot open a regrind order without a work center",
                "impossible d'ouvrir un OF de rebroyat sans poste de charge",
            )

        # output_quantity is left unset: the scrap this report just wrote is
        # recorded in whatever unit its own product uses (tonnes for a raw
        # semolina, kilos for others), which is not necessarily the rebroyat
        # product's own unit. create_regrind_batch converts it and uses that
        # as the estimate -- passing this report's raw `quantity` here would
        # reintroduce the same unit mismatch for the estimate that it now
        # guards against for input_quantity_total.
        batch = RegrindService(self._connection).create_regrind_batch(
            tenant_id=tenant_id,
            actor_id=actor_id,
            scrap_record_ids=[scrap_record_id],
            work_center_id=work_center_id,
        )
        if isinstance(batch, Err):
            return batch
        return Ok(batch.value["work_order"].id)

    def reject_report(
        self, *, tenant_id: str, actor_id: str, report_id: str, reason: str, correlation_id: str | None = None
    ) -> Result[ProductionReport]:
        if not reason.strip():
            return Err(
                "MISSING_REASON",
                "a rejection must say what is wrong with the report",
                "un renvoi doit préciser ce qui ne va pas dans le rapport",
            )

        header = self._load_header(tenant_id=tenant_id, report_id=report_id, for_update=True)
        if header is None:
            return Err("NOT_FOUND", f"report {report_id} not found", f"rapport {report_id} introuvable")

        result = transition_report(header, "rejected")
        if isinstance(result, Err):
            return result

        self._connection.execute(
            "UPDATE production.production_reports SET status = 'rejected', rejection_reason = %s, updated_at = NOW() WHERE id = %s",
            (reason, report_id),
        )
        publish_event(
            self._connection,
            event_type="production.report.rejected",
            producer="production",
            tenant_id=tenant_id,
            correlation_id=correlation_id or str(ULID()),
            payload={
                "report_id": report_id,
                "of_id": header.of_id,
                "report_type": header.report_type,
                "reason": reason,
            },
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="production_report.rejected",
            entity_type="production_report",
            entity_id=report_id,
            payload={"reason": reason},
        )
        return Ok(self._load_header(tenant_id=tenant_id, report_id=report_id))  # type: ignore[arg-type]

    def revise_report(self, *, tenant_id: str, actor_id: str, report_id: str) -> Result[ProductionReport]:
        """Return a rejected report to the team as a fresh revision.

        The revision number moves on so the team's next submission is frozen
        alongside — not on top of — the one that was rejected.
        """
        header = self._load_header(tenant_id=tenant_id, report_id=report_id, for_update=True)
        if header is None:
            return Err("NOT_FOUND", f"report {report_id} not found", f"rapport {report_id} introuvable")

        result = transition_report(header, "draft")
        if isinstance(result, Err):
            return result

        new_revision = header.revision + 1
        self._connection.execute(
            """
            UPDATE production.production_reports
            SET status = 'draft', revision = %s, submitted_at = NULL, rejection_reason = NULL, updated_at = NOW()
            WHERE id = %s
            """,
            (new_revision, report_id),
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="production_report.revised",
            entity_type="production_report",
            entity_id=report_id,
            payload={"revision": new_revision},
        )
        return Ok(self._load_header(tenant_id=tenant_id, report_id=report_id))  # type: ignore[arg-type]

    # ---- internals -------------------------------------------------------

    def _duplicate_report_exists(
        self, *, tenant_id: str, of_id: str, report_type: str, report_date: datetime.date, shift: str | None
    ) -> bool:
        """A shift reports once.

        `production_reports_one_per_shift` enforces this in the database; checking
        here first is what turns it into a readable refusal instead of a unique
        violation surfacing as a 500. Same defence-in-depth shape as the
        one-active-recipe-per-product rule.
        """
        row = self._connection.execute(
            """
            SELECT 1 FROM production.production_reports
            WHERE tenant_id = %s AND of_id = %s AND report_type = %s AND report_date = %s
              AND shift IS NOT DISTINCT FROM %s
            """,
            (tenant_id, of_id, report_type, report_date, shift),
        ).fetchone()
        return row is not None

    def _record_regrind_scrap(
        self, *, tenant_id: str, actor_id: str, header: ProductionReport, quantity_override: float | None = None
    ) -> Result[str | None]:
        """Turn a validated report's rebroyat figure into a scrap record.

        scrap_records stops being something anyone types in for a shift and
        becomes a derived ledger: this is what keeps regrind_batch_inputs supplied
        once the daily report owns the waste figures. Phase 5 additionally opens
        the regrind OF from here.

        `quantity_override` is for `_reconcile_closed_regrind_batch`: it records
        just the delta above an already-closed batch, not the report's full
        (not-yet-persisted-at-this-point) rebroyat figure.
        """
        if quantity_override is None:
            detail = self._load_daily_detail(tenant_id=tenant_id, report_id=header.id)
            if detail is None or detail.regrind_quantity <= 0:
                return Ok(None)
            quantity = detail.regrind_quantity
        else:
            if quantity_override <= 0:
                return Ok(None)
            quantity = quantity_override

        order_row = self._connection.execute(
            "SELECT 1 FROM production.work_orders WHERE id = %s AND tenant_id = %s",
            (header.of_id, tenant_id),
        ).fetchone()
        if order_row is None:
            return Err("NOT_FOUND", f"work order {header.of_id} not found", f"OF {header.of_id} introuvable")

        # Imported here rather than at module scope: regrind_service imports the
        # work order service, and a top-level import would close the cycle.
        from modules.production.api.regrind_service import RegrindDefaultsService, ScrapService

        # Always the tenant's one rebroyat product -- never `detail.regrind_product_id`
        # (a free pick the report author made, typically the raw semolina actually
        # in use that shift) and never the OF's finished product (a wrapped 500g
        # packet is not what goes back through the mill). Every regrind batch
        # resolves to this same single product regardless of what fed it (see
        # RegrindService.create_regrind_batch), so recording the scrap against
        # anything else only invited a mismatched unit -- raw semolina is bought
        # by the tonne, rebroyat is weighed in kg, and that exact mismatch is
        # what caused the 1000x scale bug scripts/fix_regrind_batch_scale*.py
        # corrected. `detail.regrind_product_id` is kept only as an informational
        # field on the report itself (see of_consolidation_service.py).
        scrap_product_id = RegrindDefaultsService(self._connection).resolve_output_product(
            tenant_id=tenant_id, input_product_id=None
        )
        if scrap_product_id is None:
            return Err(
                "REGRIND_DEFAULT_MISSING",
                "no regrind output product is configured — set one in Production Settings before regrinding",
                "aucun produit de sortie de rebroyat n'est configuré — définissez-en un dans les paramètres de"
                " production avant de rebroyer",
            )

        scrap = ScrapService(self._connection).record_scrap(
            tenant_id=tenant_id,
            actor_id=actor_id,
            work_order_id=header.of_id,
            work_center_id=header.work_center_id,
            scrap_type="daily_report",
            product_id=scrap_product_id,
            quantity=quantity,
            source_note=f"daily report {header.id} revision {header.revision}",
        )
        if isinstance(scrap, Err):
            return scrap
        return Ok(scrap.value.id)

    def _insert_daily_detail(self, *, tenant_id: str, report_id: str, detail: DailyReportDetail) -> None:
        values = self._daily_values(detail)
        # Built from the value tuple rather than typed out: the count drifting
        # from the column list is the classic way a column silently stops
        # being written.
        placeholders = ", ".join(["%s"] * (2 + len(values)))
        self._connection.execute(
            f"""
            INSERT INTO production.daily_reports (report_id, tenant_id, {_DAILY_COLUMNS})
            VALUES ({placeholders})
            """,
            (report_id, tenant_id, *values),
        )
        replace_waste_lines(
            self._connection, tenant_id=tenant_id, report_id=report_id, lines=detail.waste_lines
        )
        replace_semolina_lines(
            self._connection, tenant_id=tenant_id, report_id=report_id, lines=detail.semolina_lines
        )
        replace_downtime_lines(
            self._connection, tenant_id=tenant_id, report_id=report_id, lines=detail.downtime_lines
        )

    def _update_daily_detail(self, *, tenant_id: str, report_id: str, detail: DailyReportDetail) -> None:
        assignments = ", ".join(f"{column.strip()} = %s" for column in _DAILY_COLUMNS.split(","))
        self._connection.execute(
            f"UPDATE production.daily_reports SET {assignments} WHERE report_id = %s AND tenant_id = %s",
            (*self._daily_values(detail), report_id, tenant_id),
        )
        replace_waste_lines(
            self._connection, tenant_id=tenant_id, report_id=report_id, lines=detail.waste_lines
        )
        replace_semolina_lines(
            self._connection, tenant_id=tenant_id, report_id=report_id, lines=detail.semolina_lines
        )
        replace_downtime_lines(
            self._connection, tenant_id=tenant_id, report_id=report_id, lines=detail.downtime_lines
        )

    @staticmethod
    def _daily_values(detail: DailyReportDetail) -> tuple:
        return (
            detail.dough_quantity,
            detail.finished_product_quantity,
            detail.regrind_quantity,
            detail.water_quantity,
            detail.fuel_quantity,
            detail.gasoil_quantity,
            detail.electricity_quantity,
            detail.start_time,
            detail.end_time,
            detail.production_minutes,
            detail.raw_material_location_id,
            detail.regrind_input_quantity,
            detail.regrind_input_product_id,
            detail.regrind_product_id,
            detail.mold_id,
            detail.water_percentage,
            detail.semolina_flow_rate,
            detail.fuel_supplier_id,
            detail.gasoil_supplier_id,
            detail.gasoil_flow_rate,
            detail.generator_hours,
        )

    def _write_revision(
        self,
        *,
        tenant_id: str,
        report_id: str,
        revision: int,
        detail: DailyReportDetail,
        reason: str | None,
        actor_id: str,
    ) -> None:
        self._connection.execute(
            """
            INSERT INTO production.report_revisions (id, tenant_id, report_id, revision, detail, reason, actor_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (str(ULID()), tenant_id, report_id, revision, Jsonb(_detail_to_json(detail)), reason, actor_id),
        )

    def _touch(self, report_id: str) -> None:
        self._connection.execute(
            "UPDATE production.production_reports SET updated_at = NOW() WHERE id = %s", (report_id,)
        )
