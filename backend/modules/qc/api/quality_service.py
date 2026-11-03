from __future__ import annotations

import datetime

import psycopg
from ulid import ULID

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from core.events.outbox import publish_event
from modules.qc.domain.parameters import validate_parameter_entry
from modules.qc.domain.quality import (
    DEFAULT_FOLLOW_UP_WINDOW_DAYS,
    ConformityLine,
    FollowUp,
    QualityReport,
    QualityReportDetail,
    follow_up_window_end,
    is_conforming,
    transition_follow_up,
    transition_quality_report,
    validate_conformity_line,
    validate_window_days,
)

_REPORT_COLUMNS = """
    id, shift_report_id, report_date, status, revision, team, shift, created_by,
    submitted_at, validated_by, validated_at, rejection_reason
"""

_DETAIL_COLUMNS = "comments, corrective_action"

_LINE_COLUMNS = """
    id, report_id, shift_packing_row_id, of_id, product_id,
    conforming_cartons, non_conforming_cartons, defect_details
"""

_FOLLOW_UP_COLUMNS = """
    id, quality_report_id, of_id, conformity_line_id, window_ends_on, observed_on, status, result, observation, actor_id
"""

# For INSERTs that supply the id separately. A manually recorded observation
# carries the conformity line it is about when the caller names one, NULL
# otherwise (a report-wide observation).
_FOLLOW_UP_INSERT_COLUMNS = """
    quality_report_id, of_id, conformity_line_id, window_ends_on, observed_on, status, result, observation, actor_id
"""


def _row_to_report(row: tuple) -> QualityReport:
    return QualityReport(
        id=row[0], shift_report_id=row[1], report_date=row[2], status=row[3], revision=row[4],
        team=row[5], shift=row[6], created_by=row[7], submitted_at=row[8],
        validated_by=row[9], validated_at=row[10], rejection_reason=row[11],
    )


def _row_to_detail(row: tuple) -> QualityReportDetail:
    return QualityReportDetail(comments=row[0], corrective_action=row[1])


def _detail_values(detail: QualityReportDetail) -> tuple:
    return (detail.comments, detail.corrective_action)


def _row_to_line(row: tuple) -> ConformityLine:
    return ConformityLine(
        id=row[0], report_id=row[1], shift_packing_row_id=row[2], of_id=row[3], product_id=row[4],
        conforming_cartons=float(row[5]), non_conforming_cartons=float(row[6]), defect_details=row[7],
    )


def _row_to_follow_up(row: tuple) -> FollowUp:
    return FollowUp(
        id=row[0],
        quality_report_id=row[1],
        of_id=row[2],
        conformity_line_id=row[3],
        window_ends_on=row[4],
        observed_on=row[5],
        status=row[6],
        result=row[7],
        observation=row[8],
        actor_id=row[9],
    )


class FollowUpPolicyService:
    """How long the follow-up window runs, per product.

    A tenant-wide default with an optional per-product override — shelf-life
    behaviour differs between pasta shapes, so 40 days is a default rather than a
    constant baked into the code.
    """

    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def resolve_window_days(self, *, tenant_id: str, product_id: str | None) -> int:
        """Per-product override, else the tenant default, else 40."""
        if product_id is not None:
            row = self._connection.execute(
                "SELECT window_days FROM qc.follow_up_policies WHERE tenant_id = %s AND product_id = %s",
                (tenant_id, product_id),
            ).fetchone()
            if row is not None:
                return int(row[0])

        row = self._connection.execute(
            "SELECT window_days FROM qc.follow_up_policies WHERE tenant_id = %s AND product_id IS NULL",
            (tenant_id,),
        ).fetchone()
        return int(row[0]) if row is not None else DEFAULT_FOLLOW_UP_WINDOW_DAYS

    def set_policy(
        self, *, tenant_id: str, actor_id: str, window_days: int, product_id: str | None = None
    ) -> Result[dict]:
        validation = validate_window_days(window_days)
        if isinstance(validation, Err):
            return validation

        self._connection.execute(
            """
            INSERT INTO qc.follow_up_policies (id, tenant_id, product_id, window_days)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (tenant_id, product_id) DO UPDATE
                SET window_days = EXCLUDED.window_days, updated_at = NOW()
            """,
            (str(ULID()), tenant_id, product_id, window_days),
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="follow_up_policy.updated",
            entity_type="follow_up_policy",
            entity_id=product_id or "tenant-default",
            payload={"product_id": product_id, "window_days": window_days},
        )
        return Ok({"product_id": product_id, "window_days": window_days})

    def list_policies(self, *, tenant_id: str) -> list[dict]:
        rows = self._connection.execute(
            "SELECT product_id, window_days FROM qc.follow_up_policies WHERE tenant_id = %s ORDER BY product_id NULLS FIRST",
            (tenant_id,),
        ).fetchall()
        return [{"product_id": product_id, "window_days": int(window_days)} for product_id, window_days in rows]


