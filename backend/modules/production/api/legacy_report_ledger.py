"""Old-shaped report rows for a shift, so validation can reuse the existing stock rules.

Everything that posts stock, opens a regrind order, registers a lot or judges a
packaging variance is keyed on the old report id and reads `production_reports` and
its detail tables. A run or packing row of a shift report *has that same id*, so
validating a shift starts by writing those old-shaped rows (as `submitted`) from the
shift's own tables, then handing each to the existing `validate_report`.

This is deliberately transitional. Once the old tables become views over the shift
tables, the rows this module writes are the shift's own rows and this module goes
away; what validation does does not change.

Nothing here commits. It runs inside the caller's savepoint.
"""
from __future__ import annotations

import datetime

import psycopg
from ulid import ULID

from core.api.service import CoreService
from core.domain.result import Err, Ok, Result
from modules.maintenance.api.equipment_service import EquipmentService
from modules.production.api.dashboard_settings_service import DashboardSettingsService
from modules.production.domain.line_machines import pick_stage_machine
from modules.production.domain.shift_report import split_proportionally

# Energy columns of the old daily report that are quantities to share across runs.
_SHARED_ENERGY = ("fuel_quantity", "gasoil_quantity", "electricity_quantity", "generator_hours")

_DAILY_COLUMNS = (
    "dough_quantity", "finished_product_quantity", "regrind_quantity", "water_quantity",
    "start_time", "end_time", "production_minutes", "raw_material_location_id", "regrind_input_quantity",
    "regrind_input_product_id", "regrind_product_id", "mold_id", "water_percentage", "semolina_flow_rate",
)
_PACKING_COLUMNS = (
    "finished_product_quantity", "film_quantity", "carton_quantity", "tape_quantity", "machine_speed",
    "production_minutes", "downtime_minutes", "downtime_reason", "lot_number", "dlc_date", "film_product_id",
    "carton_product_id", "tape_product_id", "packaging_location_id", "finished_goods_location_id",
    "packets_counted", "snapshot_net_weight_grams", "snapshot_packets_per_carton", "film_supplier_id",
    "carton_supplier_id", "tape_supplier_id", "downtime_note", "scotch_quantity", "scotch_product_id",
    "scotch_supplier_id", "ruban_quantity", "ruban_product_id", "ruban_supplier_id", "waste_carton_quantity",
)


