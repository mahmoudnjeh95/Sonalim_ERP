"""What each shift report section stores, and how a save reaches the database.

The nine sections differ only in their tables and columns, so they are described
as data (`SECTIONS`) and one small engine loads, validates and syncs them. Adding a
section later is a new entry here plus its key in `domain/shift_report.py`.

A save is *validate everything, then write*: nothing is written when any row is
refused, so a caller that gets an `Err` has changed nothing.

Rows are synced by id, not replaced wholesale: a run that is edited keeps its id,
and with it the waste and packing rows pointing at it and the stock posted under
that id. An id the client sends is trusted only when it already belongs to the same
shift; anything else is treated as a new row.
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import psycopg
from ulid import ULID

from core.api.service import CoreService
from core.domain.result import Err, Ok, Result
from modules.production.api.packing_derivation_service import derive_packing_rows, derive_waste_cartons
from modules.production.domain.shift_report import split_proportionally
from modules.production.domain.production_report import (
    ConditionnementReportDetail,
    DailyReportDetail,
    DowntimeLine,
    SemolinaLine,
    WasteLine,
    validate_conditionnement_stock_targets,
    validate_daily_stock_targets,
    validate_downtime_lines,
    validate_waste_lines,
)

# Work orders that still take reports; the same rule the old report flow uses.
_OF_STATUSES_ACCEPTING_REPORTS = {"planned", "ongoing", "suspended"}


@dataclass(frozen=True)
class Col:
    """One column of a section table.

    `default` is what a missing value becomes for a NOT NULL column; `None` means the
    column is nullable and a missing value is stored as NULL.
    """

    name: str
    kind: str = "text"  # text | num | int | date | time | ts | of | run_ref | packing_ref
    required: bool = False
    default: Any = None


@dataclass(frozen=True)
class ChildSet:
    """Rows hanging off a parent row (semoule lines under a run)."""

    table: str
    payload_key: str
    parent_column: str
    columns: tuple[Col, ...]


@dataclass(frozen=True)
class RowSet:
    """A list of rows in one table, scoped to the shift (and optionally a fixed column value)."""

    table: str
    payload_key: str
    columns: tuple[Col, ...]
    scope: dict[str, str] = field(default_factory=dict)
    children: tuple[ChildSet, ...] = ()
    order_by: str = "line_order, id"
    has_line_order: bool = True


@dataclass(frozen=True)
class Single:
    """One row per shift (energy, staffing), keyed by the shift's id."""

    table: str
    payload_key: str
    columns: tuple[Col, ...]
    has_updated_at: bool = False


Part = RowSet | Single


def _num(name: str, default: float | None = 0) -> Col:
    return Col(name, "num", default=default)


def _int(name: str, default: int | None = 0) -> Col:
    return Col(name, "int", default=default)


def _text(*names: str) -> tuple[Col, ...]:
    return tuple(Col(n) for n in names)


_SEMOLINA = ChildSet(
    table="shift_run_semolina_lines",
    payload_key="semolina_lines",
    parent_column="run_id",
    columns=(Col("product_id"), _num("quantity"), Col("location_id"), _num("bag_count", None), Col("lot_number")),
)

_RUNS = RowSet(
    table="shift_runs",
    payload_key="runs",
    children=(_SEMOLINA,),
    columns=(
        Col("of_id", "of", required=True),
        *_text("equipment_id", "mold_id", "lot_number"),
        Col("start_time", "time"),
        Col("end_time", "time"),
        _int("production_minutes"),
        _num("dough_quantity"),
        _num("finished_product_quantity"),
        _num("regrind_quantity"),
        _num("regrind_input_quantity"),
        *_text("regrind_input_product_id", "regrind_product_id", "raw_material_location_id"),
        _num("water_quantity"),
        _num("water_percentage"),
        _num("humidity_percentage", None),
        _num("semolina_flow_rate"),
        Col("shortfall_comment"),
    ),
)

# Raw material poured into the line, recorded once per shift rather than per run.
_VERSEMENTS = RowSet(
    table="shift_versements",
    payload_key="versements",
    columns=(Col("product_id"), Col("location_id"), _num("quantity")),
)

# Regrind material (already reground) poured back into the line, recorded once per shift.
_REBROYAT_VERSEMENTS = RowSet(
    table="shift_rebroyat_versements",
    payload_key="rebroyat_versements",
    columns=(Col("product_id"), Col("location_id"), _num("quantity")),
)