class QualityReportService:
    """The quality report and the follow-up windows it opens.

    One report per shift report, carrying one conformity line per product
    packed that shift. Deliberately its own aggregate rather than a detail
    table hanging off production's header: a module may not read another's
    tables, and quality outlives the OF it was raised against.
    """

    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    # ---- reads -----------------------------------------------------------

    def _load_report(self, *, tenant_id: str, report_id: str, for_update: bool = False) -> QualityReport | None:
        row = self._connection.execute(
            f"""
            SELECT {_REPORT_COLUMNS} FROM qc.quality_reports
            WHERE id = %s AND tenant_id = %s
            {'FOR UPDATE' if for_update else ''}
            """,
            (report_id, tenant_id),
        ).fetchone()
        return _row_to_report(row) if row is not None else None

    def _load_detail(self, *, tenant_id: str, report_id: str) -> QualityReportDetail | None:
        row = self._connection.execute(
            f"SELECT {_DETAIL_COLUMNS} FROM qc.quality_report_details WHERE report_id = %s AND tenant_id = %s",
            (report_id, tenant_id),
        ).fetchone()
        return _row_to_detail(row) if row is not None else None

    def _load_lines(self, *, tenant_id: str, report_id: str) -> list[ConformityLine]:
        rows = self._connection.execute(
            f"SELECT {_LINE_COLUMNS} FROM qc.quality_conformity_lines WHERE report_id = %s AND tenant_id = %s ORDER BY id",
            (report_id, tenant_id),
        ).fetchall()
        return [_row_to_line(row) for row in rows]

    def get_report(self, *, tenant_id: str, report_id: str) -> dict | None:
        report = self._load_report(tenant_id=tenant_id, report_id=report_id)
        if report is None:
            return None
        return {
            "report": report,
            "detail": self._load_detail(tenant_id=tenant_id, report_id=report_id),
            "lines": self._load_lines(tenant_id=tenant_id, report_id=report_id),
        }

    def get_conformity_summary(self, *, tenant_id: str, of_id: str) -> dict:
        """How an OF's quality came out, summed over its validated reports' conformity lines.

        Only validated reports count -- a draft or rejected quality report is a
        claim, not a verdict. A shift can pack several OFs, so only this OF's
        lines are summed, never the whole report.
        """
        row = self._connection.execute(
            """
            SELECT count(DISTINCT r.id), COALESCE(SUM(l.conforming_cartons), 0), COALESCE(SUM(l.non_conforming_cartons), 0)
            FROM qc.quality_conformity_lines l
            JOIN qc.quality_reports r ON r.id = l.report_id AND r.tenant_id = l.tenant_id
            WHERE l.tenant_id = %s AND l.of_id = %s AND r.status = 'validated'
            """,
            (tenant_id, of_id),
        ).fetchone()
        report_count, conforming, non_conforming = int(row[0]), float(row[1]), float(row[2])
        total = conforming + non_conforming
        return {
            "validated_report_count": report_count,
            "conforming_cartons": conforming,
            "non_conforming_cartons": non_conforming,
            "conformity_rate": (conforming / total) if total > 0 else None,
            "pending_nc_reports": self._reports_needing_nc(tenant_id=tenant_id, of_id=of_id),
        }

    def _reports_needing_nc(self, *, tenant_id: str, of_id: str) -> list[dict]:
        """Validated conformity lines that logged a defect but never got an NC raised for it.

        Keyed by conformity line: a report spans several products and OFs, so
        the report alone does not say which defect is unaddressed. report_id
        is carried alongside so a screen can still open the report. An NC only
        clears the line of its own OF -- one shift can pack the same product
        for two OFs, and a case raised for one says nothing about the other.
        """
        rows = self._connection.execute(
            """
            SELECT l.id, r.id, r.report_date, l.non_conforming_cartons
            FROM qc.quality_conformity_lines l
            JOIN qc.quality_reports r ON r.id = l.report_id AND r.tenant_id = l.tenant_id
            WHERE l.tenant_id = %s AND l.of_id = %s AND r.status = 'validated'
              AND l.non_conforming_cartons > 0
              AND NOT EXISTS (
                  SELECT 1 FROM qc.non_conformities n
                  WHERE n.tenant_id = l.tenant_id AND n.quality_report_id = l.report_id
                    AND n.product_id = l.product_id AND n.of_id = l.of_id
              )
            ORDER BY r.report_date DESC
            """,
            (tenant_id, of_id),
        ).fetchall()
        return [
            {
                "conformity_line_id": line_id,
                "report_id": report_id,
                "report_date": report_date.isoformat(),
                "non_conforming_cartons": float(qty),
            }
            for line_id, report_id, report_date, qty in rows
        ]

    def get_validated_conforming(self, *, tenant_id: str, day: datetime.date) -> dict[str, float]:
        """Conforming pieces per product that validated QC reports of `day` cleared (see
        `get_validated_conforming_by_row`, summed per product)."""
        totals: dict[str, float] = {}
        for product_id, pieces in self.get_validated_conforming_by_row(tenant_id=tenant_id, day=day).values():
            totals[product_id] = totals.get(product_id, 0.0) + pieces
        return totals

    def get_validated_conforming_by_row(self, *, tenant_id: str, day: datetime.date) -> dict[str, tuple[str, float]]:
        """Per packing row a validated QC report of `day` judged: its product and the conforming
        pieces the verdict cleared. A row listed with 0 was judged and cleared nothing; a row not
        listed has no validated verdict yet.

        Only a validated report counts -- a draft, submitted or rejected one is a claim, not a
        verdict. `report_date` is the QC report's own, copied from its shift at creation, so it
        is the shift's day without reading production's tables. A line's conforming cartons are
        turned into pieces with the packets-per-carton frozen on its packing row (asked of
        production, never read here) and the same `finished_quantity_from_count` the packed
        figure uses, so the two stay comparable. No carton tier (a sac) passes the count through.

        A line whose packing row no longer exists, or now names a different product (the shift was
        reversed or corrected after QC looked at it), clears nothing: the verdict was about goods
        that are no longer on record as packed.
        """
        from modules.production.api.report_product import packing_row_packets_per_carton
        from modules.production.domain.packaging_estimate import finished_quantity_from_count

        rows = self._connection.execute(
            """
            SELECT l.product_id, l.shift_packing_row_id, l.conforming_cartons
            FROM qc.quality_conformity_lines l
            JOIN qc.quality_reports r ON r.id = l.report_id AND r.tenant_id = l.tenant_id
            WHERE l.tenant_id = %s AND r.status = 'validated' AND r.report_date = %s
            """,
            (tenant_id, day),
        ).fetchall()
        current_by_row = packing_row_packets_per_carton(
            self._connection, tenant_id=tenant_id, shift_packing_row_ids=[row[1] for row in rows]
        )
        by_row: dict[str, tuple[str, float]] = {}
        for product_id, row_id, conforming_cartons in rows:
            current = current_by_row.get(row_id)
            if current is None:
                continue
            packets_per_carton, current_product_id = current
            if current_product_id != product_id:
                continue
            cartons = float(conforming_cartons)
            pieces = finished_quantity_from_count(
                packets_per_carton=packets_per_carton, carton_quantity=cartons, packets_counted=cartons,
            )
            by_row[row_id] = (product_id, by_row.get(row_id, (product_id, 0.0))[1] + pieces)
        return by_row

    GRAINS = ("day", "week", "month", "year")

    def team_conformity(
        self, *, tenant_id: str, grain: str, date_from: str | None = None, date_to: str | None = None
    ) -> list[dict]:
        """Validated conformity per team per calendar bucket, summed over conformity lines."""
        if grain not in self.GRAINS:
            raise ValueError(f"grain must be one of {self.GRAINS}")
        clauses = ["r.tenant_id = %s", "r.status = 'validated'"]
        params: list[object] = [grain, tenant_id]
        if date_from is not None:
            clauses.append("r.report_date >= %s")
            params.append(date_from)
        if date_to is not None:
            clauses.append("r.report_date <= %s")
            params.append(date_to)
        rows = self._connection.execute(
            f"""
            SELECT r.team, date_trunc(%s, r.report_date)::date AS period, count(DISTINCT r.id) AS report_count,
                   COALESCE(SUM(l.conforming_cartons), 0), COALESCE(SUM(l.non_conforming_cartons), 0)
            FROM qc.quality_reports r
            JOIN qc.quality_conformity_lines l ON l.report_id = r.id AND l.tenant_id = r.tenant_id
            WHERE {' AND '.join(clauses)}
            GROUP BY r.team, period
            ORDER BY period, r.team
            """,
            params,
        ).fetchall()
        return [
            {
                "team": team, "period": period.isoformat(), "report_count": int(count),
                "conforming_cartons": float(c), "non_conforming_cartons": float(nc),
            }
            for team, period, count, c, nc in rows
        ]

    def inspection_ledger(
        self, *, tenant_id: str, date_from: str | None = None, date_to: str | None = None
    ) -> list[dict]:
        """Every conformity line of every quality report in the window, one row each.

        The dashboards need conformity sliced by product, line, team, shift,
        defect and day at once, and `team_conformity` only knows teams. Rather
        than one endpoint per slice, this hands back the line grain (a report
        has one line per product packed that shift) and lets the reader group
        it -- a month of shifts is a few hundred rows, well under what a screen
        can hold. Every status is included so the reader can also tell what is
        still waiting on QC; a caller wanting the official figure keeps
        `status == "validated"`, exactly the rule `team_conformity` applies.
        A report whose shift packed nothing has no line and so no row here; it
        still counts in `list_reports`.
        """
        clauses = ["r.tenant_id = %s"]
        params: list[object] = [tenant_id]
        if date_from is not None:
            clauses.append("r.report_date >= %s")
            params.append(date_from)
        if date_to is not None:
            clauses.append("r.report_date <= %s")
            params.append(date_to)
        rows = self._connection.execute(
            f"""
            SELECT
                l.id, r.id, r.shift_report_id, r.report_date, r.shift, r.team, r.status, r.revision,
                r.submitted_at, r.validated_at, l.of_id, l.product_id,
                l.conforming_cartons, l.non_conforming_cartons, l.defect_details, d.corrective_action,
                (SELECT count(*) FROM qc.non_conformities n
                 WHERE n.tenant_id = r.tenant_id AND n.quality_report_id = r.id
                   AND n.of_id = l.of_id AND n.product_id = l.product_id)
            FROM qc.quality_reports r
            JOIN qc.quality_conformity_lines l ON l.report_id = r.id AND l.tenant_id = r.tenant_id
            LEFT JOIN qc.quality_report_details d ON d.report_id = r.id AND d.tenant_id = r.tenant_id
            WHERE {' AND '.join(clauses)}
            ORDER BY r.report_date, r.shift, r.team, r.id, l.id
            """,
            params,
        ).fetchall()
        return [
            {
                "line_id": row[0],
                "report_id": row[1],
                "shift_report_id": row[2],
                "report_date": row[3].isoformat(),
                "shift": row[4],
                "team": row[5],
                "status": row[6],
                "revision": int(row[7]),
                "submitted_at": row[8].isoformat() if row[8] is not None else None,
                "validated_at": row[9].isoformat() if row[9] is not None else None,
                "of_id": row[10],
                "product_id": row[11],
                "conforming_cartons": float(row[12] or 0),
                "non_conforming_cartons": float(row[13] or 0),
                "defect_details": row[14],
                "corrective_action": row[15],
                "non_conformity_count": int(row[16]),
            }
            for row in rows
        ]

    def list_reports(self, *, tenant_id: str, status: str | None = None) -> list[QualityReport]:
        clauses = ["tenant_id = %s"]
        params: list[object] = [tenant_id]
        if status is not None:
            clauses.append("status = %s")
            params.append(status)
        rows = self._connection.execute(
            f"SELECT {_REPORT_COLUMNS} FROM qc.quality_reports WHERE {' AND '.join(clauses)} "
            f"ORDER BY report_date DESC, created_at DESC",
            params,
        ).fetchall()
        return [_row_to_report(row) for row in rows]

    # ---- writes ----------------------------------------------------------

    def _resolve_shift(self, *, tenant_id: str, shift_report_id: str) -> Result[dict]:
        """Resolve a shift report into what a quality report needs from it.

        Production is the authority on work_center/date/team/shift and on the
        packing rows a QC report inspects. qc never reads production's tables
        -- it asks production's own service. get_shift's packing section
        payload already carries each row's stable id, of_id and product_id.
        """
        from modules.production.api.shift_report_service import ShiftReportService

        shifts = ShiftReportService(self._connection)
        found = shifts.get_shift(tenant_id=tenant_id, shift_report_id=shift_report_id)
        if isinstance(found, Err):
            return found
        header = found.value

        packing_section = next((s for s in header["sections"] if s["key"] == "packing"), None)
        payload_rows = ((packing_section or {}).get("payload") or {}).get("rows") or []
        packing_rows = [
            {"id": row["id"], "of_id": row["of_id"], "product_id": row["product_id"]}
            for row in payload_rows
            if row.get("product_id") is not None
        ]

        return Ok(
            {
                "work_center_id": header["work_center_id"],
                "report_date": datetime.date.fromisoformat(header["report_date"]),
                "shift": header["shift"],
                "team": header["team"],
                "status": header["status"],
                "packing_rows": packing_rows,
            }
        )

    def _resolve_validated_shift(self, *, tenant_id: str, shift_report_id: str) -> Result[dict]:
        """_resolve_shift, refused unless production has validated the shift.

        An open or submitted shift can still change what it packed, so a QC verdict on it
        would be about goods that are not on record yet.
        """
        resolved = self._resolve_shift(tenant_id=tenant_id, shift_report_id=shift_report_id)
        if isinstance(resolved, Err):
            return resolved
        if resolved.value["status"] != "validated":
            return Err(
                "SHIFT_NOT_VALIDATED",
                "a quality report can only inspect a validated shift",
                "un rapport qualité ne peut inspecter qu'un shift validé",
            )
        return resolved

    def list_inspectable_shift_reports(self, *, tenant_id: str) -> list[dict]:
        """Validated shift reports with no QC report yet."""
        already_linked = {
            row[0]
            for row in self._connection.execute(
                "SELECT shift_report_id FROM qc.quality_reports WHERE tenant_id = %s", (tenant_id,)
            ).fetchall()
        }
        from modules.production.api.shift_report_service import ShiftReportService

        shifts = ShiftReportService(self._connection).list_shifts(tenant_id=tenant_id, status="validated")
        return [
            {
                "shift_report_id": s["id"], "work_center_id": s["work_center_id"], "report_date": s["report_date"],
                "shift": s["shift"], "team": s["team"],
            }
            for s in shifts
            if s["id"] not in already_linked
        ]

    def create_report(self, *, tenant_id: str, actor_id: str, shift_report_id: str) -> Result[dict]:
        if not shift_report_id.strip():
            return Err(
                "MISSING_SHIFT_REPORT", "a quality report must inspect a shift report", "un rapport qualité doit inspecter un shift"
            )

        resolved = self._resolve_validated_shift(tenant_id=tenant_id, shift_report_id=shift_report_id)
        if isinstance(resolved, Err):
            return resolved
        link = resolved.value

        duplicate = self._connection.execute(
            "SELECT 1 FROM qc.quality_reports WHERE tenant_id = %s AND shift_report_id = %s",
            (tenant_id, shift_report_id),
        ).fetchone()
        if duplicate is not None:
            return Err(
                "DUPLICATE_REPORT",
                "a quality report already exists for this shift report",
                "un rapport qualité existe déjà pour ce shift",
            )

        report_id = str(ULID())
        self._connection.execute(
            """
            INSERT INTO qc.quality_reports (id, tenant_id, shift_report_id, report_date, status, revision, team, shift, created_by)
            VALUES (%s, %s, %s, %s, 'draft', 1, %s, %s, %s)
            """,
            (report_id, tenant_id, shift_report_id, link["report_date"], link["team"], link["shift"], actor_id),
        )
        self._connection.execute(
            f"INSERT INTO qc.quality_report_details (report_id, tenant_id, {_DETAIL_COLUMNS}) VALUES (%s, %s, %s, %s)",
            (report_id, tenant_id, None, None),
        )
        for row in link["packing_rows"]:
            self._connection.execute(
                """
                INSERT INTO qc.quality_conformity_lines
                    (id, tenant_id, report_id, shift_packing_row_id, of_id, product_id)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (str(ULID()), tenant_id, report_id, row["id"], row["of_id"], row["product_id"]),
            )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="quality_report.created",
            entity_type="quality_report",
            entity_id=report_id,
            payload={
                "shift_report_id": shift_report_id,
                "report_date": link["report_date"].isoformat(),
                "line_count": len(link["packing_rows"]),
            },
        )
        return Ok(self._read(tenant_id=tenant_id, report_id=report_id))

    def update_draft(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        report_id: str,
        lines: list[dict],
        detail: QualityReportDetail | None = None,
    ) -> Result[dict]:
        report = self._load_report(tenant_id=tenant_id, report_id=report_id, for_update=True)
        if report is None:
            return Err("NOT_FOUND", f"quality report {report_id} not found", f"rapport qualité {report_id} introuvable")
        if report.status != "draft":
            return Err(
                "NOT_EDITABLE",
                f"a {report.status} quality report cannot be edited as a draft",
                f"un rapport qualité {report.status} ne peut pas être modifié comme un brouillon",
            )

        applied = self._apply_line_edits(tenant_id=tenant_id, report_id=report_id, edits=lines)
        if isinstance(applied, Err):
            return applied

        if detail is not None:
            self._write_detail(tenant_id=tenant_id, report_id=report_id, detail=detail)
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="quality_report.draft_updated",
            entity_type="quality_report",
            entity_id=report_id,
            payload={"line_count": len(lines)},
        )
        return Ok(self._read(tenant_id=tenant_id, report_id=report_id))

    def _apply_line_edits(self, *, tenant_id: str, report_id: str, edits: list[dict]) -> Result[None]:
        for edit in edits:
            row_id = edit["shift_packing_row_id"]
            existing = self._connection.execute(
                "SELECT id, of_id, product_id FROM qc.quality_conformity_lines "
                "WHERE tenant_id = %s AND report_id = %s AND shift_packing_row_id = %s",
                (tenant_id, report_id, row_id),
            ).fetchone()
            if existing is None:
                return Err(
                    "LINE_NOT_FOUND",
                    f"no conformity line for packing row {row_id} on this report",
                    f"aucune ligne de conformité pour la ligne de conditionnement {row_id} sur ce rapport",
                )
            line = ConformityLine(
                id=existing[0],
                report_id=report_id,
                shift_packing_row_id=row_id,
                of_id=existing[1],
                product_id=existing[2],
                conforming_cartons=float(edit.get("conforming_cartons", 0)),
                non_conforming_cartons=float(edit.get("non_conforming_cartons", 0)),
                defect_details=edit.get("defect_details"),
            )
            validation = validate_conformity_line(line)
            if isinstance(validation, Err):
                return validation
            self._connection.execute(
                """
                UPDATE qc.quality_conformity_lines
                SET conforming_cartons = %s, non_conforming_cartons = %s, defect_details = %s, updated_at = NOW()
                WHERE id = %s
                """,
                (line.conforming_cartons, line.non_conforming_cartons, line.defect_details, line.id),
            )
        return Ok(None)

    def admin_update_report(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        report_id: str,
        lines: list[dict] | None = None,
        shift_report_id: str | None = None,
        detail: QualityReportDetail | None = None,
        reason: str | None = None,
    ) -> Result[dict]:
        """Edit-in-place, gated by qc.admin_quality_reports.

        A separate, more trusted right than progressing a report through its normal
        workflow -- and allowed regardless of status, because the permission is what
        limits the blast radius, not a status check.

        Re-linking to a different shift_report_id is only allowed on a draft with no
        non-conformity raised against any of its lines, and only onto a validated
        shift. It re-derives report_date, shift and team together from the new shift
        and replaces the conformity lines wholesale with one per packing row of the
        new shift -- the old lines described goods of the old shift, and keeping them
        would block a fresh QC report on it (one line per packing row). A draft has
        opened no follow-up windows yet, so nothing references the removed lines.
        """
        report = self._load_report(tenant_id=tenant_id, report_id=report_id, for_update=True)
        if report is None:
            return Err("NOT_FOUND", f"quality report {report_id} not found", f"rapport qualité {report_id} introuvable")

        if shift_report_id is not None and shift_report_id != report.shift_report_id:
            if report.status != "draft":
                return Err(
                    "NOT_EDITABLE",
                    f"a {report.status} quality report cannot be moved to another shift",
                    f"un rapport qualité {report.status} ne peut pas être déplacé vers un autre shift",
                )
            attached = self._connection.execute(
                """
                SELECT 1 FROM qc.quality_conformity_lines l
                JOIN qc.non_conformities n
                  ON n.tenant_id = l.tenant_id AND n.quality_report_id = l.report_id
                 AND n.of_id = l.of_id AND n.product_id = l.product_id
                WHERE l.tenant_id = %s AND l.report_id = %s
                LIMIT 1
                """,
                (tenant_id, report_id),
            ).fetchone()
            if attached is not None:
                return Err(
                    "NON_CONFORMITY_ATTACHED",
                    "a non-conformity was raised from this report; it cannot be moved to another shift",
                    "une non-conformité a été ouverte depuis ce rapport ; il ne peut pas être déplacé vers un autre shift",
                )
            resolved = self._resolve_validated_shift(tenant_id=tenant_id, shift_report_id=shift_report_id)
            if isinstance(resolved, Err):
                return resolved
            duplicate = self._connection.execute(
                "SELECT 1 FROM qc.quality_reports WHERE tenant_id = %s AND shift_report_id = %s AND id != %s",
                (tenant_id, shift_report_id, report_id),
            ).fetchone()
            if duplicate is not None:
                return Err(
                    "DUPLICATE_REPORT",
                    "a quality report already exists for this shift report",
                    "un rapport qualité existe déjà pour ce shift",
                )
            link = resolved.value
            self._connection.execute(
                "UPDATE qc.quality_reports SET shift_report_id = %s, team = %s, shift = %s, report_date = %s, "
                "updated_at = NOW() WHERE id = %s",
                (shift_report_id, link["team"], link["shift"], link["report_date"], report_id),
            )
            self._connection.execute(
                "DELETE FROM qc.quality_conformity_lines WHERE tenant_id = %s AND report_id = %s",
                (tenant_id, report_id),
            )
            for row in link["packing_rows"]:
                self._connection.execute(
                    """
                    INSERT INTO qc.quality_conformity_lines
                        (id, tenant_id, report_id, shift_packing_row_id, of_id, product_id)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (str(ULID()), tenant_id, report_id, row["id"], row["of_id"], row["product_id"]),
                )

        if lines is not None:
            applied = self._apply_line_edits(tenant_id=tenant_id, report_id=report_id, edits=lines)
            if isinstance(applied, Err):
                return applied

        if detail is not None:
            self._write_detail(tenant_id=tenant_id, report_id=report_id, detail=detail)

        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="quality_report.updated",
            entity_type="quality_report",
            entity_id=report_id,
            payload={"shift_report_id": shift_report_id, "reason": reason},
        )
        return Ok(self._read(tenant_id=tenant_id, report_id=report_id))

    def submit_report(self, *, tenant_id: str, actor_id: str, report_id: str) -> Result[QualityReport]:
        report = self._load_report(tenant_id=tenant_id, report_id=report_id, for_update=True)
        if report is None:
            return Err("NOT_FOUND", f"quality report {report_id} not found", f"rapport qualité {report_id} introuvable")

        result = transition_quality_report(report, "submitted")
        if isinstance(result, Err):
            return result

        for line in self._load_lines(tenant_id=tenant_id, report_id=report_id):
            validation = validate_conformity_line(line)
            if isinstance(validation, Err):
                return validation

        self._connection.execute(
            "UPDATE qc.quality_reports SET status = 'submitted', submitted_at = NOW(), updated_at = NOW() WHERE id = %s",
            (report_id,),
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="quality_report.submitted",
            entity_type="quality_report",
            entity_id=report_id,
            payload={"revision": report.revision},
        )
        return Ok(self._load_report(tenant_id=tenant_id, report_id=report_id))  # type: ignore[arg-type]

    def validate_report(self, *, tenant_id: str, actor_id: str, report_id: str, correlation_id: str) -> Result[dict]:
        """Make a quality report official and open one follow-up window per product line.

        Posts no stock -- quality only moves inventory through a non-conformity.
        Each line already carries its own product_id, so the per-product window
        policy applies without qc reading production's tables.
        """
        report = self._load_report(tenant_id=tenant_id, report_id=report_id, for_update=True)
        if report is None:
            return Err("NOT_FOUND", f"quality report {report_id} not found", f"rapport qualité {report_id} introuvable")

        result = transition_quality_report(report, "validated")
        if isinstance(result, Err):
            return result

        lines = self._load_lines(tenant_id=tenant_id, report_id=report_id)

        self._connection.execute(
            """
            UPDATE qc.quality_reports
            SET status = 'validated', validated_by = %s, validated_at = NOW(), rejection_reason = NULL, updated_at = NOW()
            WHERE id = %s
            """,
            (actor_id, report_id),
        )

        policies = FollowUpPolicyService(self._connection)
        opened_follow_ups = []
        for line in lines:
            window_days = policies.resolve_window_days(tenant_id=tenant_id, product_id=line.product_id)
            window_ends_on = follow_up_window_end(report.report_date, window_days)
            follow_up_id = str(ULID())
            self._connection.execute(
                """
                INSERT INTO qc.quality_follow_ups
                    (id, tenant_id, quality_report_id, of_id, conformity_line_id, window_ends_on, observed_on,
                     status, observation, actor_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, 'open', %s, %s)
                """,
                (
                    follow_up_id, tenant_id, report_id, line.of_id, line.id, window_ends_on, report.report_date,
                    "opened on validation", actor_id,
                ),
            )
            opened_follow_ups.append({"follow_up_id": follow_up_id, "of_id": line.of_id, "window_ends_on": window_ends_on})

        conforming = is_conforming(lines)
        publish_event(
            self._connection,
            event_type="qc.quality_report.validated",
            producer="qc",
            tenant_id=tenant_id,
            correlation_id=correlation_id,
            payload={"quality_report_id": report_id, "is_conforming": conforming},
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="quality_report.validated",
            entity_type="quality_report",
            entity_id=report_id,
            payload={"is_conforming": conforming, "follow_ups": len(opened_follow_ups)},
        )
        return Ok(
            {
                "report": self._load_report(tenant_id=tenant_id, report_id=report_id),
                "lines": lines,
                "follow_ups": opened_follow_ups,
            }
        )

    def reject_report(
        self, *, tenant_id: str, actor_id: str, report_id: str, reason: str
    ) -> Result[QualityReport]:
        if not reason.strip():
            return Err(
                "MISSING_REASON", "a rejection must say what is wrong with the report", "un rejet doit indiquer ce qui ne va pas avec le rapport"
            )

        report = self._load_report(tenant_id=tenant_id, report_id=report_id, for_update=True)
        if report is None:
            return Err("NOT_FOUND", f"quality report {report_id} not found", f"rapport qualité {report_id} introuvable")

        result = transition_quality_report(report, "rejected")
        if isinstance(result, Err):
            return result

        # Clean up any non-conformities linked to this report.
        # They represent a rejected validation attempt and must not stay in quarantine.
        # Only clean up if they are still in quarantined/raised status (not yet dispositioned).
        # The OF comes from the NC itself -- a shift-based report spans several OFs.
        non_conformities = self._connection.execute(
            """
            SELECT id, product_id, quantity, quarantine_location_id, source_location_id, of_id
            FROM qc.non_conformities
            WHERE tenant_id = %s AND quality_report_id = %s AND status IN ('raised', 'quarantined')
            """,
            (tenant_id, report_id),
        ).fetchall()

        for nc_id, product_id, quantity, quarantine_location_id, source_location_id, nc_of_id in non_conformities:
            # The hold was never warranted -- the report describing it was rejected --
            # so the product goes back to where it was pulled from, not just off the books.
            from modules.warehouse.api.service import StockService
            released = StockService(self._connection).restore_from_quarantine(
                tenant_id=tenant_id,
                product_id=product_id,
                quarantine_location_id=quarantine_location_id,
                destination_location_id=source_location_id,
                quantity=float(quantity),
                correlation_id=f"quality_report_rejection:{report_id}",
                reference=f"non_conformity:{nc_id}:rejection_cleanup",
                actor_id=actor_id,
                source_type="qc.non_conformity_rejection_cleanup",
                source_id=nc_id,
                of_id=nc_of_id,
            )
            if isinstance(released, Err):
                return released

            # Delete the non-conformity record
            self._connection.execute(
                "DELETE FROM qc.nc_dispositions WHERE tenant_id = %s AND non_conformity_id = %s",
                (tenant_id, nc_id),
            )
            self._connection.execute(
                "DELETE FROM qc.non_conformities WHERE tenant_id = %s AND id = %s",
                (tenant_id, nc_id),
            )
            record_audit(
                self._connection,
                tenant_id=tenant_id,
                actor_id=actor_id,
                action="non_conformity.deleted_by_report_rejection",
                entity_type="non_conformity",
                entity_id=nc_id,
                payload={"quality_report_id": report_id, "quantity": float(quantity)},
            )

        self._connection.execute(
            "UPDATE qc.quality_reports SET status = 'rejected', rejection_reason = %s, updated_at = NOW() WHERE id = %s",
            (reason, report_id),
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="quality_report.rejected",
            entity_type="quality_report",
            entity_id=report_id,
            payload={"reason": reason},
        )
        return Ok(self._load_report(tenant_id=tenant_id, report_id=report_id))  # type: ignore[arg-type]

    def revise_report(self, *, tenant_id: str, actor_id: str, report_id: str) -> Result[QualityReport]:
        report = self._load_report(tenant_id=tenant_id, report_id=report_id, for_update=True)
        if report is None:
            return Err("NOT_FOUND", f"quality report {report_id} not found", f"rapport qualité {report_id} introuvable")

        result = transition_quality_report(report, "draft")
        if isinstance(result, Err):
            return result

        self._connection.execute(
            """
            UPDATE qc.quality_reports
            SET status = 'draft', revision = %s, submitted_at = NULL, rejection_reason = NULL, updated_at = NOW()
            WHERE id = %s
            """,
            (report.revision + 1, report_id),
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="quality_report.revised",
            entity_type="quality_report",
            entity_id=report_id,
            payload={"revision": report.revision + 1},
        )
        return Ok(self._load_report(tenant_id=tenant_id, report_id=report_id))  # type: ignore[arg-type]

    def delete_report(self, *, tenant_id: str, actor_id: str, report_id: str, reason: str) -> Result[str]:
        """Remove a quality report, undoing what its validation opened.

        A quality report posts no stock, so there is nothing to reverse in the
        warehouse. What validation *does* create is a follow-up window per line,
        and those go with the report. A non-conformity raised from the report is
        a different matter -- it may already have moved stock into quarantine --
        so the deletion is refused while one is still attached.
        """
        if not reason.strip():
            return Err("MISSING_REASON", "deleting a report must say why", "supprimer un rapport doit indiquer pourquoi")

        report = self._load_report(tenant_id=tenant_id, report_id=report_id, for_update=True)
        if report is None:
            return Err("NOT_FOUND", f"quality report {report_id} not found", f"rapport qualité {report_id} introuvable")

        attached = self._connection.execute(
            "SELECT COUNT(*) FROM qc.non_conformities WHERE tenant_id = %s AND quality_report_id = %s",
            (tenant_id, report_id),
        ).fetchone()
        if attached and attached[0]:
            return Err(
                "NON_CONFORMITY_ATTACHED",
                "detach the non-conformities raised from this report before deleting it",
                "détachez les non-conformités ouvertes depuis ce rapport avant de le supprimer",
            )

        self._connection.execute(
            "DELETE FROM qc.quality_follow_ups WHERE tenant_id = %s AND quality_report_id = %s",
            (tenant_id, report_id),
        )
        self._connection.execute(
            "DELETE FROM qc.quality_conformity_lines WHERE tenant_id = %s AND report_id = %s",
            (tenant_id, report_id),
        )
        self._connection.execute(
            "DELETE FROM qc.quality_parameters WHERE tenant_id = %s AND report_id = %s",
            (tenant_id, report_id),
        )
        self._connection.execute(
            "DELETE FROM qc.quality_report_details WHERE tenant_id = %s AND report_id = %s",
            (tenant_id, report_id),
        )
        self._connection.execute(
            "DELETE FROM qc.quality_reports WHERE tenant_id = %s AND id = %s", (tenant_id, report_id)
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="quality_report.deleted",
            entity_type="quality_report",
            entity_id=report_id,
            payload={
                "reason": reason,
                "status_when_deleted": report.status,
                "shift_report_id": report.shift_report_id,
            },
        )
        return Ok(report_id)

    def _write_detail(self, *, tenant_id: str, report_id: str, detail: QualityReportDetail) -> None:
        assignments = ", ".join(f"{column.strip()} = %s" for column in _DETAIL_COLUMNS.split(","))
        self._connection.execute(
            f"UPDATE qc.quality_report_details SET {assignments} WHERE report_id = %s AND tenant_id = %s",
            (*_detail_values(detail), report_id, tenant_id),
        )
        self._connection.execute("UPDATE qc.quality_reports SET updated_at = NOW() WHERE id = %s", (report_id,))

    def _read(self, *, tenant_id: str, report_id: str) -> dict:
        return {
            "report": self._load_report(tenant_id=tenant_id, report_id=report_id),
            "detail": self._load_detail(tenant_id=tenant_id, report_id=report_id),
            "lines": self._load_lines(tenant_id=tenant_id, report_id=report_id),
        }

    # ---- Contrôle des paramètres ------------------------------------------

    def list_parameters(self, *, tenant_id: str, report_id: str) -> list[dict]:
        rows = self._connection.execute(
            "SELECT id, group_key, entry_label, fields FROM qc.quality_parameters "
            "WHERE tenant_id = %s AND report_id = %s ORDER BY group_key, created_at",
            (tenant_id, report_id),
        ).fetchall()
        return [{"id": r[0], "group_key": r[1], "entry_label": r[2], "fields": r[3]} for r in rows]

    def _parameters_editable(self, *, tenant_id: str, report_id: str, allow_non_draft: bool) -> Result[None]:
        """Parameter entries follow the report: editable on a draft, otherwise only by an admin
        correcting in place (the router passes allow_non_draft for qc.admin_quality_reports)."""
        report = self._load_report(tenant_id=tenant_id, report_id=report_id, for_update=True)
        if report is None:
            return Err("NOT_FOUND", f"quality report {report_id} not found", f"rapport qualité {report_id} introuvable")
        if report.status != "draft" and not allow_non_draft:
            return Err(
                "NOT_EDITABLE",
                f"the parameters of a {report.status} quality report cannot be edited",
                f"les paramètres d'un rapport qualité {report.status} ne peuvent pas être modifiés",
            )
        return Ok(None)

    def save_parameter_entry(
        self, *, tenant_id: str, actor_id: str, report_id: str, group_key: str,
        entry_label: str | None, fields: dict, allow_non_draft: bool = False,
    ) -> Result[dict]:
        import json

        editable = self._parameters_editable(tenant_id=tenant_id, report_id=report_id, allow_non_draft=allow_non_draft)
        if isinstance(editable, Err):
            return editable
        validation = validate_parameter_entry(group_key, fields)
        if isinstance(validation, Err):
            return validation

        entry_id = str(ULID())
        self._connection.execute(
            "INSERT INTO qc.quality_parameters (id, tenant_id, report_id, group_key, entry_label, fields) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (entry_id, tenant_id, report_id, group_key, entry_label, json.dumps(fields)),
        )
        record_audit(
            self._connection, tenant_id=tenant_id, actor_id=actor_id, action="quality_parameter.saved",
            entity_type="quality_report", entity_id=report_id, payload={"group_key": group_key, "entry_label": entry_label},
        )
        return Ok({"id": entry_id, "group_key": group_key, "entry_label": entry_label, "fields": fields})

    def delete_parameter_entry(
        self, *, tenant_id: str, actor_id: str, report_id: str, entry_id: str, allow_non_draft: bool = False,
    ) -> Result[None]:
        editable = self._parameters_editable(tenant_id=tenant_id, report_id=report_id, allow_non_draft=allow_non_draft)
        if isinstance(editable, Err):
            return editable
        deleted = self._connection.execute(
            "DELETE FROM qc.quality_parameters WHERE tenant_id = %s AND report_id = %s AND id = %s RETURNING id",
            (tenant_id, report_id, entry_id),
        ).fetchone()
        if deleted is None:
            return Err(
                "NOT_FOUND",
                f"parameter entry {entry_id} not found on report {report_id}",
                f"saisie de paramètre {entry_id} introuvable sur le rapport {report_id}",
            )
        record_audit(
            self._connection, tenant_id=tenant_id, actor_id=actor_id, action="quality_parameter.deleted",
            entity_type="quality_report", entity_id=report_id, payload={"entry_id": entry_id},
        )
        return Ok(None)