def _rows(connection: psycopg.Connection, sql: str, params: tuple) -> list[dict]:
    cursor = connection.execute(sql, params)
    names = [d.name for d in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def _delete_old_rows(connection: psycopg.Connection, tenant_id: str, report_ids: list[str]) -> Result[None]:
    """Remove earlier non-validated copies (a rejected or reversed shift is materialised again)."""
    if not report_ids:
        return Ok(None)
    posted = connection.execute(
        "SELECT id FROM production.production_reports WHERE tenant_id = %s AND id = ANY(%s) AND status = 'validated'",
        (tenant_id, report_ids),
    ).fetchone()
    if posted is not None:
        return Err("ALREADY_POSTED", f"report {posted[0]} is already validated and has posted its stock")
    for table in ("report_waste_lines", "report_semolina_lines", "report_downtime_lines"):
        connection.execute(f"DELETE FROM production.{table} WHERE tenant_id = %s AND report_id = ANY(%s)", (tenant_id, report_ids))
    # Packing reports point at their daily report, so they go first.
    connection.execute("DELETE FROM production.conditionnement_reports WHERE tenant_id = %s AND report_id = ANY(%s)", (tenant_id, report_ids))
    connection.execute("DELETE FROM production.daily_reports WHERE tenant_id = %s AND report_id = ANY(%s)", (tenant_id, report_ids))
    connection.execute("DELETE FROM production.report_revisions WHERE tenant_id = %s AND report_id = ANY(%s)", (tenant_id, report_ids))
    connection.execute("DELETE FROM production.production_reports WHERE tenant_id = %s AND id = ANY(%s)", (tenant_id, report_ids))
    return Ok(None)


def _finished_goods_store(connection: psycopg.Connection, tenant_id: str, row: dict, line_store: str | None) -> str | None:
    """Where a packing row's finished goods are posted.

    Packed goods wait in the line store until they are released. A row filled in before the line
    store was set carries the product's own store (the screen filled it in), so an empty store or
    the product's own store is read as "not chosen" and follows the line store. Any other store
    was chosen on purpose and is kept.
    """
    stored = row["finished_goods_location_id"]
    if line_store is None:
        return stored
    if not stored:
        return line_store
    product_id = connection.execute(
        "SELECT product_id FROM production.work_orders WHERE id = %s AND tenant_id = %s", (row["of_id"], tenant_id)
    ).fetchone()
    product = CoreService(connection).get_product(tenant_id, product_id[0]) if product_id and product_id[0] else None
    return line_store if product is not None and stored == product.default_location_id else stored


def _stop_minutes(started: datetime.datetime, ended: datetime.datetime) -> int:
    return int(round((ended - started).total_seconds() / 60))


def materialize_shift(
    connection: psycopg.Connection, *, tenant_id: str, shift_report_id: str, actor_id: str, provisional: bool = False
) -> Result[list[tuple[str, str]]]:
    """Write old-shaped `submitted` reports for the shift; return `[(report_id, report_type)]`, runs first.

    `provisional` is for a caller that only wants to *read* a shift the way validation will (the
    day sheet and the board, inside a savepoint they roll back): a stop that is still ongoing does
    not refuse it, it just has no minutes yet.
    """
    shift = _rows(
        connection,
        "SELECT work_center_id, report_date, shift, team, created_by FROM production.shift_reports "
        "WHERE id = %s AND tenant_id = %s",
        (shift_report_id, tenant_id),
    )[0]
    runs = _rows(
        connection,
        "SELECT * FROM production.shift_runs WHERE shift_report_id = %s AND tenant_id = %s ORDER BY line_order, id",
        (shift_report_id, tenant_id),
    )
    packing = _rows(
        connection,
        "SELECT * FROM production.shift_packing_rows WHERE shift_report_id = %s AND tenant_id = %s ORDER BY line_order, id",
        (shift_report_id, tenant_id),
    )
    if not runs and not packing:
        return Err("NOTHING_TO_VALIDATE", "the shift has no production run and no packing row to validate")

    machines = [
        (machine.id, machine.production_stage, machine.status)
        for machine in EquipmentService(connection).list_equipment(tenant_id=tenant_id, work_center_id=shift["work_center_id"])
    ]
    # Machine performance reads a machine off each report; the screen no longer asks for one,
    # so a report takes the line's machine at the stage it ran on (only when there is exactly one).
    stage_machine = {
        "daily": pick_stage_machine(machines, "extrusion"),
        "conditionnement": pick_stage_machine(machines, "conditionnement"),
    }

    open_stop = connection.execute(
        "SELECT 1 FROM production.machine_stops WHERE shift_report_id = %s AND tenant_id = %s AND ended_at IS NULL LIMIT 1",
        (shift_report_id, tenant_id),
    ).fetchone()
    if open_stop is not None and not provisional:
        return Err("OPEN_STOP", "a machine stop is still ongoing; end it before validating the shift")

    report_ids = [r["id"] for r in runs] + [p["id"] for p in packing]
    cleared = _delete_old_rows(connection, tenant_id, report_ids)
    if isinstance(cleared, Err):
        return cleared

    # ---- headers -----------------------------------------------------------
    for report_type, rows in (("daily", runs), ("conditionnement", packing)):
        for row in rows:
            connection.execute(
                """
                INSERT INTO production.production_reports
                    (id, tenant_id, of_id, report_type, team, work_center_id, report_date, status, revision,
                     created_by, submitted_at, shift, equipment_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, 'submitted', 1, %s, NOW(), %s, %s)
                """,
                (
                    row["id"], tenant_id, row["of_id"], report_type, shift["team"], shift["work_center_id"],
                    shift["report_date"], shift["created_by"] or actor_id, shift["shift"], row["equipment_id"] or stage_machine[report_type],
                ),
            )

    # ---- daily details, with the shift's energy shared by production time ----
    energy = _rows(
        connection,
        "SELECT * FROM production.shift_energy WHERE shift_report_id = %s AND tenant_id = %s",
        (shift_report_id, tenant_id),
    )
    energy_row = energy[0] if energy else {}
    weights = [float(r["production_minutes"]) for r in runs]
    shares = {
        column: split_proportionally(float(energy_row.get(column) or 0), weights) for column in _SHARED_ENERGY
    }
    for index, row in enumerate(runs):
        values = [row[c] for c in _DAILY_COLUMNS]
        connection.execute(
            f"""
            INSERT INTO production.daily_reports
                (report_id, tenant_id, {', '.join(_DAILY_COLUMNS)}, fuel_quantity, gasoil_quantity,
                 electricity_quantity, generator_hours, gasoil_flow_rate, fuel_supplier_id, gasoil_supplier_id)
            VALUES (%s, %s, {', '.join(['%s'] * len(_DAILY_COLUMNS))}, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                row["id"], tenant_id, *values,
                shares["fuel_quantity"][index], shares["gasoil_quantity"][index],
                shares["electricity_quantity"][index], shares["generator_hours"][index],
                float(energy_row.get("gasoil_flow_rate") or 0), energy_row.get("fuel_supplier_id"),
                energy_row.get("gasoil_supplier_id"),
            ),
        )
        for line in _rows(
            connection,
            "SELECT * FROM production.shift_run_semolina_lines WHERE run_id = %s AND tenant_id = %s ORDER BY line_order, id",
            (row["id"], tenant_id),
        ):
            connection.execute(
                "INSERT INTO production.report_semolina_lines (id, tenant_id, report_id, product_id, quantity, location_id, line_order) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (line["id"], tenant_id, row["id"], line["product_id"], line["quantity"], line["location_id"], line["line_order"]),
            )

    # ---- packing details -----------------------------------------------------
    line_store = DashboardSettingsService(connection).line_store_id(tenant_id=tenant_id)
    for row in packing:
        row["finished_goods_location_id"] = _finished_goods_store(connection, tenant_id, row, line_store)
        connection.execute(
            f"""
            INSERT INTO production.conditionnement_reports
                (report_id, tenant_id, daily_report_id, {', '.join(_PACKING_COLUMNS)})
            VALUES (%s, %s, %s, {', '.join(['%s'] * len(_PACKING_COLUMNS))})
            """,
            (row["id"], tenant_id, row["run_id"], *(row[c] for c in _PACKING_COLUMNS)),
        )

    # ---- waste and stops: to the row they name, else the first of their side --
    first_run = runs[0]["id"] if runs else None
    first_packing = packing[0]["id"] if packing else None
    waste = _rows(
        connection,
        "SELECT * FROM production.shift_waste_lines WHERE shift_report_id = %s AND tenant_id = %s ORDER BY line_order, id",
        (shift_report_id, tenant_id),
    )
    for line in waste:
        default = first_run if line["section_key"] == "waste_production" else first_packing
        owner = line["run_id"] or line["packing_row_id"] or default
        if owner is None:
            return Err("INVALID_VALUE", f"a {line['section_key']} line has no report to belong to")
        connection.execute(
            "INSERT INTO production.report_waste_lines (id, tenant_id, report_id, category, product_id, quantity, note, line_order) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (line["id"], tenant_id, owner, line["category"], line["product_id"], line["quantity"], line["note"], line["line_order"]),
        )

    stops = _rows(
        connection,
        "SELECT * FROM production.machine_stops WHERE shift_report_id = %s AND tenant_id = %s ORDER BY started_at, line_order, id",
        (shift_report_id, tenant_id),
    )
    for order, stop in enumerate(stops):
        if stop["ended_at"] is None:
            continue  # only reachable when provisional: an ongoing stop has lost no minutes yet
        owner = stop["run_id"] or stop["packing_row_id"] or first_run or first_packing
        note = " - ".join(part for part in (stop["note"], f"action: {stop['corrective_action']}" if stop["corrective_action"] else None) if part) or None
        connection.execute(
            "INSERT INTO production.report_downtime_lines "
            "(id, tenant_id, report_id, motif, minutes, note, line_order, downtime_type, classification) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                str(ULID()), tenant_id, owner, stop["motif"], _stop_minutes(stop["started_at"], stop["ended_at"]),
                note, order, stop["downtime_type"], stop["classification"],
            ),
        )

    return Ok([(r["id"], "daily") for r in runs] + [(p["id"], "conditionnement") for p in packing])