def _waste(section_key: str) -> RowSet:
    return RowSet(
        table="shift_waste_lines",
        payload_key="waste_lines",
        scope={"section_key": section_key},
        columns=(
            Col("category", required=True),
            Col("product_id"),
            _num("quantity"),
            Col("note"),
            Col("occurred_at", "ts"),
            Col("lot_number"),
            Col("run_id", "run_ref"),
            Col("packing_row_id", "packing_ref"),
        ),
    )


_MOLD_WASHES = RowSet(
    table="shift_mold_washes",
    payload_key="mold_washes",
    columns=(Col("mold_id"), Col("washed_at", "ts"), Col("state")),
)

_STOPS = RowSet(
    table="machine_stops",
    payload_key="stops",
    columns=(
        Col("equipment_id"),
        Col("run_id", "run_ref"),
        Col("packing_row_id", "packing_ref"),
        Col("started_at", "ts", required=True),
        Col("ended_at", "ts"),
        *_text("downtime_type", "classification", "motif", "note", "corrective_action"),
    ),
)

_SILO = RowSet(
    table="shift_silo_states",
    payload_key="states",
    order_by="side, phase",
    has_line_order=False,
    columns=(
        Col("side", required=True),
        Col("phase", required=True),
        Col("format"),
        Col("lot_number"),
        _num("level_percent", None),
        Col("line_state"),
    ),
)

_STAFFING = Single(
    table="shift_staffing",
    payload_key="staffing",
    columns=(_int("control_room", None), _int("petrin", None), _int("semoule", None), _int("broyage", None)),
)

_PACKING = RowSet(
    table="shift_packing_rows",
    payload_key="rows",
    columns=(
        Col("of_id", "of"),
        Col("run_id", "run_ref"),
        Col("product_id"),
        *_text("equipment_id", "packing_type", "film_type"),
        _num("finished_product_quantity"),
        _num("packets_counted"),
        _num("film_quantity"),
        _num("carton_quantity"),
        _num("tape_quantity"),
        _num("scotch_quantity"),
        _num("ruban_quantity"),
        _num("waste_carton_quantity"),
        _num("machine_speed", None),
        _int("production_minutes"),
        _int("downtime_minutes"),
        *_text("downtime_reason", "downtime_note", "lot_number"),
        Col("dlc_date", "date"),
        *_text(
            "film_product_id", "carton_product_id", "tape_product_id", "scotch_product_id", "ruban_product_id",
            "film_supplier_id", "carton_supplier_id", "tape_supplier_id", "scotch_supplier_id", "ruban_supplier_id",
            "packaging_location_id", "film_location_id", "carton_location_id", "scotch_location_id", "ruban_location_id",
            "finished_goods_location_id",
        ),
        _num("snapshot_net_weight_grams", None),
        _num("snapshot_packets_per_carton", None),
        Col("shortfall_comment"),
    ),
)

_PACKET_CHECKS = RowSet(
    table="shift_packet_checks",
    payload_key="checks",
    columns=(
        Col("checked_at", "ts"),
        Col("film_state"),
        _num("packet_weight_grams", None),
        *_text("long_weld", "vertical_weld", "date_print", "note"),
    ),
)

_ENERGY = Single(
    table="shift_energy",
    payload_key="energy",
    has_updated_at=True,
    columns=(
        _num("fuel_quantity"),
        Col("fuel_supplier_id"),
        _num("gasoil_quantity"),
        Col("gasoil_supplier_id"),
        _num("gasoil_flow_rate"),
        _num("generator_hours"),
        _num("electricity_quantity"),
    ),
)

# Section key -> its parts. A part missing from a payload is left untouched; a part
# present (even empty) replaces what was stored, so one part can be saved alone.
SECTIONS: dict[str, tuple[Part, ...]] = {
    "runs": (_RUNS, _VERSEMENTS, _REBROYAT_VERSEMENTS),
    "waste_production": (_waste("waste_production"), _MOLD_WASHES),
    "stops": (_STOPS,),
    "silo": (_SILO,),
    "staffing": (_STAFFING,),
    "packing": (_PACKING,),
    "packet_checks": (_PACKET_CHECKS,),
    "waste_packing": (_waste("waste_packing"),),
    "energy": (_ENERGY,),
}

# Which report type's waste categories a waste section is checked against.
_WASTE_REPORT_TYPE = {"waste_production": "daily", "waste_packing": "conditionnement"}

_SILO_SIDES = ("production", "packing")
_SILO_PHASES = ("start", "end")


def _bad(message: str, message_fr: str) -> Err:
    return Err("INVALID_VALUE", message, message_fr)


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        return value.isoformat()
    return value


