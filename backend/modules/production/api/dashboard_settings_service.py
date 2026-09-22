from __future__ import annotations

import datetime

import psycopg

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from modules.production.domain.dashboard import (
    STORE_ROLES,
    ShiftWindow,
    shift_length_minutes,
    validate_shift_window,
    validate_team_rotation,
)


def _hhmm(value) -> str:
    return value.strftime("%H:%M")


class DashboardSettingsService:
    """The three lists the production dashboard is configured with.

    Each is replaced as a whole, not edited row by row: a supervisor sees the
    complete roster or store list on one screen and saves it, so the stored list
    is always exactly what they last saw. Every replacement is audited with the
    list it left behind.

    Machines are not among them: which machines a line has and what stage each
    works at are declared once, in maintenance's equipment registry.
    """

    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    def line_store_id(self, *, tenant_id: str) -> str | None:
        """The store finished product waits in, when the settings name exactly one.

        None when none is set, and also when several are: packed goods are not put into one of
        them by guesswork, they keep going to the product's own store until the settings are clear.
        """
        rows = self._connection.execute(
            "SELECT location_id FROM production.store_roles WHERE tenant_id = %s AND role = 'line'", (tenant_id,)
        ).fetchall()
        return rows[0][0] if len(rows) == 1 else None

    def get_settings(self, *, tenant_id: str) -> dict:
        windows = self._connection.execute(
            "SELECT shift, start_time, end_time FROM production.shift_windows "
            "WHERE tenant_id = %s ORDER BY start_time, shift",
            (tenant_id,),
        ).fetchall()
        rotation = self._connection.execute(
            "SELECT team, anchor_date, anchor_stop FROM production.team_rotation WHERE tenant_id = %s ORDER BY anchor_stop",
            (tenant_id,),
        ).fetchall()
        roles = self._connection.execute(
            "SELECT location_id, role FROM production.store_roles WHERE tenant_id = %s ORDER BY location_id",
            (tenant_id,),
        ).fetchall()
        return {
            # The length rides along so a report form can offer the shift's hours as the
            # time produced without every screen re-deriving how a night shift wraps.
            "shift_windows": [
                {
                    "shift": s,
                    "start_time": _hhmm(a),
                    "end_time": _hhmm(b),
                    "length_minutes": shift_length_minutes(ShiftWindow(shift=s, start=a, end=b)),
                }
                for s, a, b in windows
            ],
            "team_rotation": [{"team": t, "anchor_date": d.isoformat(), "anchor_stop": s} for t, d, s in rotation],
            "store_roles": [{"location_id": l, "role": r} for l, r in roles],
        }

    def list_shift_windows(self, *, tenant_id: str) -> list[ShiftWindow]:
        rows = self._connection.execute(
            "SELECT shift, start_time, end_time FROM production.shift_windows WHERE tenant_id = %s", (tenant_id,)
        ).fetchall()
        return [ShiftWindow(shift=s, start=a, end=b) for s, a, b in rows]

    def replace_shift_windows(self, *, tenant_id: str, actor_id: str, windows: list[ShiftWindow]) -> Result[list[dict]]:
        seen: set[str] = set()
        for window in windows:
            check = validate_shift_window(shift=window.shift, start=window.start, end=window.end)
            if isinstance(check, Err):
                return check
            key = window.shift.strip().lower()
            if key in seen:
                return Err("DUPLICATE_ENTRY", f"shift {window.shift!r} appears twice")
            seen.add(key)

        self._connection.execute("DELETE FROM production.shift_windows WHERE tenant_id = %s", (tenant_id,))
        for window in windows:
            self._connection.execute(
                "INSERT INTO production.shift_windows (tenant_id, shift, start_time, end_time) VALUES (%s, %s, %s, %s)",
                (tenant_id, window.shift.strip(), window.start, window.end),
            )
        result = [{"shift": w.shift.strip(), "start_time": _hhmm(w.start), "end_time": _hhmm(w.end)} for w in windows]
        self._audit(tenant_id, actor_id, "shift_windows", result)
        return Ok(result)

    def replace_team_rotation(self, *, tenant_id: str, actor_id: str, entries: list[dict]) -> Result[list[dict]]:
        num_shifts = len(self.list_shift_windows(tenant_id=tenant_id))
        if num_shifts == 0:
            return Err("NO_SHIFTS_CONFIGURED", "configure the plant's shifts before the team rotation")

        cleaned = []
        for entry in entries:
            team = (entry.get("team") or "").strip()
            raw_date = entry.get("anchor_date")
            try:
                anchor_date = raw_date if isinstance(raw_date, datetime.date) else datetime.date.fromisoformat(str(raw_date))
            except (TypeError, ValueError):
                return Err("INVALID_ENTRY", "a rotation entry needs a valid anchor date")
            anchor_stop = entry.get("anchor_stop")
            if not team or not isinstance(anchor_stop, int):
                return Err("INVALID_ENTRY", "a rotation entry needs a team and its stop in the cycle")
            cleaned.append({"team": team, "anchor_date": anchor_date, "anchor_stop": anchor_stop})

        check = validate_team_rotation(cleaned, num_shifts=num_shifts)
        if isinstance(check, Err):
            return check

        self._connection.execute("DELETE FROM production.team_rotation WHERE tenant_id = %s", (tenant_id,))
        for row in cleaned:
            self._connection.execute(
                "INSERT INTO production.team_rotation (tenant_id, team, anchor_date, anchor_stop) VALUES (%s, %s, %s, %s)",
                (tenant_id, row["team"], row["anchor_date"], row["anchor_stop"]),
            )
        result = [{"team": r["team"], "anchor_date": r["anchor_date"].isoformat(), "anchor_stop": r["anchor_stop"]} for r in cleaned]
        self._audit(tenant_id, actor_id, "team_rotation", result)
        return Ok(result)

    def replace_store_roles(self, *, tenant_id: str, actor_id: str, entries: list[dict]) -> Result[list[dict]]:
        return self._replace_keyed(
            tenant_id, actor_id, entries,
            table="production.store_roles", key="location_id", value="role", allowed=STORE_ROLES,
            section="store_roles",
        )

    def _replace_keyed(
        self, tenant_id: str, actor_id: str, entries: list[dict], *, table: str, key: str, value: str,
        allowed: tuple[str, ...], section: str,
    ) -> Result[list[dict]]:
        seen: set[str] = set()
        cleaned = []
        for entry in entries:
            ref = (entry.get(key) or "").strip()
            chosen = entry.get(value)
            if not ref:
                return Err("INVALID_ENTRY", f"every entry needs its {key}")
            if chosen not in allowed:
                return Err("INVALID_ENTRY", f"{value} must be one of {list(allowed)}")
            if ref in seen:
                return Err("DUPLICATE_ENTRY", f"{key} {ref} appears twice")
            seen.add(ref)
            cleaned.append({key: ref, value: chosen})

        self._connection.execute(f"DELETE FROM {table} WHERE tenant_id = %s", (tenant_id,))
        for row in cleaned:
            self._connection.execute(
                f"INSERT INTO {table} (tenant_id, {key}, {value}) VALUES (%s, %s, %s)",
                (tenant_id, row[key], row[value]),
            )
        self._audit(tenant_id, actor_id, section, cleaned)
        return Ok(cleaned)

    def _audit(self, tenant_id: str, actor_id: str, section: str, entries: list[dict]) -> None:
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="dashboard_settings.replaced",
            entity_type="dashboard_settings",
            entity_id=section,
            payload={"section": section, "entries": entries},
        )