class FollowUpService:
    """Observations inside a validated report's follow-up window.

    Survives OF closure by design — the window outlives production, which is the
    whole reason quality is not keyed to an open work order.
    """

    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def list_follow_ups(
        self, *, tenant_id: str, quality_report_id: str | None = None, of_id: str | None = None, status: str | None = None
    ) -> list[FollowUp]:
        clauses = ["tenant_id = %s"]
        params: list[object] = [tenant_id]
        if quality_report_id is not None:
            clauses.append("quality_report_id = %s")
            params.append(quality_report_id)
        if of_id is not None:
            clauses.append("of_id = %s")
            params.append(of_id)
        if status is not None:
            clauses.append("status = %s")
            params.append(status)
        rows = self._connection.execute(
            f"""
            SELECT {_FOLLOW_UP_COLUMNS} FROM qc.quality_follow_ups
            WHERE {' AND '.join(clauses)}
            ORDER BY observed_on DESC, created_at DESC
            """,
            params,
        ).fetchall()
        return [_row_to_follow_up(row) for row in rows]

    def count_open_for_of(self, *, tenant_id: str, of_id: str) -> int:
        """Follow-ups still outstanding for an OF.

        Production asks this when checking whether an order is ready to close.
        Note that an open window does not *prevent* closure — the 40-day follow-up
        deliberately outlives production, and refusing to close until it expires
        would leave orders open for over a month.
        """
        return int(
            self._connection.execute(
                """
                SELECT count(*) FROM qc.quality_follow_ups
                WHERE tenant_id = %s AND of_id = %s AND status <> 'completed'
                """,
                (tenant_id, of_id),
            ).fetchone()[0]
        )

    def record_observation(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        quality_report_id: str,
        observed_on: datetime.date,
        observation: str | None = None,
        result: str | None = None,
        conformity_line_id: str | None = None,
    ) -> Result[FollowUp]:
        """Record an observation inside a report's follow-up window.

        Each conformity line has its own window (its own product's policy) and OF, so an
        observation naming a line takes both from that line's follow-up. Without one it
        falls back to the report's first window.
        """
        if conformity_line_id is not None:
            parent = self._connection.execute(
                """
                SELECT of_id, window_ends_on FROM qc.quality_follow_ups
                WHERE tenant_id = %s AND quality_report_id = %s AND conformity_line_id = %s
                ORDER BY created_at LIMIT 1
                """,
                (tenant_id, quality_report_id, conformity_line_id),
            ).fetchone()
            if parent is None:
                return Err(
                    "NOT_FOUND",
                    f"conformity line {conformity_line_id} has no follow-up window on report {quality_report_id}",
                    f"la ligne de conformité {conformity_line_id} n'a pas de fenêtre de suivi sur le rapport {quality_report_id}",
                )
        else:
            parent = self._connection.execute(
                """
                SELECT of_id, window_ends_on FROM qc.quality_follow_ups
                WHERE tenant_id = %s AND quality_report_id = %s
                ORDER BY created_at LIMIT 1
                """,
                (tenant_id, quality_report_id),
            ).fetchone()
            if parent is None:
                return Err(
                    "NOT_FOUND",
                    f"quality report {quality_report_id} has no open follow-up window",
                    f"le rapport qualité {quality_report_id} n'a pas de fenêtre de suivi ouverte",
                )
        of_id, window_ends_on = parent

        if observed_on > window_ends_on:
            return Err(
                "OUTSIDE_WINDOW",
                f"the follow-up window for this report closed on {window_ends_on.isoformat()}",
                f"la fenêtre de suivi de ce rapport s'est terminée le {window_ends_on.isoformat()}",
            )

        follow_up_id = str(ULID())
        self._connection.execute(
            f"""
            INSERT INTO qc.quality_follow_ups
                (id, tenant_id, {_FOLLOW_UP_INSERT_COLUMNS})
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'open', %s, %s, %s)
            """,
            (
                follow_up_id,
                tenant_id,
                quality_report_id,
                of_id,
                conformity_line_id,
                window_ends_on,
                observed_on,
                result,
                observation,
                actor_id,
            ),
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="quality_follow_up.recorded",
            entity_type="quality_follow_up",
            entity_id=follow_up_id,
            payload={
                "quality_report_id": quality_report_id,
                "conformity_line_id": conformity_line_id,
                "observed_on": observed_on.isoformat(),
            },
        )
        return Ok(self._load(tenant_id=tenant_id, follow_up_id=follow_up_id))  # type: ignore[arg-type]

    def transition(
        self, *, tenant_id: str, actor_id: str, follow_up_id: str, new_status: str, result: str | None = None
    ) -> Result[FollowUp]:
        current = self._load(tenant_id=tenant_id, follow_up_id=follow_up_id, for_update=True)
        if current is None:
            return Err("NOT_FOUND", f"follow-up {follow_up_id} not found", f"suivi {follow_up_id} introuvable")

        moved = transition_follow_up(current, new_status)
        if isinstance(moved, Err):
            return moved

        self._connection.execute(
            "UPDATE qc.quality_follow_ups SET status = %s, result = COALESCE(%s, result), updated_at = NOW() WHERE id = %s",
            (new_status, result, follow_up_id),
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="quality_follow_up.status_changed",
            entity_type="quality_follow_up",
            entity_id=follow_up_id,
            payload={"from_status": current.status, "to_status": new_status},
        )
        return Ok(self._load(tenant_id=tenant_id, follow_up_id=follow_up_id))  # type: ignore[arg-type]

    def _load(self, *, tenant_id: str, follow_up_id: str, for_update: bool = False) -> FollowUp | None:
        row = self._connection.execute(
            f"""
            SELECT {_FOLLOW_UP_COLUMNS} FROM qc.quality_follow_ups
            WHERE id = %s AND tenant_id = %s
            {'FOR UPDATE' if for_update else ''}
            """,
            (follow_up_id, tenant_id),
        ).fetchone()
        return _row_to_follow_up(row) if row is not None else None