def _coerce(col: Col, value: Any, where: str, where_fr: str | None = None) -> Result[Any]:
    """One cell: blank becomes the column's default, anything else is parsed and range-checked."""
    where_fr = where_fr if where_fr is not None else where
    if value is None or (isinstance(value, str) and not value.strip()):
        if col.required:
            return _bad(f"{where}: {col.name} is required", f"{where_fr} : {col.name} est obligatoire")
        return Ok(col.default)
    try:
        if col.kind in ("num", "int"):
            number = float(value) if col.kind == "num" else int(value)
            if number < 0:
                return _bad(f"{where}: {col.name} cannot be negative", f"{where_fr} : {col.name} ne peut pas être négatif")
            return Ok(number)
        if col.kind == "date":
            return Ok(value if isinstance(value, datetime.date) else datetime.date.fromisoformat(str(value)))
        if col.kind == "time":
            return Ok(value if isinstance(value, datetime.time) else datetime.time.fromisoformat(str(value)))
        if col.kind == "ts":
            if isinstance(value, datetime.datetime):
                return Ok(value)
            return Ok(datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00")))
    except (TypeError, ValueError):
        return _bad(f"{where}: {col.name} is not a valid {col.kind}", f"{where_fr} : {col.name} n'est pas un {col.kind} valide")
    text = str(value).strip()
    return Ok(text)


def _clean_rows(part: RowSet | ChildSet, rows: Any, label: str) -> Result[list[dict]]:
    if not isinstance(rows, list):
        return _bad(f"{label} must be a list", f"{label} doit être une liste")
    cleaned: list[dict] = []
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            return _bad(f"{label} row {index} must be an object", f"{label} ligne {index} doit être un objet")
        out: dict[str, Any] = {"_id": str(row["id"]) if row.get("id") else None}
        for col in part.columns:
            result = _coerce(col, row.get(col.name), f"{label} row {index}", f"{label} ligne {index}")
            if isinstance(result, Err):
                return result
            out[col.name] = result.value
        if isinstance(part, RowSet):
            out["_children"] = {}
            for child in part.children:
                if child.payload_key in row:
                    kids = _clean_rows(child, row[child.payload_key], f"{label} row {index} {child.payload_key}")
                    if isinstance(kids, Err):
                        return kids
                    out["_children"][child.payload_key] = kids.value
        cleaned.append(out)
    return Ok(cleaned)


def _clean_single(part: Single, value: Any, label: str) -> Result[dict | None]:
    if value is None:
        return Ok(None)
    if not isinstance(value, dict):
        return _bad(f"{label} must be an object", f"{label} doit être un objet")
    out: dict[str, Any] = {}
    for col in part.columns:
        result = _coerce(col, value.get(col.name), label)
        if isinstance(result, Err):
            return result
        out[col.name] = result.value
    given = any(value.get(col.name) not in (None, "") for col in part.columns)
    return Ok(out if given else None)


# ---- loading ---------------------------------------------------------------


def _select(connection: psycopg.Connection, sql: str, params: tuple) -> list[dict]:
    cursor = connection.execute(sql, params)
    names = [d.name for d in cursor.description]
    return [{n: _jsonable(v) for n, v in zip(names, row)} for row in cursor.fetchall()]


def _load_rowset(connection: psycopg.Connection, tenant_id: str, shift_id: str, part: RowSet) -> list[dict]:
    cols = ", ".join(("id", *(c.name for c in part.columns)))
    where = "tenant_id = %s AND shift_report_id = %s" + "".join(f" AND {k} = %s" for k in part.scope)
    if part.table == "machine_stops":
        cols += ", source"
    rows = _select(
        connection,
        f"SELECT {cols} FROM production.{part.table} WHERE {where} ORDER BY {part.order_by}",
        (tenant_id, shift_id, *part.scope.values()),
    )
    for child in part.children:
        ids = [r["id"] for r in rows]
        kids = (
            _select(
                connection,
                f"SELECT id, {child.parent_column}, {', '.join(c.name for c in child.columns)} "
                f"FROM production.{child.table} WHERE tenant_id = %s AND {child.parent_column} = ANY(%s) "
                f"ORDER BY line_order, id",
                (tenant_id, ids),
            )
            if ids
            else []
        )
        for row in rows:
            row[child.payload_key] = [
                {k: v for k, v in kid.items() if k != child.parent_column} for kid in kids if kid[child.parent_column] == row["id"]
            ]
    return rows


def _load_single(connection: psycopg.Connection, tenant_id: str, shift_id: str, part: Single) -> dict | None:
    rows = _select(
        connection,
        f"SELECT {', '.join(c.name for c in part.columns)} FROM production.{part.table} "
        f"WHERE tenant_id = %s AND shift_report_id = %s",
        (tenant_id, shift_id),
    )
    return rows[0] if rows else None


def load_section(connection: psycopg.Connection, *, tenant_id: str, shift_report_id: str, section_key: str) -> dict:
    """A section's stored rows as a JSON-safe payload, in the shape `save_section_rows` accepts."""
    payload: dict[str, Any] = {}
    for part in SECTIONS[section_key]:
        if isinstance(part, Single):
            payload[part.payload_key] = _load_single(connection, tenant_id, shift_report_id, part)
        else:
            payload[part.payload_key] = _load_rowset(connection, tenant_id, shift_report_id, part)
    return payload


def section_is_empty(payload: dict) -> bool:
    return all(not value for value in payload.values())


# ---- validation across rows ------------------------------------------------


def _validate_shift_references(
    connection: psycopg.Connection, tenant_id: str, shift_id: str, part: RowSet, rows: list[dict]
) -> Result[None]:
    """A run or packing row a line points at must be on this shift."""
    for col in part.columns:
        if col.kind not in ("run_ref", "packing_ref"):
            continue
        table = "shift_runs" if col.kind == "run_ref" else "shift_packing_rows"
        wanted = {r[col.name] for r in rows if r[col.name]}
        if not wanted:
            continue
        found = {
            r[0]
            for r in connection.execute(
                f"SELECT id FROM production.{table} WHERE tenant_id = %s AND shift_report_id = %s AND id = ANY(%s)",
                (tenant_id, shift_id, list(wanted)),
            ).fetchall()
        }
        if wanted - found:
            return _bad(f"{part.payload_key}: {col.name} does not belong to this shift", f"{part.payload_key} : {col.name} n'appartient pas à ce shift")
    return Ok(None)


def _validate_orders(
    connection: psycopg.Connection, tenant_id: str, shift_id: str, part: RowSet, rows: list[dict]
) -> Result[None]:
    """New or changed work orders must still accept reports; untouched ones may be corrected after closure."""
    kept = {
        r[0]: r[1]
        for r in connection.execute(
            f"SELECT id, of_id FROM production.{part.table} WHERE tenant_id = %s AND shift_report_id = %s",
            (tenant_id, shift_id),
        ).fetchall()
    }
    wanted = {r["of_id"] for r in rows if r["_id"] is None or kept.get(r["_id"]) != r["of_id"]}
    if not wanted:
        return Ok(None)
    statuses = dict(
        connection.execute(
            "SELECT id, status FROM production.work_orders WHERE tenant_id = %s AND id = ANY(%s)",
            (tenant_id, list(wanted)),
        ).fetchall()
    )
    for of_id in sorted(wanted):
        if of_id not in statuses:
            return Err("NOT_FOUND", f"work order {of_id} not found", f"OF {of_id} introuvable")
        if statuses[of_id] not in _OF_STATUSES_ACCEPTING_REPORTS:
            return Err(
                "OF_NOT_OPEN",
                f"work order {of_id} is {statuses[of_id]} and accepts no new rows",
                f"l'OF {of_id} est {statuses[of_id]} et n'accepte plus de nouvelles lignes",
            )
    return Ok(None)


def _validate_shift_waste(
    connection: psycopg.Connection, tenant_id: str, section_key: str, rows: list[dict]
) -> Result[None]:
    """One place per loss.

    Finished product lost while packing is filed on the packing side as `product`; the
    old Daily form's `finished_product_conditioning` would be a second place for the same
    kilos, counted twice in the sheet's total. A packaging line is in its item's own unit
    (film in kg, a carton, scotch or ruban in pieces); the sheet keeps counted items out
    of the kilo total.
    """
    if section_key == "waste_production":
        for index, row in enumerate(rows, start=1):
            if row["category"] == "finished_product_conditioning":
                return _bad(
                    f"waste {index}: finished product lost while packing is recorded under packing waste, as Product",
                    f"déchet {index} : le produit perdu au conditionnement se saisit dans les déchets de conditionnement, en Produit",
                )
    return Ok(None)


def _validate_part(
    connection: psycopg.Connection,
    tenant_id: str,
    shift_id: str,
    section_key: str,
    part: RowSet,
    rows: list[dict],
    custom_waste_categories: dict[str, frozenset[str]],
) -> Result[None]:
    references = _validate_shift_references(connection, tenant_id, shift_id, part, rows)
    if isinstance(references, Err):
        return references
    if any(c.kind == "of" for c in part.columns):
        orders = _validate_orders(connection, tenant_id, shift_id, part, rows)
        if isinstance(orders, Err):
            return orders

    if part.table == "shift_waste_lines":
        report_type = _WASTE_REPORT_TYPE[section_key]
        checked = validate_waste_lines(
            tuple(WasteLine(category=r["category"], quantity=r["quantity"]) for r in rows),
            report_type=report_type,
            custom_categories=custom_waste_categories.get(report_type, frozenset()),
        )
        if isinstance(checked, Err):
            return checked
        return _validate_shift_waste(connection, tenant_id, section_key, rows)
    if part.table == "machine_stops":
        for index, row in enumerate(rows, start=1):
            if row["ended_at"] is not None and row["ended_at"] < row["started_at"]:
                return _bad(f"stop {index}: it ends before it starts", f"arrêt {index} : il se termine avant de commencer")
        return validate_downtime_lines(tuple(DowntimeLine(motif=r["motif"], minutes=0) for r in rows))
    if part.table == "shift_silo_states":
        seen: set[tuple[str, str]] = set()
        for index, row in enumerate(rows, start=1):
            if row["side"] not in _SILO_SIDES or row["phase"] not in _SILO_PHASES:
                return _bad(
                    f"silo row {index}: side must be one of {_SILO_SIDES} and phase one of {_SILO_PHASES}",
                    f"ligne silo {index} : side doit être l'un de {_SILO_SIDES} et phase l'une de {_SILO_PHASES}",
                )
            if row["level_percent"] is not None and row["level_percent"] > 100:
                return _bad(f"silo row {index}: level_percent cannot exceed 100", f"ligne silo {index} : level_percent ne peut pas dépasser 100")
            key = (row["side"], row["phase"])
            if key in seen:
                return Err("DUPLICATE_ROW", f"silo state for {key[0]} / {key[1]} is listed twice", f"l'état du silo pour {key[0]} / {key[1]} est listé deux fois")
            seen.add(key)
    if part.table == "shift_packing_rows":
        for index, row in enumerate(rows, start=1):
            if row["dlc_date"] is not None and not row["lot_number"]:
                return Err(
                    "INCOMPLETE_DLC",
                    f"packing row {index}: a DLC needs the lot it belongs to",
                    f"ligne de conditionnement {index} : une DLC a besoin du lot auquel elle appartient",
                )
    return Ok(None)


# ---- writing ---------------------------------------------------------------


def _existing_ids(connection: psycopg.Connection, tenant_id: str, shift_id: str, part: RowSet) -> set[str]:
    where = "tenant_id = %s AND shift_report_id = %s" + "".join(f" AND {k} = %s" for k in part.scope)
    rows = connection.execute(
        f"SELECT id FROM production.{part.table} WHERE {where}", (tenant_id, shift_id, *part.scope.values())
    ).fetchall()
    return {r[0] for r in rows}


def _sync_children(
    connection: psycopg.Connection, tenant_id: str, parent_id: str, child: ChildSet, rows: list[dict]
) -> None:
    existing = {
        r[0]
        for r in connection.execute(
            f"SELECT id FROM production.{child.table} WHERE tenant_id = %s AND {child.parent_column} = %s",
            (tenant_id, parent_id),
        ).fetchall()
    }
    keep: list[str] = []
    names = [c.name for c in child.columns]
    for order, row in enumerate(rows):
        row_id = row["_id"] if row["_id"] in existing else str(ULID())
        keep.append(row_id)
        values = [row[n] for n in names]
        if row_id in existing:
            connection.execute(
                f"UPDATE production.{child.table} SET {', '.join(f'{n} = %s' for n in names)}, line_order = %s "
                f"WHERE id = %s AND tenant_id = %s",
                (*values, order, row_id, tenant_id),
            )
        else:
            connection.execute(
                f"INSERT INTO production.{child.table} (id, tenant_id, {child.parent_column}, {', '.join(names)}, line_order) "
                f"VALUES (%s, %s, %s, {', '.join(['%s'] * len(names))}, %s)",
                (row_id, tenant_id, parent_id, *values, order),
            )
    connection.execute(
        f"DELETE FROM production.{child.table} WHERE tenant_id = %s AND {child.parent_column} = %s AND id <> ALL(%s::text[])",
        (tenant_id, parent_id, keep),
    )


def _sync_rowset(
    connection: psycopg.Connection, tenant_id: str, shift_id: str, part: RowSet, rows: list[dict]
) -> None:
    existing = _existing_ids(connection, tenant_id, shift_id, part)
    keep: list[str] = []
    names = [c.name for c in part.columns]
    scope_names = list(part.scope)
    for order, row in enumerate(rows):
        row_id = row["_id"] if row["_id"] in existing else str(ULID())
        keep.append(row_id)
        values = [row[n] for n in names]
        if row_id in existing:
            assignments = ", ".join(f"{n} = %s" for n in names)
            if part.has_line_order:
                assignments += ", line_order = %s"
            connection.execute(
                f"UPDATE production.{part.table} SET {assignments} WHERE id = %s AND tenant_id = %s AND shift_report_id = %s",
                (*values, *((order,) if part.has_line_order else ()), row_id, tenant_id, shift_id),
            )
        else:
            insert_cols = ["id", "tenant_id", "shift_report_id", *scope_names, *names]
            insert_values = [row_id, tenant_id, shift_id, *part.scope.values(), *values]
            if part.has_line_order:
                insert_cols.append("line_order")
                insert_values.append(order)
            connection.execute(
                f"INSERT INTO production.{part.table} ({', '.join(insert_cols)}) "
                f"VALUES ({', '.join(['%s'] * len(insert_cols))})",
                tuple(insert_values),
            )
        for child in part.children:
            if child.payload_key in row["_children"]:
                _sync_children(connection, tenant_id, row_id, child, row["_children"][child.payload_key])
    where = "tenant_id = %s AND shift_report_id = %s" + "".join(f" AND {k} = %s" for k in scope_names)
    connection.execute(
        f"DELETE FROM production.{part.table} WHERE {where} AND id <> ALL(%s::text[])",
        (tenant_id, shift_id, *part.scope.values(), keep),
    )


def _sync_single(connection: psycopg.Connection, tenant_id: str, shift_id: str, part: Single, row: dict | None) -> None:
    if row is None:
        connection.execute(
            f"DELETE FROM production.{part.table} WHERE tenant_id = %s AND shift_report_id = %s", (tenant_id, shift_id)
        )
        return
    names = [c.name for c in part.columns]
    updates = ", ".join(f"{n} = EXCLUDED.{n}" for n in names) + (", updated_at = NOW()" if part.has_updated_at else "")
    connection.execute(
        f"INSERT INTO production.{part.table} (shift_report_id, tenant_id, {', '.join(names)}) "
        f"VALUES (%s, %s, {', '.join(['%s'] * len(names))}) "
        f"ON CONFLICT (shift_report_id) DO UPDATE SET {updates}",
        (shift_id, tenant_id, *(row[n] for n in names)),
    )


def _derive_versement_locations(connection: psycopg.Connection, *, tenant_id: str, rows: list[dict]) -> None:
    """A versement names no store: it comes from its raw material's own default store."""
    core = CoreService(connection)
    for row in rows:
        if not row["location_id"] and row["product_id"]:
            product = core.get_product(tenant_id, row["product_id"])
            if product is not None:
                row["location_id"] = product.default_location_id


def _derive_run_inputs(connection: psycopg.Connection, *, tenant_id: str, shift_id: str) -> None:
    """What each run took in, worked out from the shift's versements; the team no longer types it.

    The versements are recorded once for the shift, so their totals are shared across
    the runs by production minutes, as the energy is, each product on its own. A run's
    semoule lines are its share of each MP versé, drawn from that MP's store; its
    rebroyat used is its share of the rebroyat; its dough is the two together. These
    are the figures stock posting and every run-level analysis already read.
    """
    runs = connection.execute(
        "SELECT id, production_minutes FROM production.shift_runs WHERE tenant_id = %s AND shift_report_id = %s "
        "ORDER BY line_order, id",
        (tenant_id, shift_id),
    ).fetchall()
    if not runs:
        return
    # One entry per MP, in the order the team first listed it.
    mp = [
        (product_id, location_id, float(quantity))
        for product_id, location_id, quantity in connection.execute(
            "SELECT product_id, MIN(location_id), SUM(quantity) FROM production.shift_versements "
            "WHERE tenant_id = %s AND shift_report_id = %s AND quantity > 0 AND product_id IS NOT NULL "
            "GROUP BY product_id ORDER BY MIN(line_order), product_id",
            (tenant_id, shift_id),
        ).fetchall()
    ]
    mp_total = sum(quantity for _, _, quantity in mp)
    rebroyat = connection.execute(
        "SELECT product_id, MIN(location_id), SUM(quantity) FROM production.shift_rebroyat_versements "
        "WHERE tenant_id = %s AND shift_report_id = %s AND quantity > 0 GROUP BY product_id ORDER BY product_id",
        (tenant_id, shift_id),
    ).fetchone()
    rebroyat_product, rebroyat_location, rebroyat_total = (
        (rebroyat[0], rebroyat[1], float(rebroyat[2])) if rebroyat else (None, None, 0.0)
    )
    weights = [float(minutes or 0) for _, minutes in runs]
    doughs = split_proportionally(mp_total + rebroyat_total, weights)
    regrinds = split_proportionally(rebroyat_total, weights)
    mp_shares = [split_proportionally(quantity, weights) for _, _, quantity in mp]
    for index, ((run_id, _), dough, regrind) in enumerate(zip(runs, doughs, regrinds)):
        connection.execute(
            "DELETE FROM production.shift_run_semolina_lines WHERE tenant_id = %s AND run_id = %s", (tenant_id, run_id)
        )
        lines = [(product_id, location_id, shares[index]) for (product_id, location_id, _), shares in zip(mp, mp_shares)]
        for order, (product_id, location_id, quantity) in enumerate(line for line in lines if line[2] > 0):
            connection.execute(
                "INSERT INTO production.shift_run_semolina_lines (id, tenant_id, run_id, product_id, quantity, location_id, line_order) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (str(ULID()), tenant_id, run_id, product_id, quantity, location_id, order),
            )
        used = regrind > 0
        connection.execute(
            "UPDATE production.shift_runs SET dough_quantity = %s, regrind_input_quantity = %s, "
            "regrind_input_product_id = %s, raw_material_location_id = %s WHERE id = %s AND tenant_id = %s",
            (dough, regrind, rebroyat_product if used else None, rebroyat_location if used else None, run_id, tenant_id),
        )


def _validate_single_rebroyat(rows: list[dict]) -> Result[None]:
    """A run records one rebroyat item, so a shift's rebroyat versements must all name the same one."""
    products = {r["product_id"] for r in rows if r["product_id"] and (r["quantity"] or 0) > 0}
    if len(products) > 1:
        return Err(
            "MIXED_REBROYAT",
            "rebroyat versements: every row must name the same rebroyat item",
            "rebroyat versé : toutes les lignes doivent nommer le même article rebroyat",
        )
    return Ok(None)


def save_section_rows(
    connection: psycopg.Connection,
    *,
    tenant_id: str,
    shift_report_id: str,
    section_key: str,
    payload: dict,
    custom_waste_categories: dict[str, frozenset[str]] | None = None,
) -> Result[None]:
    """Validate the payload's parts, then sync each one. Nothing is written unless all validate."""
    custom = custom_waste_categories or {}
    staged: list[tuple[Part, Any]] = []
    for part in SECTIONS[section_key]:
        if part.payload_key not in payload:
            continue
        if isinstance(part, Single):
            single = _clean_single(part, payload[part.payload_key], part.payload_key)
            if isinstance(single, Err):
                return single
            staged.append((part, single.value))
        else:
            rows = _clean_rows(part, payload[part.payload_key], part.payload_key)
            if isinstance(rows, Err):
                return rows
            if part.table == "shift_packing_rows":
                derived = derive_packing_rows(connection, tenant_id=tenant_id, shift_id=shift_report_id, rows=rows.value)
                if isinstance(derived, Err):
                    return derived
            if part.table in ("shift_versements", "shift_rebroyat_versements"):
                _derive_versement_locations(connection, tenant_id=tenant_id, rows=rows.value)
            if part.table == "shift_rebroyat_versements":
                single = _validate_single_rebroyat(rows.value)
                if isinstance(single, Err):
                    return single
            checked = _validate_part(connection, tenant_id, shift_report_id, section_key, part, rows.value, custom)
            if isinstance(checked, Err):
                return checked
            staged.append((part, rows.value))
    for part, value in staged:
        if isinstance(part, Single):
            _sync_single(connection, tenant_id, shift_report_id, part, value)
        else:
            _sync_rowset(connection, tenant_id, shift_report_id, part, value)
    if section_key == "runs":
        _derive_run_inputs(connection, tenant_id=tenant_id, shift_id=shift_report_id)
    if section_key in ("packing", "waste_packing"):
        derive_waste_cartons(connection, tenant_id=tenant_id, shift_id=shift_report_id)
    return Ok(None)


def clear_section_rows(connection: psycopg.Connection, *, tenant_id: str, shift_report_id: str, section_key: str) -> None:
    """Empty every part of a section ("nothing to report")."""
    empty = {p.payload_key: (None if isinstance(p, Single) else []) for p in SECTIONS[section_key]}
    save_section_rows(connection, tenant_id=tenant_id, shift_report_id=shift_report_id, section_key=section_key, payload=empty)


def _wrap_run_check(index: int, checked: Err) -> Err:
    return Err(checked.code, f"run {index}: {checked.message}",
               f"passage {index} : {checked.message_fr or checked.message}")


def _wrap_packing_check(index: int, checked: Err) -> Err:
    return Err(checked.code, f"packing row {index}: {checked.message}",
               f"ligne de conditionnement {index} : {checked.message_fr or checked.message}")


def check_ready_to_submit(section_key: str, payload: dict) -> Result[None]:
    """The completeness the old flow demanded when a report left the team.

    A team may save a half-typed draft, so none of this is checked on save. It is
    checked when the section is submitted, exactly as a report used to be checked
    on submit: a figure that will move stock must say which item and which store,
    and a lost quantity must say what was lost. Better here, at the team's
    screen, than as a refusal at the validation desk.
    """
    if section_key == "runs":
        for key, name, name_fr in (("versements", "versement", "versement"), ("rebroyat_versements", "rebroyat", "rebroyat")):
            for index, row in enumerate(payload.get(key) or [], start=1):
                if float(row.get("quantity") or 0) > 0 and row.get("product_id") and not row.get("location_id"):
                    return Err(
                        "MISSING_STOCK_TARGET",
                        f"{name} row {index}: the item has no default store; set one on the item, then save the section again",
                        f"ligne {name_fr} {index} : l'article n'a pas de magasin par défaut ; "
                        "définissez-en un sur l'article, puis enregistrez à nouveau la section",
                    )
        for index, run in enumerate(payload.get("runs") or [], start=1):
            detail = DailyReportDetail(
                semolina_lines=tuple(
                    SemolinaLine(
                        product_id=line.get("product_id"),
                        quantity=float(line.get("quantity") or 0),
                        location_id=line.get("location_id"),
                    )
                    for line in run.get("semolina_lines") or []
                ),
                regrind_input_quantity=float(run.get("regrind_input_quantity") or 0),
                regrind_input_product_id=run.get("regrind_input_product_id"),
                raw_material_location_id=run.get("raw_material_location_id"),
            )
            checked = validate_daily_stock_targets(detail)
            if isinstance(checked, Err):
                return _wrap_run_check(index, checked)
    elif section_key in _WASTE_REPORT_TYPE:
        # The shift's waste lines track a quantity per kind; the form has no product column and
        # nothing is posted to stock from them, so a line need not name what was lost.
        return Ok(None)
    elif section_key == "packing":
        for index, row in enumerate(payload.get("rows") or [], start=1):
            if not row.get("product_id"):
                return Err(
                    "PRODUCT_REQUIRED",
                    f"packing row {index}: pick the product this lot is made of",
                    f"ligne de conditionnement {index} : choisissez le produit dont ce lot est fait",
                )
            if float(row.get("packets_counted") or 0) > 0 and not row.get("finished_goods_location_id"):
                return Err(
                    "NO_DEFAULT_LOCATION",
                    f"packing row {index}: the product has no default storage location; set one on the product, then save the section again",
                    f"ligne de conditionnement {index} : le produit n'a pas d'emplacement de stockage par défaut ; "
                    "définissez-en un sur le produit, puis enregistrez à nouveau la section",
                )
            # Each packaging item posts from its own default store; a row with several items
            # no longer needs them to share one (see packing_derivation_service).
            for quantity_key, location_key in (
                ("film_quantity", "film_location_id"),
                ("carton_quantity", "carton_location_id"),
                ("scotch_quantity", "scotch_location_id"),
                ("ruban_quantity", "ruban_location_id"),
            ):
                if float(row.get(quantity_key) or 0) > 0 and not (row.get(location_key) or row.get("packaging_location_id")):
                    return Err(
                        "NO_DEFAULT_LOCATION",
                        f"packing row {index}: a packaging item has no default storage location; set one on the item, then save the section again",
                        f"ligne de conditionnement {index} : un article d'emballage n'a pas d'emplacement de stockage par défaut ; "
                        "définissez-en un sur l'article, puis enregistrez à nouveau la section",
                    )
            detail = ConditionnementReportDetail(
                packets_counted=float(row.get("packets_counted") or 0),
                film_quantity=float(row.get("film_quantity") or 0),
                carton_quantity=float(row.get("carton_quantity") or 0),
                scotch_quantity=float(row.get("scotch_quantity") or 0),
                ruban_quantity=float(row.get("ruban_quantity") or 0),
                film_product_id=row.get("film_product_id"),
                carton_product_id=row.get("carton_product_id"),
                scotch_product_id=row.get("scotch_product_id"),
                ruban_product_id=row.get("ruban_product_id"),
                packaging_location_id=row.get("packaging_location_id"),
                film_location_id=row.get("film_location_id"),
                carton_location_id=row.get("carton_location_id"),
                scotch_location_id=row.get("scotch_location_id"),
                ruban_location_id=row.get("ruban_location_id"),
                finished_goods_location_id=row.get("finished_goods_location_id"),
            )
            checked = validate_conditionnement_stock_targets(detail)
            if isinstance(checked, Err):
                return _wrap_packing_check(index, checked)
    return Ok(None)
