from __future__ import annotations

import datetime

import psycopg
from ulid import ULID

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from core.events.outbox import publish_event
from modules.qc.domain.quality import (
    DEFAULT_FOLLOW_UP_WINDOW_DAYS,
    FollowUp,
    QualityReport,
    QualityReportDetail,
    follow_up_window_end,
    is_conforming,
    transition_follow_up,
    transition_quality_report,
    validate_quality_detail,
    validate_window_days,
)

_REPORT_COLUMNS = """
    id, of_id, report_date, status, revision, conditionnement_report_id, team, shift, created_by,
    submitted_at, validated_by, validated_at, rejection_reason
"""

_DETAIL_COLUMNS = """
    pre_dryer_index, humidity_percentage, cooling_index, pf_index, sumo_index,
    conforming_cartons, non_conforming_cartons, defect_details, comments, corrective_action
"""

_FOLLOW_UP_COLUMNS = """
    id, quality_report_id, of_id, window_ends_on, observed_on, status, result, observation, actor_id
"""

# Same list without the id, for INSERTs that supply it separately.
_FOLLOW_UP_INSERT_COLUMNS = """
    quality_report_id, of_id, window_ends_on, observed_on, status, result, observation, actor_id
"""


def _row_to_report(row: tuple) -> QualityReport:
    return QualityReport(
        id=row[0],
        of_id=row[1],
        report_date=row[2],
        status=row[3],
        revision=row[4],
        conditionnement_report_id=row[5],
        team=row[6],
        shift=row[7],
        created_by=row[8],
        submitted_at=row[9],
        validated_by=row[10],
        validated_at=row[11],
        rejection_reason=row[12],
    )


def _row_to_detail(row: tuple) -> QualityReportDetail:
    return QualityReportDetail(
        pre_dryer_index=float(row[0]) if row[0] is not None else None,
        humidity_percentage=float(row[1]) if row[1] is not None else None,
        cooling_index=float(row[2]) if row[2] is not None else None,
        pf_index=float(row[3]) if row[3] is not None else None,
        sumo_index=float(row[4]) if row[4] is not None else None,
        conforming_cartons=float(row[5]),
        non_conforming_cartons=float(row[6]),
        defect_details=row[7],
        comments=row[8],
        corrective_action=row[9],
    )


def _detail_values(detail: QualityReportDetail) -> tuple:
    return (
        detail.pre_dryer_index,
        detail.humidity_percentage,
        detail.cooling_index,
        detail.pf_index,
        detail.sumo_index,
        detail.conforming_cartons,
        detail.non_conforming_cartons,
        detail.defect_details,
        detail.comments,
        detail.corrective_action,
    )


