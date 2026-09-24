from __future__ import annotations

import psycopg

from modules.production.domain.shift_report import SECTION_KEYS


def _window(prefix: str, tenant_id: str, date_from: str | None, date_to: str | None) -> tuple[str, list[object]]:
    """The tenant/date filter on shift_reports, qualified by `prefix` ('' or 's.')."""
    clauses = [f"{prefix}tenant_id = %s"]
    params: list[object] = [tenant_id]
    if date_from is not None:
        clauses.append(f"{prefix}report_date >= %s")
        params.append(date_from)
    if date_to is not None:
        clauses.append(f"{prefix}report_date <= %s")
        params.append(date_to)
    return " AND ".join(clauses), params


class ShiftHealthService:
    """Health of the shift-reporting process itself: how many shifts are in
    each state, how long validation takes, which sections get sent back most,
    and how complete shifts are. Every figure here is a recorded fact or a
    direction-only comparison -- no target or "on time" threshold exists
    anywhere in the system for any of these, so none is invented here.
    """

    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def get_shift_health(
        self,
        *,
        tenant_id: str,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> dict:
        where, params = _window("", tenant_id, date_from, date_to)
        s_where, s_params = _window("s.", tenant_id, date_from, date_to)

        # Every shift opened in the window, whatever its status now.
        funnel = [
            {"status": status, "count": int(count)}
            for status, count in self._connection.execute(
                f"SELECT status, count(*) FROM production.shift_reports WHERE {where} GROUP BY status ORDER BY status", params
            ).fetchall()
        ]

        median, average, sample_size = self._connection.execute(
            f"""
            SELECT
                PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY EXTRACT(EPOCH FROM (validated_at - submitted_at)) / 60),
                AVG(EXTRACT(EPOCH FROM (validated_at - submitted_at)) / 60),
                count(*)
            FROM production.shift_reports
            WHERE {where} AND status = 'validated' AND submitted_at IS NOT NULL AND validated_at IS NOT NULL
            """,
            params,
        ).fetchone()
        time_to_validate_minutes = {
            "median": float(median) if median is not None else None,
            "average": float(average) if average is not None else None,
            "sample_size": int(sample_size),
        }

        # A return leaves no revision and its return_reason is cleared once the team
        # answers, so the audit entry reject_sections writes is the lasting record. A
        # section still marked returned counts too: shifts converted from rejected
        # legacy reports are returned with no audit entry. Each (shift, section) once.
        # Only shifts handed in at least once (submitted_at set) can have been sent back.
        handed_in = int(self._connection.execute(
            f"SELECT count(*) FROM production.shift_reports WHERE {where} AND submitted_at IS NOT NULL", params
        ).fetchone()[0])
        returned_counts = dict(
            self._connection.execute(
                f"""
                SELECT returned.section_key, count(DISTINCT returned.shift_report_id)
                FROM (
                    SELECT a.entity_id AS shift_report_id, section.key AS section_key
                    FROM core.audit_log a
                    CROSS JOIN LATERAL jsonb_array_elements_text(a.payload -> 'sections') AS section(key)
                    WHERE a.tenant_id = %s AND a.action = 'shift_report.sections_returned' AND a.entity_type = 'shift_report'
                    UNION
                    SELECT shift_report_id, section_key
                    FROM production.shift_report_sections
                    WHERE tenant_id = %s AND status = 'returned'
                ) returned
                JOIN production.shift_reports s ON s.id = returned.shift_report_id
                WHERE {s_where} AND s.submitted_at IS NOT NULL
                GROUP BY returned.section_key
                """,
                [tenant_id, tenant_id, *s_params],
            ).fetchall()
        )
        return_rate_by_section = [
            {
                "section_key": key,
                "returned_count": int(returned_counts.get(key, 0)),
                "total_count": handed_in,
                "return_rate_pct": (returned_counts.get(key, 0) / handed_in) * 100 if handed_in > 0 else None,
            }
            for key in SECTION_KEYS
        ]

        edited_counts = dict(
            self._connection.execute(
                f"""
                SELECT r.section_key, count(DISTINCT r.shift_report_id)
                FROM production.shift_section_revisions r
                JOIN production.shift_reports s ON s.id = r.shift_report_id AND s.tenant_id = r.tenant_id
                WHERE {s_where} AND r.section_key = ANY(%s) AND r.edited_by_validator = TRUE
                GROUP BY r.section_key
                """,
                [*s_params, list(SECTION_KEYS)],
            ).fetchall()
        )
        validator_edit_rate_by_section = [
            {
                "section_key": key,
                "edited_count": int(edited_counts.get(key, 0)),
                "total_count": handed_in,
                "edit_rate_pct": (edited_counts.get(key, 0) / handed_in) * 100 if handed_in > 0 else None,
            }
            for key in SECTION_KEYS
        ]

        avg_filled, shift_count = self._connection.execute(
            f"""
            SELECT AVG(filled), count(*)
            FROM (
                SELECT s.id, count(sec.section_key) FILTER (WHERE sec.status != 'empty') AS filled
                FROM production.shift_reports s
                LEFT JOIN production.shift_report_sections sec ON sec.shift_report_id = s.id AND sec.tenant_id = s.tenant_id
                WHERE {s_where}
                GROUP BY s.id
            ) per_shift
            """,
            s_params,
        ).fetchone()
        completeness = {
            "average_sections_filled": float(avg_filled) if avg_filled is not None else None,
            "total_sections": len(SECTION_KEYS),
            "shift_count": int(shift_count),
        }

        return {
            "funnel": funnel,
            "time_to_validate_minutes": time_to_validate_minutes,
            "return_rate_by_section": return_rate_by_section,
            "validator_edit_rate_by_section": validator_edit_rate_by_section,
            "completeness": completeness,
        }
