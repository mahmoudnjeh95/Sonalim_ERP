from __future__ import annotations

import datetime

import psycopg
from ulid import ULID

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from core.events.outbox import publish_event
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

# For INSERTs that supply the id separately. A manually recorded observation is
# not tied to one conformity line, so conformity_line_id is left NULL there --
# only validate_report's own insert sets it.
_FOLLOW_UP_INSERT_COLUMNS = """
    quality_report_id, of_id, window_ends_on, observed_on, status, result, observation, actor_id
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

    GRAINS = ("day", "week", "month", "year")

    # get_conformity_summary / team_conformity / index_trend read the old
    # per-report conformity columns, which no longer exist. They are rewritten
    # against conformity lines and parameter entries in the next task; until
    # then they refuse loudly rather than query dropped columns.

    def get_conformity_summary(self, *, tenant_id: str, of_id: str) -> dict:
        raise NotImplementedError("rewritten in the next task")

    def team_conformity(
        self, *, tenant_id: str, grain: str, date_from: str | None = None, date_to: str | None = None
    ) -> list[dict]:
        if grain not in self.GRAINS:
            raise ValueError(f"grain must be one of {self.GRAINS}")
        raise NotImplementedError("rewritten in the next task")

    def index_trend(
        self, *, tenant_id: str, grain: str, date_from: str | None = None, date_to: str | None = None
    ) -> list[dict]:
        if grain not in self.GRAINS:
            raise ValueError(f"grain must be one of {self.GRAINS}")
        raise NotImplementedError("rewritten in the next task")

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
        for the header -- it asks production's own service. The packing rows
        are read directly because get_shift returns section payloads, not
        typed rows with stable ids.
        """
        from modules.production.api.shift_report_service import ShiftReportService

        shifts = ShiftReportService(self._connection)
        found = shifts.get_shift(tenant_id=tenant_id, shift_report_id=shift_report_id)
        if isinstance(found, Err):
            return found
        header = found.value

        packing_rows = self._connection.execute(
            """
            SELECT id, of_id, product_id FROM production.shift_packing_rows
            WHERE tenant_id = %s AND shift_report_id = %s AND product_id IS NOT NULL
            ORDER BY id
            """,
            (tenant_id, shift_report_id),
        ).fetchall()

        return Ok(
            {
                "work_center_id": header["work_center_id"],
                "report_date": datetime.date.fromisoformat(header["report_date"]),
                "shift": header["shift"],
                "team": header["team"],
                "status": header["status"],
                "packing_rows": [{"id": r[0], "of_id": r[1], "product_id": r[2]} for r in packing_rows],
            }
        )

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
            return Err("MISSING_SHIFT_REPORT", "a quality report must inspect a shift report")

        resolved = self._resolve_shift(tenant_id=tenant_id, shift_report_id=shift_report_id)
        if isinstance(resolved, Err):
            return resolved
        link = resolved.value

        duplicate = self._connection.execute(
            "SELECT 1 FROM qc.quality_reports WHERE tenant_id = %s AND shift_report_id = %s",
            (tenant_id, shift_report_id),
        ).fetchone()
        if duplicate is not None:
            return Err("DUPLICATE_REPORT", "a quality report already exists for this shift report")

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
            return Err("NOT_FOUND", f"quality report {report_id} not found")
        if report.status != "draft":
            return Err("NOT_EDITABLE", f"a {report.status} quality report cannot be edited as a draft")

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
                return Err("LINE_NOT_FOUND", f"no conformity line for packing row {row_id} on this report")
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

        Re-linking to a different shift_report_id re-derives report_date, shift and
        team together from it, and adds a conformity line for each of its packing
        rows not already present. Existing lines are never removed here -- one may
        carry a non-conformity, and silently orphaning it is worse than a stale line.
        """
        report = self._load_report(tenant_id=tenant_id, report_id=report_id, for_update=True)
        if report is None:
            return Err("NOT_FOUND", f"quality report {report_id} not found")

        if lines is not None:
            applied = self._apply_line_edits(tenant_id=tenant_id, report_id=report_id, edits=lines)
            if isinstance(applied, Err):
                return applied

        if shift_report_id is not None:
            resolved = self._resolve_shift(tenant_id=tenant_id, shift_report_id=shift_report_id)
            if isinstance(resolved, Err):
                return resolved
            duplicate = self._connection.execute(
                "SELECT 1 FROM qc.quality_reports WHERE tenant_id = %s AND shift_report_id = %s AND id != %s",
                (tenant_id, shift_report_id, report_id),
            ).fetchone()
            if duplicate is not None:
                return Err("DUPLICATE_REPORT", "a quality report already exists for this shift report")
            link = resolved.value
            self._connection.execute(
                "UPDATE qc.quality_reports SET shift_report_id = %s, team = %s, shift = %s, report_date = %s, "
                "updated_at = NOW() WHERE id = %s",
                (shift_report_id, link["team"], link["shift"], link["report_date"], report_id),
            )
            existing_row_ids = {
                r[0]
                for r in self._connection.execute(
                    "SELECT shift_packing_row_id FROM qc.quality_conformity_lines WHERE tenant_id = %s AND report_id = %s",
                    (tenant_id, report_id),
                ).fetchall()
            }
            for row in link["packing_rows"]:
                if row["id"] not in existing_row_ids:
                    self._connection.execute(
                        """
                        INSERT INTO qc.quality_conformity_lines
                            (id, tenant_id, report_id, shift_packing_row_id, of_id, product_id)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                        (str(ULID()), tenant_id, report_id, row["id"], row["of_id"], row["product_id"]),
                    )

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
            return Err("NOT_FOUND", f"quality report {report_id} not found")

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
            return Err("NOT_FOUND", f"quality report {report_id} not found")

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
            return Err("MISSING_REASON", "a rejection must say what is wrong with the report")

        report = self._load_report(tenant_id=tenant_id, report_id=report_id, for_update=True)
        if report is None:
            return Err("NOT_FOUND", f"quality report {report_id} not found")

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
            return Err("NOT_FOUND", f"quality report {report_id} not found")

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
            return Err("MISSING_REASON", "deleting a report must say why")

        report = self._load_report(tenant_id=tenant_id, report_id=report_id, for_update=True)
        if report is None:
            return Err("NOT_FOUND", f"quality report {report_id} not found")

        attached = self._connection.execute(
            "SELECT COUNT(*) FROM qc.non_conformities WHERE tenant_id = %s AND quality_report_id = %s",
            (tenant_id, report_id),
        ).fetchone()
        if attached and attached[0]:
            return Err(
                "NON_CONFORMITY_ATTACHED",
                "detach the non-conformities raised from this report before deleting it",
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
    ) -> Result[FollowUp]:
        parent = self._connection.execute(
            """
            SELECT of_id, window_ends_on FROM qc.quality_follow_ups
            WHERE tenant_id = %s AND quality_report_id = %s
            ORDER BY created_at LIMIT 1
            """,
            (tenant_id, quality_report_id),
        ).fetchone()
        if parent is None:
            return Err("NOT_FOUND", f"quality report {quality_report_id} has no open follow-up window")
        of_id, window_ends_on = parent

        if observed_on > window_ends_on:
            return Err("OUTSIDE_WINDOW", f"the follow-up window for this report closed on {window_ends_on.isoformat()}")

        follow_up_id = str(ULID())
        self._connection.execute(
            f"""
            INSERT INTO qc.quality_follow_ups
                (id, tenant_id, {_FOLLOW_UP_INSERT_COLUMNS})
            VALUES (%s, %s, %s, %s, %s, %s, 'open', %s, %s, %s)
            """,
            (
                follow_up_id,
                tenant_id,
                quality_report_id,
                of_id,
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
            payload={"quality_report_id": quality_report_id, "observed_on": observed_on.isoformat()},
        )
        return Ok(self._load(tenant_id=tenant_id, follow_up_id=follow_up_id))  # type: ignore[arg-type]

    def transition(
        self, *, tenant_id: str, actor_id: str, follow_up_id: str, new_status: str, result: str | None = None
    ) -> Result[FollowUp]:
        current = self._load(tenant_id=tenant_id, follow_up_id=follow_up_id, for_update=True)
        if current is None:
            return Err("NOT_FOUND", f"follow-up {follow_up_id} not found")

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