def _row_to_follow_up(row: tuple) -> FollowUp:
    return FollowUp(
        id=row[0],
        quality_report_id=row[1],
        of_id=row[2],
        window_ends_on=row[3],
        observed_on=row[4],
        status=row[5],
        result=row[6],
        observation=row[7],
        actor_id=row[8],
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
    """The quality report and the follow-up window it opens.

    Deliberately its own aggregate rather than a third detail table hanging off
    production's header: a module may not read another's tables, and quality
    outlives the OF it was raised against.
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

    def get_report(self, *, tenant_id: str, report_id: str) -> dict | None:
        report = self._load_report(tenant_id=tenant_id, report_id=report_id)
        if report is None:
            return None
        return {"report": report, "detail": self._load_detail(tenant_id=tenant_id, report_id=report_id)}

    def get_conformity_summary(self, *, tenant_id: str, of_id: str) -> dict:
        """How an OF's quality came out, summed over its validated reports.

        This is qc's answer to production's consolidation question. Production
        calls it rather than reading qc's tables — an immediate answer the caller
        needs, which is exactly what a synchronous cross-module call is for.

        Only validated reports count. A draft or rejected quality report is a
        claim, not a verdict, and consolidating it would let unapproved figures
        into the OF's official result.
        """
        row = self._connection.execute(
            """
            SELECT
                count(*),
                COALESCE(SUM(d.conforming_cartons), 0),
                COALESCE(SUM(d.non_conforming_cartons), 0)
            FROM qc.quality_reports r
            JOIN qc.quality_report_details d ON d.report_id = r.id AND d.tenant_id = r.tenant_id
            WHERE r.tenant_id = %s AND r.of_id = %s AND r.status = 'validated'
            """,
            (tenant_id, of_id),
        ).fetchone()
        report_count, conforming, non_conforming = int(row[0]), float(row[1]), float(row[2])
        total = conforming + non_conforming
        return {
            "validated_report_count": report_count,
            "conforming_cartons": conforming,
            "non_conforming_cartons": non_conforming,
            # None rather than 100% when nothing was inspected: "no data" and
            # "everything passed" are different answers.
            "conformity_rate": (conforming / total) if total > 0 else None,
            "pending_nc_reports": self._reports_needing_nc(tenant_id=tenant_id, of_id=of_id),
        }

    def _reports_needing_nc(self, *, tenant_id: str, of_id: str) -> list[dict]:
        """Validated reports that logged a defect but never got a case raised for it.

        A carton flagged `non_conforming_cartons` on the inspection form is only
        an observation -- nothing pulls it off the market until someone raises a
        non-conformity ticket against it (decision 21, see
        `NonConformityService.get_rejected_quantity_for_of`). That second step is
        manual, so a validated report can sit indefinitely with a defect nobody
        acted on; this is what lets a screen say so instead of only showing a
        conformity rate that already includes the drop.
        """
        rows = self._connection.execute(
            """
            SELECT r.id, r.report_date, d.non_conforming_cartons
            FROM qc.quality_reports r
            JOIN qc.quality_report_details d ON d.report_id = r.id AND d.tenant_id = r.tenant_id
            WHERE r.tenant_id = %s AND r.of_id = %s AND r.status = 'validated'
              AND d.non_conforming_cartons > 0
              AND NOT EXISTS (
                  SELECT 1 FROM qc.non_conformities n
                  WHERE n.tenant_id = r.tenant_id AND n.quality_report_id = r.id
              )
            ORDER BY r.report_date DESC
            """,
            (tenant_id, of_id),
        ).fetchall()
        return [
            {
                "report_id": report_id,
                "report_date": report_date.isoformat(),
                "non_conforming_cartons": float(non_conforming_cartons),
            }
            for report_id, report_date, non_conforming_cartons in rows
        ]

    GRAINS = ("day", "week", "month", "year")

    def team_conformity(
        self,
        *,
        tenant_id: str,
        grain: str,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> list[dict]:
        """Conformity from validated reports, bucketed by team and period.

        Same shape and validated-only rule as `get_conformity_summary`, just
        grouped by team and a calendar bucket instead of filtered to one OF —
        production's team-performance panel and the QC dashboard's plant-wide
        trend both read this, the second by summing across teams per period.
        """
        if grain not in self.GRAINS:
            raise ValueError(f"grain must be one of {self.GRAINS}")

        clauses = ["qr.tenant_id = %s", "qr.status = 'validated'"]
        params: list[object] = [grain, tenant_id]
        if date_from is not None:
            clauses.append("qr.report_date >= %s")
            params.append(date_from)
        if date_to is not None:
            clauses.append("qr.report_date <= %s")
            params.append(date_to)

        rows = self._connection.execute(
            f"""
            SELECT
                qr.team,
                date_trunc(%s, qr.report_date)::date AS period,
                count(*) AS report_count,
                COALESCE(SUM(d.conforming_cartons), 0),
                COALESCE(SUM(d.non_conforming_cartons), 0)
            FROM qc.quality_reports qr
            JOIN qc.quality_report_details d ON d.report_id = qr.id AND d.tenant_id = qr.tenant_id
            WHERE {' AND '.join(clauses)}
            GROUP BY qr.team, period
            """,
            params,
        ).fetchall()
        return [
            {
                "team": team,
                "period": period.isoformat(),
                "report_count": int(report_count),
                "conforming_cartons": float(conforming),
                "non_conforming_cartons": float(non_conforming),
            }
            for team, period, report_count, conforming, non_conforming in rows
        ]

    def index_trend(
        self,
        *,
        tenant_id: str,
        grain: str,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> list[dict]:
        """Average process indices from validated reports, bucketed by period.

        Plant-wide rather than by team like team_conformity -- these are
        leading process indicators (pre-dryer, humidity, cooling, PF, SUMO),
        not a team ranking. AVG(...) ignores NULLs on its own, so a shift that
        skipped one index doesn't drag the others toward zero.
        """
        if grain not in self.GRAINS:
            raise ValueError(f"grain must be one of {self.GRAINS}")

        clauses = ["qr.tenant_id = %s", "qr.status = 'validated'"]
        params: list[object] = [grain, tenant_id]
        if date_from is not None:
            clauses.append("qr.report_date >= %s")
            params.append(date_from)
        if date_to is not None:
            clauses.append("qr.report_date <= %s")
            params.append(date_to)

        rows = self._connection.execute(
            f"""
            SELECT
                date_trunc(%s, qr.report_date)::date AS period,
                count(*) AS report_count,
                AVG(d.pre_dryer_index),
                AVG(d.humidity_percentage),
                AVG(d.cooling_index),
                AVG(d.pf_index),
                AVG(d.sumo_index)
            FROM qc.quality_reports qr
            JOIN qc.quality_report_details d ON d.report_id = qr.id AND d.tenant_id = qr.tenant_id
            WHERE {' AND '.join(clauses)}
            GROUP BY period
            ORDER BY period
            """,
            params,
        ).fetchall()
        return [
            {
                "period": period.isoformat(),
                "report_count": int(report_count),
                "pre_dryer_index": float(pre_dryer_index) if pre_dryer_index is not None else None,
                "humidity_percentage": float(humidity_percentage) if humidity_percentage is not None else None,
                "cooling_index": float(cooling_index) if cooling_index is not None else None,
                "pf_index": float(pf_index) if pf_index is not None else None,
                "sumo_index": float(sumo_index) if sumo_index is not None else None,
            }
            for (
                period, report_count, pre_dryer_index, humidity_percentage, cooling_index, pf_index, sumo_index,
            ) in rows
        ]

    def list_reports(
        self, *, tenant_id: str, of_id: str | None = None, status: str | None = None
    ) -> list[QualityReport]:
        clauses = ["tenant_id = %s"]
        params: list[object] = [tenant_id]
        if of_id is not None:
            clauses.append("of_id = %s")
            params.append(of_id)
        if status is not None:
            clauses.append("status = %s")
            params.append(status)
        rows = self._connection.execute(
            f"""
            SELECT {_REPORT_COLUMNS} FROM qc.quality_reports
            WHERE {' AND '.join(clauses)}
            ORDER BY report_date DESC, created_at DESC
            """,
            params,
        ).fetchall()
        return [_row_to_report(row) for row in rows]

    # ---- writes ----------------------------------------------------------

    def _resolve_conditionnement(self, *, tenant_id: str, conditionnement_report_id: str) -> Result[dict]:
        """Resolve a conditionnement report into what a quality report needs from it.

        Production is the authority on of_id/team/shift/date and on the
        packaging figures QC shows as a hint before the inspector fills
        anything in. qc never reads production's tables for this -- it asks
        production's own service for an immediate answer, the same
        synchronous cross-module call production already makes into qc for
        get_conformity_summary, just in the other direction.
        """
        from modules.production.api.production_report_service import ProductionReportService

        reports = ProductionReportService(self._connection)
        found = reports.get_report(tenant_id=tenant_id, report_id=conditionnement_report_id)
        if found is None:
            return Err("NOT_FOUND", f"conditionnement report {conditionnement_report_id} not found")
        header, detail = found["report"], found["detail"]
        if header.report_type != "conditionnement":
            return Err("WRONG_REPORT_TYPE", f"report {conditionnement_report_id} is not a conditionnement report")

        regrind_quantity = None
        if detail.daily_report_id is not None:
            daily = reports.get_report(tenant_id=tenant_id, report_id=detail.daily_report_id)
            if daily is not None and daily["detail"] is not None:
                regrind_quantity = daily["detail"].regrind_quantity

        return Ok(
            {
                "of_id": header.of_id,
                "report_date": header.report_date,
                "shift": header.shift,
                "team": header.team,
                "status": header.status,
                "packets_counted": detail.packets_counted,
                "carton_quantity": detail.carton_quantity,
                "finished_product_quantity": detail.finished_product_quantity,
                "regrind_quantity": regrind_quantity,
            }
        )

    def list_inspectable_conditionnement_reports(
        self, *, tenant_id: str, of_id: str | None = None
    ) -> list[dict]:
        """Conditionnement reports a QC report can still be opened against.

        Backs both the picker in the create-report form and the hint panel
        shown once one is selected -- one call gives the inspector the OF,
        team, shift, date, and the packets/carton/regrind figures to check
        their reading against, before they type anything.
        """
        from modules.production.api.production_report_service import ProductionReportService

        already_linked = {
            row[0]
            for row in self._connection.execute(
                "SELECT conditionnement_report_id FROM qc.quality_reports "
                "WHERE tenant_id = %s AND conditionnement_report_id IS NOT NULL",
                (tenant_id,),
            ).fetchall()
        }

        reports = ProductionReportService(self._connection)
        candidates = reports.list_reports(tenant_id=tenant_id, of_id=of_id, report_type="conditionnement")

        rows = []
        for header in candidates:
            if header.id in already_linked:
                continue
            resolved = self._resolve_conditionnement(tenant_id=tenant_id, conditionnement_report_id=header.id)
            if isinstance(resolved, Err):
                continue
            rows.append({"conditionnement_report_id": header.id, **resolved.value})
        return rows

    def create_report(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        conditionnement_report_id: str,
        detail: QualityReportDetail | None = None,
    ) -> Result[dict]:
        if not conditionnement_report_id.strip():
            return Err("MISSING_CONDITIONNEMENT_REPORT", "a quality report must inspect a conditionnement report")

        detail = detail or QualityReportDetail()
        validation = validate_quality_detail(detail)
        if isinstance(validation, Err):
            return validation

        resolved = self._resolve_conditionnement(
            tenant_id=tenant_id, conditionnement_report_id=conditionnement_report_id
        )
        if isinstance(resolved, Err):
            return resolved
        link = resolved.value

        duplicate = self._connection.execute(
            "SELECT 1 FROM qc.quality_reports WHERE tenant_id = %s AND conditionnement_report_id = %s",
            (tenant_id, conditionnement_report_id),
        ).fetchone()
        if duplicate is not None:
            return Err("DUPLICATE_REPORT", "a quality report already exists for this conditionnement report")

        report_id = str(ULID())
        self._connection.execute(
            """
            INSERT INTO qc.quality_reports
                (id, tenant_id, of_id, report_date, status, revision, conditionnement_report_id, team, shift, created_by)
            VALUES (%s, %s, %s, %s, 'draft', 1, %s, %s, %s, %s)
            """,
            (
                report_id,
                tenant_id,
                link["of_id"],
                link["report_date"],
                conditionnement_report_id,
                link["team"],
                link["shift"],
                actor_id,
            ),
        )
        self._connection.execute(
            f"""
            INSERT INTO qc.quality_report_details (report_id, tenant_id, {_DETAIL_COLUMNS})
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (report_id, tenant_id, *_detail_values(detail)),
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="quality_report.created",
            entity_type="quality_report",
            entity_id=report_id,
            payload={
                "of_id": link["of_id"],
                "conditionnement_report_id": conditionnement_report_id,
                "report_date": link["report_date"].isoformat(),
            },
        )
        return Ok(self._read(tenant_id=tenant_id, report_id=report_id))

    def update_draft(
        self, *, tenant_id: str, actor_id: str, report_id: str, detail: QualityReportDetail
    ) -> Result[dict]:
        report = self._load_report(tenant_id=tenant_id, report_id=report_id, for_update=True)
        if report is None:
            return Err("NOT_FOUND", f"quality report {report_id} not found")
        if report.status != "draft":
            return Err("NOT_EDITABLE", f"a {report.status} quality report cannot be edited as a draft")

        validation = validate_quality_detail(detail)
        if isinstance(validation, Err):
            return validation

        self._write_detail(tenant_id=tenant_id, report_id=report_id, detail=detail)
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="quality_report.draft_updated",
            entity_type="quality_report",
            entity_id=report_id,
            payload={"conforming_cartons": detail.conforming_cartons, "non_conforming_cartons": detail.non_conforming_cartons},
        )
        return Ok(self._read(tenant_id=tenant_id, report_id=report_id))

    def admin_update_report(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        report_id: str,
        detail: QualityReportDetail | None = None,
        conditionnement_report_id: str | None = None,
        reason: str | None = None,
    ) -> Result[dict]:
        """Edit-in-place, gated by qc.admin_quality_reports.

        A separate, more trusted right than progressing a report through its normal
        workflow — and allowed regardless of status, because the permission is what
        limits the blast radius, not a status check.

        Re-linking to a different conditionnement_report_id re-derives of_id,
        report_date, shift and team together from it. There is no path left to
        set those independently, even in this elevated path -- a correction
        can never leave the report pointing at one conditionnement run while
        carrying another run's team or shift.
        """
        report = self._load_report(tenant_id=tenant_id, report_id=report_id, for_update=True)
        if report is None:
            return Err("NOT_FOUND", f"quality report {report_id} not found")

        current = self._load_detail(tenant_id=tenant_id, report_id=report_id) or QualityReportDetail()
        updated = detail if detail is not None else current
        validation = validate_quality_detail(updated)
        if isinstance(validation, Err):
            return validation

        link = None
        if conditionnement_report_id is not None:
            resolved = self._resolve_conditionnement(
                tenant_id=tenant_id, conditionnement_report_id=conditionnement_report_id
            )
            if isinstance(resolved, Err):
                return resolved
            duplicate = self._connection.execute(
                "SELECT 1 FROM qc.quality_reports WHERE tenant_id = %s AND conditionnement_report_id = %s AND id != %s",
                (tenant_id, conditionnement_report_id, report_id),
            ).fetchone()
            if duplicate is not None:
                return Err("DUPLICATE_REPORT", "a quality report already exists for this conditionnement report")
            link = resolved.value

        self._write_detail(tenant_id=tenant_id, report_id=report_id, detail=updated)
        self._connection.execute(
            """
            UPDATE qc.quality_reports
            SET conditionnement_report_id = %s, of_id = %s, team = %s, shift = %s, report_date = %s, updated_at = NOW()
            WHERE id = %s
            """,
            (
                conditionnement_report_id if link is not None else report.conditionnement_report_id,
                link["of_id"] if link is not None else report.of_id,
                link["team"] if link is not None else report.team,
                link["shift"] if link is not None else report.shift,
                link["report_date"] if link is not None else report.report_date,
                report_id,
            ),
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="quality_report.updated",
            entity_type="quality_report",
            entity_id=report_id,
            payload={
                "conditionnement_report_id": conditionnement_report_id,
                "non_conforming_cartons": updated.non_conforming_cartons,
                "reason": reason,
            },
        )
        return Ok(self._read(tenant_id=tenant_id, report_id=report_id))

    def submit_report(self, *, tenant_id: str, actor_id: str, report_id: str) -> Result[QualityReport]:
        report = self._load_report(tenant_id=tenant_id, report_id=report_id, for_update=True)
        if report is None:
            return Err("NOT_FOUND", f"quality report {report_id} not found")

        result = transition_quality_report(report, "submitted")
        if isinstance(result, Err):
            return result

        detail = self._load_detail(tenant_id=tenant_id, report_id=report_id)
        if detail is None:
            return Err("NOT_FOUND", f"quality report {report_id} has no detail to submit")
        validation = validate_quality_detail(detail)
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

    def validate_report(
        self, *, tenant_id: str, actor_id: str, report_id: str, correlation_id: str, product_id: str | None = None
    ) -> Result[dict]:
        """Make a quality report official and open its follow-up window.

        Posts no stock — quality only moves inventory through a non-conformity.
        `product_id` is supplied by the caller (resolved from the OF through
        production's service) so the per-product follow-up window can be applied
        without qc reading production's tables.
        """
        report = self._load_report(tenant_id=tenant_id, report_id=report_id, for_update=True)
        if report is None:
            return Err("NOT_FOUND", f"quality report {report_id} not found")

        result = transition_quality_report(report, "validated")
        if isinstance(result, Err):
            return result

        detail = self._load_detail(tenant_id=tenant_id, report_id=report_id)
        if detail is None:
            return Err("NOT_FOUND", f"quality report {report_id} has no detail")

        self._connection.execute(
            """
            UPDATE qc.quality_reports
            SET status = 'validated', validated_by = %s, validated_at = NOW(), rejection_reason = NULL, updated_at = NOW()
            WHERE id = %s
            """,
            (actor_id, report_id),
        )

        window_days = FollowUpPolicyService(self._connection).resolve_window_days(
            tenant_id=tenant_id, product_id=product_id
        )
        window_ends_on = follow_up_window_end(report.report_date, window_days)
        follow_up_id = str(ULID())
        self._connection.execute(
            f"""
            INSERT INTO qc.quality_follow_ups
                (id, tenant_id, {_FOLLOW_UP_INSERT_COLUMNS})
            VALUES (%s, %s, %s, %s, %s, %s, 'open', NULL, %s, %s)
            """,
            (
                follow_up_id,
                tenant_id,
                report_id,
                report.of_id,
                window_ends_on,
                report.report_date,
                "opened on validation",
                actor_id,
            ),
        )

        publish_event(
            self._connection,
            event_type="qc.quality_report.validated",
            producer="qc",
            tenant_id=tenant_id,
            correlation_id=correlation_id,
            payload={
                "quality_report_id": report_id,
                "of_id": report.of_id,
                "is_conforming": is_conforming(detail),
            },
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="quality_report.validated",
            entity_type="quality_report",
            entity_id=report_id,
            payload={
                "of_id": report.of_id,
                "is_conforming": is_conforming(detail),
                "window_days": window_days,
                "window_ends_on": window_ends_on.isoformat(),
            },
        )
        return Ok(
            {
                "report": self._load_report(tenant_id=tenant_id, report_id=report_id),
                "detail": detail,
                "follow_up_id": follow_up_id,
                "window_ends_on": window_ends_on,
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
        non_conformities = self._connection.execute(
            """
            SELECT id, product_id, quantity, quarantine_location_id, source_location_id
            FROM qc.non_conformities
            WHERE tenant_id = %s AND quality_report_id = %s AND status IN ('raised', 'quarantined')
            """,
            (tenant_id, report_id),
        ).fetchall()

        for nc_id, product_id, quantity, quarantine_location_id, source_location_id in non_conformities:
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
                of_id=report.of_id,
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
        warehouse. What validation *does* create is a follow-up window, and that
        window goes with the report. A non-conformity raised from the report is
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
            payload={"reason": reason, "status_when_deleted": report.status, "of_id": report.of_id},
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
