from __future__ import annotations

import datetime
from collections.abc import Callable

import psycopg

from core.domain.result import Err, Ok, Result
from modules.production.api.dashboard_settings_service import DashboardSettingsService
from modules.production.api.legacy_report_ledger import materialize_shift
from modules.production.domain.day_sheet import KG_PER_TONNE, DailyFact, PackingFact, build_rows
from modules.production.domain.packaging_estimate import tonnage_from_count

# What a shift's report can be in and still be shown on the sheet. A rejected
# report is on its way back to its team for correction, so it is neither a result
# nor work in progress.
_VALIDATED = ("validated",)
_WITH_PENDING = ("validated", "submitted", "draft")

# A report with no shift filed falls in this column rather than vanishing; so does one
# whose order has no product to name a recap column after.
NO_SHIFT = ""
NO_PRODUCT = ""


class DaySheetService:
    """One line's reports for a day (or any range), laid out as the plant's Excel sheet.

    Validated reports only, unless the caller asks for the ones still being filled
    in as well: a sheet meant as results must not move when a team saves a draft,
    while a sheet meant to check what has been entered so far has to show the
    draft. Either way each column says how many reports of each kind it holds and
    how many are still waiting, so a partial sheet never reads as a complete one.

    Figures are restated into the units the Excel prints before they are added --
    a semoule quality poured in tonnes and rebroyat filed in kilos would otherwise
    be added as if they were the same unit.
    """

    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    # -- reading ------------------------------------------------------------

    def _reports(
        self, tenant_id: str, date_from: datetime.date, date_to: datetime.date, work_center_id: str
    ) -> list[dict]:
        rows = self._connection.execute(
            """
            SELECT r.id, r.report_type, r.shift, r.team, r.status, r.of_id, o.product_id
            FROM production.production_reports r
            LEFT JOIN production.work_orders o ON o.id = r.of_id AND o.tenant_id = r.tenant_id
            WHERE r.tenant_id = %s AND r.report_date BETWEEN %s AND %s
              AND r.work_center_id = %s AND r.status = ANY(%s)
            ORDER BY r.created_at, r.id
            """,
            (tenant_id, date_from, date_to, work_center_id, list(_WITH_PENDING)),
        ).fetchall()
        return [
            {"id": i, "type": kind, "shift": shift, "team": team, "status": state, "of_id": of_id, "of_product_id": product_id}
            for i, kind, shift, team, state, of_id, product_id in rows
        ]

    def _products(self, tenant_id: str, product_ids: set[str]) -> dict[str, dict]:
        """Name, the unit's category and ratio to its base unit (kg, m, ea...), and the packaging."""
        if not product_ids:
            return {}
        rows = self._connection.execute(
            """
            SELECT p.id, p.name, u.category, u.ratio_to_base, p.net_weight_grams, p.packets_per_carton
            FROM core.products p
            LEFT JOIN core.uoms u ON u.id = p.uom_id AND u.tenant_id = p.tenant_id
            WHERE p.tenant_id = %s AND p.id = ANY(%s)
            """,
            (tenant_id, list(product_ids)),
        ).fetchall()
        return {
            i: {
                "name": name,
                "category": category,
                "ratio": float(ratio) if ratio is not None else None,
                "net_weight_grams": float(net_weight) if net_weight is not None else None,
                "packets_per_carton": float(per_carton) if per_carton is not None else None,
            }
            for i, name, category, ratio, net_weight, per_carton in rows
        }

    def _base_units(self, tenant_id: str) -> dict[str, str]:
        """The code of each category's base unit -- the one every ratio_to_base is against."""
        rows = self._connection.execute(
            "SELECT category, MIN(code) FROM core.uoms WHERE tenant_id = %s AND ratio_to_base = 1 GROUP BY category",
            (tenant_id,),
        ).fetchall()
        return dict(rows)

    def _rows_for(self, sql: str, tenant_id: str, report_ids: list[str]) -> list[tuple]:
        if not report_ids:
            return []
        return self._connection.execute(sql, (tenant_id, report_ids)).fetchall()

    # -- the sheet ----------------------------------------------------------

    def _present_pending_shifts(
        self, tenant_id: str, date_from: datetime.date, date_to: datetime.date, work_center_id: str
    ) -> None:
        """Lay every shift still being filled in, or waiting for its validator, out as old-style
        reports, so the sheet reads it exactly the way validation will (same owner, energy split
        and machine rules: one conversion, not a second copy that could drift). A returned shift
        is on its way back to its team and is left out, like a rejected report always was.

        The rows only exist inside the caller's rolled-back savepoint.
        """
        for shift_id, created_by in self._connection.execute(
            "SELECT id, created_by FROM production.shift_reports "
            "WHERE tenant_id = %s AND work_center_id = %s AND report_date BETWEEN %s AND %s "
            "AND status IN ('open', 'submitted') ORDER BY report_date, id",
            (tenant_id, work_center_id, date_from, date_to),
        ).fetchall():
            # A shift with nothing in it yet has nothing to show; that is not an error here.
            materialize_shift(
                self._connection, tenant_id=tenant_id, shift_report_id=shift_id, actor_id=created_by or "", provisional=True
            )

    def read_sheet(
        self,
        *,
        tenant_id: str,
        date_from: datetime.date,
        date_to: datetime.date,
        work_center_id: str,
        include_pending: bool,
        column_of: Callable[[dict], str],
        yield_by_column: bool = False,
    ) -> dict:
        """The rows and per-column report counts for a range, columns chosen by `column_of`."""
        with self._connection.transaction(force_rollback=True):
            self._present_pending_shifts(tenant_id, date_from, date_to, work_center_id)
            return self._read_sheet(
                tenant_id=tenant_id, date_from=date_from, date_to=date_to, work_center_id=work_center_id,
                include_pending=include_pending, column_of=column_of, yield_by_column=yield_by_column,
            )

    def _read_sheet(
        self,
        *,
        tenant_id: str,
        date_from: datetime.date,
        date_to: datetime.date,
        work_center_id: str,
        include_pending: bool,
        column_of: Callable[[dict], str],
        yield_by_column: bool = False,
    ) -> dict:
        reports = self._reports(tenant_id, date_from, date_to, work_center_id)
        shown = _WITH_PENDING if include_pending else _VALIDATED
        figures = [r for r in reports if r["status"] in shown]
        column = {r["id"]: column_of(r) for r in reports}
        by_id = {r["id"]: r for r in figures}
        daily_ids = [r["id"] for r in figures if r["type"] == "daily"]
        packing_ids = [r["id"] for r in figures if r["type"] == "conditionnement"]

        daily_rows = self._rows_for(
            """
            SELECT report_id, water_quantity, production_minutes, fuel_quantity, gasoil_quantity,
                   electricity_quantity, generator_hours, regrind_input_quantity, regrind_input_product_id
            FROM production.daily_reports WHERE tenant_id = %s AND report_id = ANY(%s)
            """,
            tenant_id, daily_ids,
        )
        semolina_rows = self._rows_for(
            "SELECT report_id, product_id, quantity FROM production.report_semolina_lines "
            "WHERE tenant_id = %s AND report_id = ANY(%s) ORDER BY report_id, line_order",
            tenant_id, daily_ids,
        )
        downtime_rows = self._rows_for(
            "SELECT report_id, SUM(minutes) FROM production.report_downtime_lines "
            "WHERE tenant_id = %s AND report_id = ANY(%s) GROUP BY report_id",
            tenant_id, daily_ids,
        )
        waste_rows = self._rows_for(
            "SELECT report_id, category, product_id, quantity FROM production.report_waste_lines "
            "WHERE tenant_id = %s AND report_id = ANY(%s) ORDER BY report_id, line_order",
            tenant_id, daily_ids + packing_ids,
        )
        packing_rows = self._rows_for(
            """
            SELECT report_id, finished_product_quantity, packets_counted, film_quantity, carton_quantity,
                   waste_carton_quantity, scotch_quantity, ruban_quantity, lot_number,
                   film_product_id, carton_product_id, scotch_product_id, ruban_product_id
            FROM production.conditionnement_reports WHERE tenant_id = %s AND report_id = ANY(%s)
            """,
            tenant_id, packing_ids,
        )

        wanted: set[str] = {r["of_product_id"] for r in figures if r["of_product_id"]}
        wanted |= {row[1] for row in semolina_rows if row[1]} | {row[2] for row in waste_rows if row[2]}
        wanted |= {row[8] for row in daily_rows if row[8]}
        for row in packing_rows:
            wanted |= {product for product in row[9:13] if product}
        products = self._products(tenant_id, wanted)
        base_units = self._base_units(tenant_id)

        def tonnes(quantity: float, product_id: str | None) -> float:
            """A weight in the product's own unit, restated into tonnes. Anything that
            is not a known weight is left as recorded: there is nothing to convert."""
            product = products.get(product_id or "")
            if product and product["category"] == "weight" and product["ratio"]:
                return quantity * product["ratio"] / KG_PER_TONNE
            return quantity

        def in_base_unit(quantity: float, product_id: str | None) -> tuple[float, str | None]:
            product = products.get(product_id or "")
            if not product or not product["ratio"]:
                return quantity, None
            return quantity * product["ratio"], base_units.get(product["category"])

        # -- Daily facts
        semolina: dict[str, list[tuple[str | None, str | None, float]]] = {}
        semolina_ratio: dict[str, float] = {}
        for report_id, product_id, quantity in semolina_rows:
            name = products.get(product_id or "", {}).get("name")
            semolina.setdefault(report_id, []).append((product_id, name, tonnes(float(quantity), product_id)))
            ratio = products.get(product_id or "", {}).get("ratio")
            if ratio and report_id not in semolina_ratio:
                semolina_ratio[report_id] = ratio
        downtime = {report_id: float(minutes) for report_id, minutes in downtime_rows}
        daily_waste: dict[str, list[tuple[str, float]]] = {}
        packing_waste: dict[str, list[tuple[str, str | None, str | None, float, str | None]]] = {}
        for report_id, category, product_id, quantity in waste_rows:
            if report_id in by_id and by_id[report_id]["type"] == "daily":
                # The daily form records déchet in raw kilos whatever the item's unit is.
                daily_waste.setdefault(report_id, []).append((category, float(quantity)))
            else:
                # Packing waste names no item on the shift screen: it is a kind and a weight in kilos.
                # Older lines that do name an item are restated in that item's own unit.
                amount, unit = in_base_unit(float(quantity), product_id) if product_id else (float(quantity), "kg")
                name = products.get(product_id or "", {}).get("name")
                packing_waste.setdefault(report_id, []).append((category, product_id, name, amount, unit))

        daily_facts: list[DailyFact] = []
        for report_id, water, minutes, fuel, gasoil, electricity, generator, regrind, regrind_product in daily_rows:
            regrind_ratio = products.get(regrind_product or "", {}).get("ratio")
            # Rebroyat with no product to say its unit is taken to be in the same unit as
            # the semoule poured with it -- the assumption every consolidation here makes.
            ratio = regrind_ratio or semolina_ratio.get(report_id) or KG_PER_TONNE
            daily_facts.append(
                DailyFact(
                    column=column[report_id],
                    water_l=float(water or 0),
                    production_minutes=float(minutes or 0),
                    downtime_minutes=downtime.get(report_id, 0.0),
                    regrind_t=float(regrind or 0) * ratio / KG_PER_TONNE,
                    fuel_l=float(fuel or 0),
                    gasoil_l=float(gasoil or 0),
                    electricity_kwh=float(electricity or 0),
                    generator_hours=float(generator or 0),
                    semolina=tuple(semolina.get(report_id, ())),
                    waste_kg=tuple(daily_waste.get(report_id, ())),
                )
            )

        # -- Conditionnement facts
        packaging_units: dict[str, str | None] = {}
        packing_facts: list[PackingFact] = []
        lots: dict[str, set[str]] = {}
        for (
            report_id, finished, packets, film, carton, waste_carton, scotch, ruban, lot,
            film_product, carton_product, scotch_product, ruban_product,
        ) in packing_rows:
            amounts: dict[str, float] = {}
            # Empty cartons are counted in the carton's own unit, so they share its row unit.
            for key, unit_row, quantity, product_id in (
                ("film", "film", film, film_product),
                ("carton", "carton", carton, carton_product),
                ("waste_carton", "carton", waste_carton, carton_product),
                ("scotch", "scotch", scotch, scotch_product),
                ("ruban", "ruban", ruban, ruban_product),
            ):
                amounts[key], unit = in_base_unit(float(quantity or 0), product_id)
                if unit and not packaging_units.get(unit_row):
                    packaging_units[unit_row] = unit
            of_product = by_id[report_id]["of_product_id"]
            finished_t = float(finished or 0)
            if by_id[report_id]["status"] != "validated":
                # The tonnage is settled from the count when a report is validated, so
                # a report still being filled in carries whatever was last saved. Read
                # its count the way validation will, or the sheet would show 0 t next
                # to 24 000 packets.
                product = products.get(of_product or "", {})
                finished_t = tonnage_from_count(
                    net_weight_grams=product.get("net_weight_grams"),
                    packets_per_carton=product.get("packets_per_carton"),
                    carton_quantity=float(carton or 0),
                    packets_counted=float(packets or 0),
                    waste_carton_quantity=float(waste_carton or 0),
                )
            packing_facts.append(
                PackingFact(
                    column=column[report_id],
                    product_id=of_product,
                    product_name=products.get(of_product or "", {}).get("name"),
                    finished_t=finished_t,
                    packets=float(packets or 0),
                    film=amounts["film"],
                    carton=amounts["carton"],
                    waste_carton=amounts["waste_carton"],
                    scotch=amounts["scotch"],
                    ruban=amounts["ruban"],
                    waste=tuple(packing_waste.get(report_id, ())),
                )
            )
            if lot:
                lots.setdefault(column[report_id], set()).add(lot)

        rows = build_rows(
            daily_facts, packing_facts, packaging_units=packaging_units, yield_by_column=yield_by_column
        )

        # -- what each column holds
        columns: dict[str, dict] = {}
        for r in reports:
            entry = columns.setdefault(
                column[r["id"]],
                {
                    "key": column[r["id"]],
                    "teams": set(),
                    "lots": set(),
                    "reports": {
                        kind: {"validated": 0, "pending": 0} for kind in ("daily", "conditionnement")
                    },
                },
            )
            if r["team"]:
                entry["teams"].add(r["team"])
            entry["reports"][r["type"]]["validated" if r["status"] == "validated" else "pending"] += 1
        for key, found in lots.items():
            columns[key]["lots"] = found

        of_product = {r["of_id"]: r["of_product_id"] for r in figures}
        ofs = (
            self._connection.execute(
                "SELECT id, reference FROM production.work_orders WHERE tenant_id = %s AND id = ANY(%s)",
                (tenant_id, sorted(of_product)),
            ).fetchall()
            if of_product
            else []
        )

        return {
            "columns": columns,
            "rows": [row.to_dict() for row in rows],
            "ofs": [
                {"id": i, "reference": ref, "product_name": products.get(of_product.get(i) or "", {}).get("name")}
                for i, ref in sorted(ofs, key=lambda o: o[1] or "")
            ],
        }

    def _line(self, tenant_id: str, work_center_id: str) -> dict | None:
        row = self._connection.execute(
            "SELECT id, code, name FROM production.work_centers WHERE tenant_id = %s AND id = %s",
            (tenant_id, work_center_id),
        ).fetchone()
        return {"id": row[0], "code": row[1], "name": row[2]} if row else None

    def get_day_sheet(
        self, *, tenant_id: str, date: datetime.date, work_center_id: str, include_pending: bool = False
    ) -> Result[dict]:
        line = self._line(tenant_id, work_center_id)
        if line is None:
            return Err("NOT_FOUND", "work center not found")

        sheet = self.read_sheet(
            tenant_id=tenant_id,
            date_from=date,
            date_to=date,
            work_center_id=work_center_id,
            include_pending=include_pending,
            column_of=lambda report: report["shift"] or NO_SHIFT,
        )

        # Shifts in the order the plant's day runs, then any shift a report was filed
        # under that is not a configured one. A configured shift nobody reported on is
        # still a column: an empty one is how a missing report shows on the sheet.
        windows = {w.shift.lower(): w for w in DashboardSettingsService(self._connection).list_shift_windows(tenant_id=tenant_id)}
        keys = {key.lower(): key for key in sheet["columns"]}
        for lowered, window in windows.items():
            keys.setdefault(lowered, window.shift)
        columns = []
        for lowered, key in sorted(
            keys.items(),
            key=lambda item: (windows[item[0]].start if item[0] in windows else datetime.time.max, item[1]),
        ):
            entry = sheet["columns"].get(key) or _empty_column(key)
            columns.append({**entry, "teams": sorted(entry["teams"]), "lots": sorted(entry["lots"])})
        if any(c["key"] == NO_SHIFT for c in columns):
            columns.sort(key=lambda c: c["key"] == NO_SHIFT)

        return Ok(
            {
                "date": date.isoformat(),
                "work_center": line,
                "include_pending": include_pending,
                "columns": columns,
                "rows": sheet["rows"],
                "ofs": sheet["ofs"],
            }
        )

    def get_month_recap(self, *, tenant_id: str, month: datetime.date, work_center_id: str) -> Result[dict]:
        """A line's month: the same rows as a day sheet, added up over every day, with a
        column per product produced instead of a column per shift.

        Validated reports only. The recap is what the month produced, so a report a
        team is still filling in or a supervisor has not signed off is counted in the
        column's `pending` and left out of the figures -- never added silently.
        """
        line = self._line(tenant_id, work_center_id)
        if line is None:
            return Err("NOT_FOUND", "work center not found")

        first = month.replace(day=1)
        last = (first.replace(day=28) + datetime.timedelta(days=4)).replace(day=1) - datetime.timedelta(days=1)
        sheet = self.read_sheet(
            tenant_id=tenant_id,
            date_from=first,
            date_to=last,
            work_center_id=work_center_id,
            include_pending=False,
            column_of=lambda report: report["of_product_id"] or NO_PRODUCT,
            yield_by_column=True,
        )
        names = self._products(tenant_id, {key for key in sheet["columns"] if key != NO_PRODUCT})
        columns = [
            {
                **entry,
                "name": names.get(key, {}).get("name"),
                "teams": sorted(entry["teams"]),
                "lots": sorted(entry["lots"]),
            }
            for key, entry in sheet["columns"].items()
        ]
        columns.sort(key=lambda c: (c["name"] is None, (c["name"] or "").lower(), c["key"]))

        return Ok(
            {
                "month": first.strftime("%Y-%m"),
                "work_center": line,
                "columns": columns,
                "rows": sheet["rows"],
            }
        )


def _empty_column(key: str) -> dict:
    return {
        "key": key,
        "teams": set(),
        "lots": set(),
        "reports": {kind: {"validated": 0, "pending": 0} for kind in ("daily", "conditionnement")},
    }
