"""The month's production workbook: the plant's recap and every day sheet in one file.

Sheet order, as the plant reads it:

1. ``Récap`` -- the month at a glance (one KPI column per line and the plant total),
   then each line's recap grid with a column per product, exactly as the screen.
2. ``Récap par lot`` -- the same month with one row per lot: what went in, what came
   out, over which days, and the lot's yield.
3. One day sheet per line and per day, the PC line's days first and then the PL
   line's (``PC 01`` .. ``PC 30``, ``PL 01`` ..): the day's reports, a column per shift.
4. ``Conso production`` and ``Conso conditionnement`` -- what was consumed while
   making pasta and what was consumed while packing it, per day and per lot/product.
5. ``Énergie`` -- electricity, fuel, gasoil and generator hours per day, and per tonne.
6. ``Arrêts``, ``Déchets``, ``Équipes``, ``Tendance`` -- the analyses a manager asks for
   next: where the hours went, where the kilos went, who ran what, and how the month
   moved day by day (with charts).

Validated reports only, like the screen's recap: a figure a supervisor has not signed
off is counted as waiting, never added. Everything is built from one read of each
line's month (`DaySheetService.load`) so the sheets cannot disagree with each other.
"""
from __future__ import annotations

import calendar
import datetime
import io
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

import psycopg
from openpyxl import Workbook
from openpyxl.chart import BarChart, LineChart, Reference
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from modules.production.api.dashboard_settings_service import DashboardSettingsService
from modules.production.api.day_sheet_service import (
    NO_LOT,
    NO_PRODUCT,
    NO_SHIFT,
    DaySheetService,
    LoadedSheet,
    assemble,
    lot_columns,
    month_bounds,
    product_columns,
    shift_columns,
)
from modules.production.api.waste_type_service import WasteTypeService
from modules.production.domain.day_sheet import KG_PER_TONNE, PRODUCT_WASTE, SECTIONS, DailyFact, PackingFact

# -- French labels ------------------------------------------------------------------

MONTHS_FR = (
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
)
DAYS_FR = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")

SECTION_LABELS_FR = {
    "material": "Consommation MP",
    "production": "Production",
    "waste": "Déchets",
    "packing": "Conditionnement",
    "energy": "Énergie",
}

ROW_LABELS_FR = {
    "total_mp": "Total MP",
    "regrind": "Rebroyat",
    "total_fab": "Total fabrication",
    "water": "Eau",
    "production_hours": "Heures de production",
    "downtime_hours": "Heures d'arrêt",
    "hourly_output": "Production horaire",
    "total_waste": "Total déchets",
    "total_packing_waste": "Total déchets emballage",
    "total_finished": "Total conditionné",
    "yield": "Rendement (conditionné ÷ fabrication)",
    "packets": "Paquets comptés",
    "film": "Film (cello)",
    "carton": "Cartons",
    "waste_carton": "Cartons déchet",
    "scotch": "Bande adhésive (scotch)",
    "ruban": "Ruban imprimante",
    "electricity": "Électricité",
    "fuel": "Fuel chaudière",
    "gasoil": "Gasoil groupe électrogène",
    "generator_hours": "Heures groupe électrogène",
}

WASTE_LABELS_FR = {
    "raw_material": "Matière",
    "press": "Presse",
    "pouring": "Versement",
    "cross": "Cross",
    "kneading": "Pétrin",
    "finished_product_conditioning": "Produit fini (conditionnement)",
    "product": "Produit",
    "packaging": "Emballage",
}

MOTIF_LABELS_FR = {
    "format_change": "Changement de format / recette",
    "cleaning_extruder": "Nettoyage extrudeuse",
    "cleaning_dryer": "Nettoyage séchoir",
    "scheduled_maintenance": "Maintenance préventive programmée",
    "team_break": "Pause équipe / relève",
    "end_of_production": "Fin de production (pas de commande)",
    "extruder_failure": "Panne extrudeuse / filière",
    "die_jam": "Bourrage / colmatage filière",
    "dryer_failure": "Panne séchoir (température/ventilation)",
    "cutter_failure": "Panne système de coupe/découpe",
    "packaging_failure": "Panne conditionneuse / peseuse",
    "film_jam": "Bourrage film d'emballage",
    "conveyor_failure": "Panne convoyeur / transfert",
    "electrical_failure": "Panne électrique",
    "pneumatic_failure": "Panne pneumatique / air comprimé",
    "steam_failure": "Panne vapeur / chaudière",
    "semolina_shortage": "Rupture semoule/farine",
    "water_shortage": "Rupture eau/additifs",
    "dough_nonconformity": "Non-conformité pâte (humidité, texture)",
    "qc_hold": "Attente contrôle qualité",
    "packaging_supply_shortage": "Rupture consommables (cartons, films, étiquettes)",
    "operator_shortage": "Sous-effectif / absence opérateur",
    "work_order_missing": "Attente ordre de fabrication",
    "security_incident": "Incident sécurité / accident",
    "product_evacuation_pending": "Attente évacuation produit fini",
    "other": "Autre",
}

DOWNTIME_TYPE_LABELS_FR = {
    "preventive": "Préventive",
    "corrective": "Corrective",
    "maintenance": "Maintenance",
    "cleaning": "Nettoyage",
}

# The line families the plant runs, in the order its workbook lists them.
_TAG_ORDER = {"PC": 0, "PL": 1}

DASH = "—"


def month_phrase(month: datetime.date) -> str:
    return f"{MONTHS_FR[month.month - 1]} {month.year}"


def day_phrase(day: datetime.date) -> str:
    return f"{DAYS_FR[day.weekday()]} {day.day} {MONTHS_FR[day.month - 1]} {day.year}"


def line_tag(name: str, code: str) -> str:
    """"PC" or "PL" when the line's name or code says which family it runs, else its code."""
    for candidate in (name or "", code or ""):
        upper = candidate.upper()
        for tag in ("PC", "PL"):
            if re.search(rf"(^|[^A-Z]){tag}([^A-Z]|$)", upper):
                return tag
    return (code or name or "?").upper()[:6]


# -- the data --------------------------------------------------------------------------


@dataclass
class LineMonth:
    line: dict
    tag: str
    sheet_prefix: str
    by_product: dict
    by_lot: dict
    days: list[dict]
    loaded: LoadedSheet


@dataclass
class MonthRecapData:
    month: datetime.date
    generated_on: datetime.date
    lines: list[LineMonth]
    waste_labels: dict[str, str] = field(default_factory=dict)
    motif_labels: dict[str, str] = field(default_factory=dict)


def _dedupe_prefixes(lines: list[tuple[dict, str]]) -> list[str]:
    """Day sheets are named "<prefix> <day>"; two lines of the same family need their own prefix."""
    counts: dict[str, int] = {}
    for _, tag in lines:
        counts[tag] = counts.get(tag, 0) + 1
    prefixes = []
    for line, tag in lines:
        prefixes.append(tag if counts[tag] == 1 else f"{tag} {line['code']}"[:12])
    return prefixes


def collect_month_recap(
    connection: psycopg.Connection, *, tenant_id: str, month: datetime.date, today: datetime.date | None = None
) -> MonthRecapData:
    """Read every production line's month once and lay it out every way the workbook prints it."""
    today = today or datetime.date.today()
    first, last = month_bounds(month)
    service = DaySheetService(connection)
    settings = DashboardSettingsService(connection)
    windows = {w.shift.lower(): w for w in settings.list_shift_windows(tenant_id=tenant_id)}

    rows = connection.execute(
        "SELECT id, code, name FROM production.work_centers WHERE tenant_id = %s AND line_type = 'production' ORDER BY name",
        (tenant_id,),
    ).fetchall()
    lines = [({"id": i, "code": code, "name": name}, line_tag(name, code)) for i, code, name in rows]
    lines.sort(key=lambda item: (_TAG_ORDER.get(item[1], 2), item[1], item[0]["name"] or ""))
    prefixes = _dedupe_prefixes(lines)

    waste_labels = dict(WASTE_LABELS_FR)
    waste_types = WasteTypeService(connection)
    for entry in waste_types.list_builtin_settings(tenant_id=tenant_id):
        if entry["name"]:
            waste_labels[entry["category"]] = entry["name"]
    for entry in waste_types.list_types(tenant_id=tenant_id):
        waste_labels[entry["id"]] = entry["name"]

    days_in_month = [first + datetime.timedelta(days=n) for n in range((min(last, today) - first).days + 1)] if today >= first else []

    collected: list[LineMonth] = []
    for (line, tag), prefix in zip(lines, prefixes):
        with connection.transaction(force_rollback=True):
            service.present_pending_shifts(tenant_id, first, last, line["id"])
            loaded = service.load(
                tenant_id=tenant_id, date_from=first, date_to=last, work_center_id=line["id"], include_pending=False
            )
        by_product = assemble(loaded, column_of=lambda r: r["product_id"] or NO_PRODUCT, yield_by_column=True)
        by_product["columns"] = product_columns(by_product["columns"], loaded.products)
        by_lot = assemble(loaded, column_of=lambda r: r["lot"] or NO_LOT, yield_by_column=True)
        by_lot["columns"] = lot_columns(by_lot["columns"])
        days = []
        for day in days_in_month:
            sheet = assemble(loaded, column_of=lambda r: r["shift"] or NO_SHIFT, include=lambda r, d=day: r["date"] == d)
            columns = shift_columns(sheet["columns"], windows)
            days.append(
                {
                    "date": day,
                    "columns": columns,
                    "rows": sheet["rows"],
                    "ofs": sheet["ofs"],
                    "validated": sum(c["reports"][k]["validated"] for c in columns for k in ("daily", "conditionnement")),
                    "pending": sum(c["reports"][k]["pending"] for c in columns for k in ("daily", "conditionnement")),
                }
            )
        collected.append(
            LineMonth(line=line, tag=tag, sheet_prefix=prefix, by_product=by_product, by_lot=by_lot, days=days, loaded=loaded)
        )

    return MonthRecapData(
        month=first, generated_on=today, lines=collected, waste_labels=waste_labels, motif_labels=dict(MOTIF_LABELS_FR)
    )


# -- aggregates behind the analysis sheets ---------------------------------------------


@dataclass
class Agg:
    """A bucket of reports (a day, a lot, a team, a product, a line) added up in the sheet's units."""

    daily_reports: int = 0
    packing_reports: int = 0
    semolina: dict[str, float] = field(default_factory=dict)
    mp_t: float = 0.0
    regrind_t: float = 0.0
    water_l: float = 0.0
    minutes: float = 0.0
    downtime_minutes: float = 0.0
    kwh: float = 0.0
    fuel_l: float = 0.0
    gasoil_l: float = 0.0
    generator_h: float = 0.0
    waste_kg: dict[str, float] = field(default_factory=dict)
    finished_t: float = 0.0
    packets: float = 0.0
    film: float = 0.0
    carton: float = 0.0
    waste_carton: float = 0.0
    scotch: float = 0.0
    ruban: float = 0.0
    packing_waste: dict[tuple[str, str | None, str | None], float] = field(default_factory=dict)
    lots: set[str] = field(default_factory=set)
    products: set[str] = field(default_factory=set)
    teams: set[str] = field(default_factory=set)
    dates: set[datetime.date] = field(default_factory=set)

    def add_report(self, report: dict) -> None:
        if report.get("lot"):
            self.lots.add(report["lot"])
        if report.get("product_name"):
            self.products.add(report["product_name"])
        if report.get("team"):
            self.teams.add(report["team"])
        self.dates.add(report["date"])

    def add_daily(self, fact: DailyFact) -> None:
        self.daily_reports += 1
        for _product_id, name, tonnes in fact.semolina:
            self.semolina[name or "Semoule"] = self.semolina.get(name or "Semoule", 0.0) + tonnes
            self.mp_t += tonnes
        self.regrind_t += fact.regrind_t
        self.water_l += fact.water_l
        self.minutes += fact.production_minutes
        self.downtime_minutes += fact.downtime_minutes
        self.kwh += fact.electricity_kwh
        self.fuel_l += fact.fuel_l
        self.gasoil_l += fact.gasoil_l
        self.generator_h += fact.generator_hours
        for category, kilos in fact.waste_kg:
            self.waste_kg[category] = self.waste_kg.get(category, 0.0) + kilos

    def add_packing(self, fact: PackingFact) -> None:
        self.packing_reports += 1
        self.finished_t += fact.finished_t
        self.packets += fact.packets
        self.film += fact.film
        self.carton += fact.carton
        self.waste_carton += fact.waste_carton
        self.scotch += fact.scotch
        self.ruban += fact.ruban
        for category, _product_id, name, quantity, unit in fact.waste:
            key = (category, name, unit)
            self.packing_waste[key] = self.packing_waste.get(key, 0.0) + quantity

    def merge(self, other: "Agg") -> None:
        self.daily_reports += other.daily_reports
        self.packing_reports += other.packing_reports
        for name, tonnes in other.semolina.items():
            self.semolina[name] = self.semolina.get(name, 0.0) + tonnes
        for attr in (
            "mp_t", "regrind_t", "water_l", "minutes", "downtime_minutes", "kwh", "fuel_l", "gasoil_l",
            "generator_h", "finished_t", "packets", "film", "carton", "waste_carton", "scotch", "ruban",
        ):
            setattr(self, attr, getattr(self, attr) + getattr(other, attr))
        for category, kilos in other.waste_kg.items():
            self.waste_kg[category] = self.waste_kg.get(category, 0.0) + kilos
        for key, quantity in other.packing_waste.items():
            self.packing_waste[key] = self.packing_waste.get(key, 0.0) + quantity
        self.lots |= other.lots
        self.products |= other.products
        self.teams |= other.teams
        self.dates |= other.dates

    @property
    def reports(self) -> int:
        return self.daily_reports + self.packing_reports

    @property
    def fab_t(self) -> float:
        return self.mp_t + self.regrind_t

    @property
    def hours(self) -> float:
        return self.minutes / 60

    @property
    def downtime_hours(self) -> float:
        return self.downtime_minutes / 60

    @property
    def kg_per_hour(self) -> float | None:
        return self.fab_t * KG_PER_TONNE / self.hours if self.hours > 0 else None

    @property
    def yield_pct(self) -> float | None:
        return ratio(self.finished_t, self.fab_t, 100)

    @property
    def downtime_pct(self) -> float | None:
        return ratio(self.downtime_minutes, self.minutes + self.downtime_minutes, 100)

    @property
    def production_waste_kg(self) -> float:
        return sum(self.waste_kg.values())

    @property
    def packed_product_waste_kg(self) -> float:
        """Finished product lost while packing -- pasta, recorded in kilos (the Excel's "PF Cdt")."""
        return sum(q for (category, _n, _u), q in self.packing_waste.items() if category == PRODUCT_WASTE)

    @property
    def waste_total_kg(self) -> float:
        """Every kilo of pasta lost: the production stages and the product lost while packing,
        the same "Total déchets" as the sheet's. Packaging (film) is not pasta and stays apart."""
        return self.production_waste_kg + self.packed_product_waste_kg

    @property
    def packaging_waste_kg(self) -> float:
        """Packaging lost while packing (film), in kilos. A line against an item counted in
        pieces is left out: it is not a weight."""
        return sum(
            q for (category, _n, unit), q in self.packing_waste.items() if category != PRODUCT_WASTE and unit == "kg"
        )

    @property
    def good_carton(self) -> float:
        """Cartons that hold product: the counted cartons include the waste ones, the tonnage does not."""
        return self.carton - self.waste_carton

    def per_tonne(self, value: float) -> float | None:
        return ratio(value, self.fab_t)


def ratio(part: float | None, whole: float | None, scale: float = 1.0) -> float | None:
    if part is None or not whole or whole <= 0:
        return None
    return part / whole * scale


def aggregate(loaded: LoadedSheet, key_of: Callable[[dict], object]) -> dict:
    """Validated reports bucketed by `key_of`, each bucket added up."""
    buckets: dict = {}
    for report in loaded.reports:
        fact = loaded.facts_of(report["id"])
        if fact is None:
            continue
        bucket = buckets.setdefault(key_of(report), Agg())
        bucket.add_report(report)
        if isinstance(fact, DailyFact):
            bucket.add_daily(fact)
        else:
            bucket.add_packing(fact)
    return buckets


def line_total(loaded: LoadedSheet) -> Agg:
    total = Agg()
    for bucket in aggregate(loaded, lambda r: 0).values():
        total.merge(bucket)
    return total


def pending_count(loaded: LoadedSheet) -> int:
    return sum(1 for r in loaded.reports if r["status"] != "validated")


# -- house style --------------------------------------------------------------------

_NAVY = "1F3864"
_BLUE = "305496"
_LIGHT = "D9E1F2"
_BAND = "EEF2F8"
_TOTAL = "E7E6E6"
_HIGHLIGHT = "FFF2CC"
_WHITE = "FFFFFF"
_MUTED = "7F7F7F"

TITLE_FONT = Font(bold=True, size=16, color=_WHITE)
SUBTITLE_FONT = Font(italic=True, size=10, color=_MUTED)
HEADER_FONT = Font(bold=True, color=_WHITE)
BOLD = Font(bold=True)
MUTED = Font(color=_MUTED)
SECTION_FONT = Font(bold=True, color=_NAVY)
TITLE_FILL = PatternFill("solid", fgColor=_NAVY)
HEADER_FILL = PatternFill("solid", fgColor=_BLUE)
SECTION_FILL = PatternFill("solid", fgColor=_LIGHT)
BAND_FILL = PatternFill("solid", fgColor=_BAND)
TOTAL_FILL = PatternFill("solid", fgColor=_TOTAL)
HIGHLIGHT_FILL = PatternFill("solid", fgColor=_HIGHLIGHT)
THIN = Side(style="thin", color="BFBFBF")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
CENTER = Alignment(horizontal="center", vertical="center", wrap_text=True)
LEFT = Alignment(horizontal="left", vertical="center")
RIGHT = Alignment(horizontal="right", vertical="center")

# How a figure in each unit prints. A unit not listed prints with two decimals.
NUMBER_FORMATS = {
    "T": "#,##0.00",
    "h": "0.00",
    "kg": "#,##0.0",
    "l": "#,##0",
    "kWh": "#,##0",
    "kg/h": "#,##0",
    "%": '0.0"%"',
    "ea": "#,##0",
    "l/T": "#,##0.0",
    "kWh/T": "#,##0.0",
    "kg/T": "#,##0.0",
    "ea/T": "#,##0.0",
    "ea/carton": "#,##0.0",
    "n": "#,##0",
    "min": "#,##0",
    "date": "DD/MM/YYYY",
}
_DEFAULT_FORMAT = "#,##0.00"


def _fmt(unit: str | None) -> str:
    return NUMBER_FORMATS.get(unit or "", _DEFAULT_FORMAT)


def _put(ws: Worksheet, row: int, col: int, value, *, unit: str | None = None, font: Font | None = None,
         fill: PatternFill | None = None, align: Alignment | None = None, border: bool = True):
    """One cell: a number in its unit's format, None as a dash, text as text."""
    if value is None:
        cell = ws.cell(row=row, column=col, value=DASH)
        cell.font = MUTED
        cell.alignment = align or CENTER
    else:
        cell = ws.cell(row=row, column=col, value=value)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            cell.number_format = _fmt(unit)
            cell.alignment = align or RIGHT
        elif isinstance(value, (datetime.date, datetime.datetime)):
            cell.number_format = NUMBER_FORMATS["date"]
            cell.alignment = align or CENTER
        else:
            cell.alignment = align or LEFT
        if font is not None:
            cell.font = font
    if fill is not None:
        cell.fill = fill
    if border:
        cell.border = BORDER
    return cell


def _title(ws: Worksheet, row: int, span: int, text: str, subtitle: str | None = None) -> int:
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=span)
    cell = ws.cell(row=row, column=1, value=text)
    cell.font = TITLE_FONT
    cell.alignment = LEFT
    for col in range(1, span + 1):
        ws.cell(row=row, column=col).fill = TITLE_FILL
    ws.row_dimensions[row].height = 28
    row += 1
    if subtitle:
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=span)
        cell = ws.cell(row=row, column=1, value=subtitle)
        cell.font = SUBTITLE_FONT
        row += 1
    return row + 1


def _heading(ws: Worksheet, row: int, span: int, text: str) -> int:
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=span)
    cell = ws.cell(row=row, column=1, value=text)
    cell.font = SECTION_FONT
    cell.alignment = LEFT
    for col in range(1, span + 1):
        ws.cell(row=row, column=col).fill = SECTION_FILL
    return row + 1


def _headers(ws: Worksheet, row: int, labels: Iterable[str], start_col: int = 1) -> int:
    for offset, label in enumerate(labels):
        cell = ws.cell(row=row, column=start_col + offset, value=label)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.border = BORDER
        cell.alignment = CENTER
    ws.row_dimensions[row].height = 30
    return row + 1


def _widths(ws: Worksheet, widths: Iterable[float], start_col: int = 1) -> None:
    for offset, width in enumerate(widths):
        ws.column_dimensions[get_column_letter(start_col + offset)].width = width


def _table(
    ws: Worksheet,
    row: int,
    headers: list[str],
    units: list[str | None],
    body: list[list],
    *,
    total: list | None = None,
    total_label: str = "Total",
    start_col: int = 1,
    highlight_cols: Iterable[int] = (),
) -> int:
    """A header row, data rows and an optional bold total row. `units` gives each
    column's unit (None for text) so every figure prints in its format."""
    row = _headers(ws, row, headers, start_col)
    highlight = set(highlight_cols)
    for values in body:
        for offset, value in enumerate(values):
            _put(ws, row, start_col + offset, value, unit=units[offset], fill=HIGHLIGHT_FILL if offset in highlight else None)
        row += 1
    if total is not None:
        for offset, value in enumerate(total):
            if offset == 0 and value is None:
                value = total_label
            _put(ws, row, start_col + offset, value, unit=units[offset], font=BOLD, fill=TOTAL_FILL)
        row += 1
    return row + 1


def _empty_note(ws: Worksheet, row: int, text: str) -> int:
    cell = ws.cell(row=row, column=1, value=text)
    cell.font = MUTED
    return row + 2


def _safe_sheet_name(name: str) -> str:
    return re.sub(r"[\[\]:*?/\\]", "-", name)[:31]


# -- the recap grid (shared by the Récap sheet and every day sheet) -------------------


def _row_label(row: dict, waste_labels: dict[str, str]) -> str:
    key = row["key"]
    if key in ("semolina", "finished"):
        return row["name"] or DASH
    if key == "waste":
        return waste_labels.get(row["ref"] or "", row["ref"] or DASH)
    if key == "packed_product_waste":
        label = waste_labels.get("finished_product_conditioning") or WASTE_LABELS_FR["finished_product_conditioning"]
        return f"{label} · {row['name'] or DASH}"
    if key == "packing_waste":
        return f"Déchet {waste_labels.get(row['ref'] or '', row['ref'] or DASH).lower()} · {row['name'] or DASH}"
    return ROW_LABELS_FR.get(key, key)


def _is_total(row: dict) -> bool:
    return row["key"].startswith("total_") or row["key"] == "yield"


def _lot_summary(lots: list[str]) -> str:
    if not lots:
        return DASH
    if len(lots) <= 3:
        return ", ".join(lots)
    return f"{len(lots)} lots · {lots[0]} → {lots[-1]}"


def write_grid(
    ws: Worksheet,
    row: int,
    *,
    first_header: str,
    columns: list[dict],
    rows: list[dict],
    waste_labels: dict[str, str],
    column_title: Callable[[dict], str],
    detail_lines: list[tuple[str, Callable[[dict], str]]],
    lot_row: bool = True,
    freeze: bool = False,
) -> int:
    """The plant's sheet: sections of rows, a column per shift / product / lot and a total.

    `detail_lines` are the small rows under the header (team, period...), each a
    label and how to read it off a column. The lot row is printed compactly when a
    column packed many lots, so a 69-lot product does not push the grid off screen.
    """
    span = len(columns) + 3
    _headers(ws, row, [first_header, "Unité", *[column_title(c) for c in columns], "Total"])
    header_row = row
    row += 1
    for label, read in detail_lines:
        _put(ws, row, 1, label, font=MUTED)
        _put(ws, row, 2, "", border=True)
        for offset, column in enumerate(columns):
            _put(ws, row, 3 + offset, read(column) or DASH, font=MUTED, align=CENTER)
        _put(ws, row, span, "", fill=TOTAL_FILL)
        row += 1
    if lot_row:
        _put(ws, row, 1, "Lot", font=MUTED)
        _put(ws, row, 2, "")
        all_lots: set[str] = set()
        for offset, column in enumerate(columns):
            all_lots |= set(column["lots"])
            _put(ws, row, 3 + offset, _lot_summary(column["lots"]), font=MUTED, align=CENTER)
        _put(ws, row, span, f"{len(all_lots)} lot(s)" if all_lots else DASH, font=MUTED, fill=TOTAL_FILL, align=CENTER)
        row += 1
    pending = [
        sum(c["reports"][k]["pending"] for k in ("daily", "conditionnement")) for c in columns
    ]
    if any(pending):
        _put(ws, row, 1, "Rapports non validés (non comptés)", font=MUTED)
        _put(ws, row, 2, "")
        for offset, count in enumerate(pending):
            _put(ws, row, 3 + offset, count if count else DASH, unit="n", font=Font(color="C00000", bold=bool(count)), align=CENTER)
        _put(ws, row, span, sum(pending), unit="n", font=Font(color="C00000", bold=True), fill=TOTAL_FILL, align=CENTER)
        row += 1
    if freeze:
        ws.freeze_panes = ws.cell(row=row, column=3)

    for section in SECTIONS:
        own = [r for r in rows if r["section"] == section]
        if not own:
            continue
        for col in range(1, span + 1):
            cell = ws.cell(row=row, column=col, value=SECTION_LABELS_FR[section].upper() if col == 1 else None)
            cell.fill = BAND_FILL
            cell.font = SECTION_FONT
            cell.border = BORDER
        row += 1
        for sheet_row in own:
            total = _is_total(sheet_row)
            font = BOLD if total else None
            _put(ws, row, 1, _row_label(sheet_row, waste_labels), font=font)
            _put(ws, row, 2, sheet_row["unit"] or "", font=MUTED, align=CENTER)
            for offset, column in enumerate(columns):
                _put(ws, row, 3 + offset, sheet_row["by_column"].get(column["key"]), unit=sheet_row["unit"], font=font)
            _put(ws, row, span, sheet_row["total"], unit=sheet_row["unit"], font=BOLD, fill=TOTAL_FILL)
            row += 1
    ws.column_dimensions["A"].width = 38
    ws.column_dimensions["B"].width = 8
    for offset in range(len(columns) + 1):
        ws.column_dimensions[get_column_letter(3 + offset)].width = 16
    ws.row_dimensions[header_row].height = 34
    return row + 1


# -- sheets --------------------------------------------------------------------------


def _kpi_rows(totals: list[tuple[str, Agg, int]]) -> tuple[list[str], list[list], list[str | None]]:
    """The month at a glance: one column per line and the plant total."""
    plant = Agg()
    for _name, agg, _pending in totals:
        plant.merge(agg)
    plant_pending = sum(p for _n, _a, p in totals)
    cells = [*[(a, p) for _n, a, p in totals], (plant, plant_pending)]
    indicators: list[tuple[str, str | None, Callable[[Agg, int], object]]] = [
        ("Total MP (semoule)", "T", lambda a, p: a.mp_t),
        ("Rebroyat", "T", lambda a, p: a.regrind_t),
        ("Total fabrication", "T", lambda a, p: a.fab_t),
        ("Total conditionné", "T", lambda a, p: a.finished_t),
        ("Rendement (conditionné ÷ fabrication)", "%", lambda a, p: a.yield_pct),
        ("Heures de production", "h", lambda a, p: a.hours),
        ("Heures d'arrêt", "h", lambda a, p: a.downtime_hours),
        ("Taux d'arrêt", "%", lambda a, p: a.downtime_pct),
        ("Production horaire", "kg/h", lambda a, p: a.kg_per_hour),
        ("Paquets comptés", "ea", lambda a, p: a.packets),
        ("Cartons", "ea", lambda a, p: a.carton),
        ("Électricité", "kWh", lambda a, p: a.kwh),
        ("Électricité par tonne fabriquée", "kWh/T", lambda a, p: a.per_tonne(a.kwh)),
        ("Fuel chaudière", "l", lambda a, p: a.fuel_l),
        ("Gasoil groupe électrogène", "l", lambda a, p: a.gasoil_l),
        ("Eau", "l", lambda a, p: a.water_l),
        ("Eau par tonne fabriquée", "l/T", lambda a, p: a.per_tonne(a.water_l)),
        ("Total déchets (production + produit perdu au conditionnement)", "kg", lambda a, p: a.waste_total_kg),
        ("Déchets par tonne fabriquée", "kg/T", lambda a, p: a.per_tonne(a.waste_total_kg)),
        ("Déchets d'emballage (film)", "kg", lambda a, p: a.packaging_waste_kg),
        ("Jours avec production", "n", lambda a, p: len(a.dates)),
        ("Rapports validés", "n", lambda a, p: a.reports),
        ("Rapports non validés (non comptés)", "n", lambda a, p: p),
        ("Lots", "n", lambda a, p: len(a.lots)),
        ("Produits fabriqués", "n", lambda a, p: len(a.products)),
    ]
    headers = ["Indicateur", "Unité", *[name for name, _a, _p in totals], "Usine"]
    # A line nobody reported on reads as "—", not as 0 tonnes: the counts stay counts.
    body = [
        [label, unit, *[read(agg, pending) if agg.reports or unit == "n" else None for agg, pending in cells]]
        for label, unit, read in indicators
    ]
    return headers, body, [None, None, *[None] * len(cells)]


def build_recap_sheet(wb: Workbook, data: MonthRecapData) -> None:
    ws = wb.create_sheet("Récap")
    span = max(4, max((len(l.by_product["columns"]) for l in data.lines), default=0) + 3, len(data.lines) + 3)
    row = _title(
        ws, 1, span, f"Récapitulatif de production — {month_phrase(data.month)}",
        f"Généré le {data.generated_on.strftime('%d/%m/%Y')} · rapports validés uniquement · {len(data.lines)} ligne(s)",
    )
    if not data.lines:
        _empty_note(ws, row, "Aucune ligne de production n'est configurée.")
        return

    row = _heading(ws, row, span, "Vue d'ensemble du mois")
    totals = [(f"{l.tag} · {l.line['name']}", line_total(l.loaded), pending_count(l.loaded)) for l in data.lines]
    headers, body, _units = _kpi_rows(totals)
    row = _headers(ws, row, headers)
    for label, unit, *values in body:
        _put(ws, row, 1, label, font=BOLD if label.startswith("Total") or label.startswith("Rendement") else None)
        _put(ws, row, 2, unit or "", font=MUTED, align=CENTER)
        for offset, value in enumerate(values):
            last = offset == len(values) - 1
            _put(ws, row, 3 + offset, value, unit=unit, font=BOLD if last else None, fill=TOTAL_FILL if last else None)
        row += 1
    row += 1

    for line in data.lines:
        row = _heading(ws, row, span, f"{line.tag} · {line.line['name']} — récap par produit")
        columns = line.by_product["columns"]
        if not columns:
            row = _empty_note(ws, row, "Aucun rapport validé pour cette ligne ce mois-ci.")
            continue
        row = write_grid(
            ws, row,
            first_header=line.line["name"],
            columns=columns,
            rows=line.by_product["rows"],
            waste_labels=data.waste_labels,
            column_title=lambda c: c["name"] or "Sans produit",
            detail_lines=[("Période", lambda c: _period(c["date_from"], c["date_to"]))],
        )
    ws.column_dimensions["A"].width = 40
    ws.column_dimensions["B"].width = 8
    ws.freeze_panes = "C4"


def _period(date_from: str | None, date_to: str | None) -> str:
    if not date_from:
        return DASH
    start = datetime.date.fromisoformat(date_from)
    end = datetime.date.fromisoformat(date_to or date_from)
    if start == end:
        return start.strftime("%d/%m")
    return f"{start.strftime('%d/%m')} → {end.strftime('%d/%m')}"


def _row_value(rows: list[dict], key: str, column: str) -> float | None:
    for r in rows:
        if r["key"] == key and r["ref"] is None:
            return r["by_column"].get(column)
    return None


def build_lot_sheet(wb: Workbook, data: MonthRecapData) -> None:
    ws = wb.create_sheet("Récap par lot")
    headers = [
        "Lot", "Produit", "Du", "Au", "Rapports", "Semoule (T)", "Rebroyat (T)", "Fabrication (T)",
        "Heures prod.", "Heures d'arrêt", "kg/h", "Conditionné (T)", "Rendement", "Paquets", "Cartons",
        "Film", "Déchets prod. (kg)",
    ]
    units: list[str | None] = [None, None, "date", "date", "n", "T", "T", "T", "h", "h", "kg/h", "T", "%", "ea", "ea", "kg", "kg"]
    span = len(headers)
    row = _title(
        ws, 1, span, f"Récap par lot — {month_phrase(data.month)}",
        "Chaque lot additionne tous ses rapports validés du mois, production et conditionnement ; "
        "le rendement d'un lot est ce qui en a été conditionné sur ce qui y a été fabriqué.",
    )
    for line in data.lines:
        row = _heading(ws, row, span, f"{line.tag} · {line.line['name']}")
        columns = line.by_lot["columns"]
        rows = line.by_lot["rows"]
        if not columns:
            row = _empty_note(ws, row, "Aucun rapport validé pour cette ligne ce mois-ci.")
            continue
        body = []
        for column in columns:
            key = column["key"]
            reports = sum(column["reports"][k]["validated"] for k in ("daily", "conditionnement"))
            if not reports:
                # Every report of this lot is still waiting: it is counted on the Récap, not here.
                continue
            body.append([
                column["name"] or "Sans lot",
                ", ".join(column["products"]) or DASH,
                datetime.date.fromisoformat(column["date_from"]) if column["date_from"] else None,
                datetime.date.fromisoformat(column["date_to"]) if column["date_to"] else None,
                reports,
                _row_value(rows, "total_mp", key),
                _row_value(rows, "regrind", key),
                _row_value(rows, "total_fab", key),
                _row_value(rows, "production_hours", key),
                _row_value(rows, "downtime_hours", key),
                _row_value(rows, "hourly_output", key),
                _row_value(rows, "total_finished", key),
                _row_value(rows, "yield", key),
                _row_value(rows, "packets", key),
                _row_value(rows, "carton", key),
                _row_value(rows, "film", key),
                _row_value(rows, "total_waste", key),
            ])
        total = line_total(line.loaded)
        totals = [
            None, f"{len(body)} lot(s)", None, None, total.reports, total.mp_t, total.regrind_t, total.fab_t,
            total.hours, total.downtime_hours, total.kg_per_hour, total.finished_t, total.yield_pct,
            total.packets, total.carton, total.film, total.waste_total_kg,
        ]
        row = _table(ws, row, headers, units, body, total=totals, highlight_cols=(12,))
    _widths(ws, [16, 28, 11, 11, 10, 12, 12, 14, 12, 12, 10, 14, 11, 12, 10, 10, 14])
    ws.freeze_panes = "C4"


def build_day_sheets(wb: Workbook, data: MonthRecapData) -> None:
    for line in data.lines:
        for day in line.days:
            date = day["date"]
            ws = wb.create_sheet(_safe_sheet_name(f"{line.sheet_prefix} {date.day:02d}"))
            columns = day["columns"]
            span = max(4, len(columns) + 3)
            status = (
                "aucun rapport" if not day["validated"] and not day["pending"]
                else f"{day['validated']} rapport(s) validé(s)" + (f", {day['pending']} non validé(s) non compté(s)" if day["pending"] else "")
            )
            row = _title(
                ws, 1, span, f"{line.line['name']} — fiche du {day_phrase(date)}",
                f"{line.tag} · {status}",
            )
            if day["ofs"]:
                orders = " — ".join(" · ".join(part for part in (o["reference"], o["product_name"]) if part) for o in day["ofs"])
                cell = ws.cell(row=row - 1, column=1, value=f"Ordres : {orders}")
                cell.font = MUTED
            row = write_grid(
                ws, row,
                first_header=line.line["name"],
                columns=columns,
                rows=day["rows"],
                waste_labels=data.waste_labels,
                column_title=lambda c: (c["name"] or "Sans équipe").capitalize(),
                detail_lines=[("Équipe", lambda c: ", ".join(c["teams"])), ("Produit", lambda c: ", ".join(c["products"]))],
                freeze=True,
            )
            cell = ws.cell(row=row, column=1, value="— : aucun rapport déposé pour cette équipe ; 0 : un rapport déposé avec 0. La colonne Total additionne les équipes.")
            cell.font = MUTED


def build_production_consumption_sheet(wb: Workbook, data: MonthRecapData) -> None:
    ws = wb.create_sheet("Conso production")
    row = _title(
        ws, 1, 14, f"Consommation pendant la production — {month_phrase(data.month)}",
        "Semoule versée par qualité, rebroyat réincorporé, eau et heures, par jour puis par lot.",
    )
    for line in data.lines:
        qualities = sorted({name for fact in line.loaded.daily_facts.values() for _i, name, _t in fact.semolina}, key=lambda n: n or "")
        qualities = [q or "Semoule" for q in qualities]
        headers = ["Date", "Jour", *qualities, "Total MP (T)", "Rebroyat (T)", "Fabrication (T)", "Eau (l)", "Eau (l/T)", "Heures prod.", "kg/h", "Lots"]
        units: list[str | None] = [None, None, *["T"] * len(qualities), "T", "T", "T", "l", "l/T", "h", "kg/h", None]
        row = _heading(ws, row, len(headers), f"{line.tag} · {line.line['name']} — par jour")
        by_day = aggregate(line.loaded, lambda r: r["date"])
        by_day = {d: a for d, a in by_day.items() if a.daily_reports}
        if not by_day:
            row = _empty_note(ws, row, "Aucune production validée ce mois-ci.")
        else:
            body = [
                [
                    day, DAYS_FR[day.weekday()], *[agg.semolina.get(q) for q in qualities], agg.mp_t, agg.regrind_t, agg.fab_t,
                    agg.water_l, agg.per_tonne(agg.water_l), agg.hours, agg.kg_per_hour, ", ".join(sorted(agg.lots)) or DASH,
                ]
                for day, agg in sorted(by_day.items())
            ]
            total = Agg()
            for agg in by_day.values():
                total.merge(agg)
            totals = [
                None, f"{len(by_day)} jour(s)", *[total.semolina.get(q) for q in qualities], total.mp_t, total.regrind_t,
                total.fab_t, total.water_l, total.per_tonne(total.water_l), total.hours, total.kg_per_hour, f"{len(total.lots)} lot(s)",
            ]
            row = _table(ws, row, headers, units, body, total=totals)

        lot_headers = ["Lot", "Produit", "Du", "Au", *qualities, "Total MP (T)", "Rebroyat (T)", "Fabrication (T)", "Eau (l)", "Heures prod.", "kg/h"]
        lot_units: list[str | None] = [None, None, "date", "date", *["T"] * len(qualities), "T", "T", "T", "l", "h", "kg/h"]
        row = _heading(ws, row, len(lot_headers), f"{line.tag} · {line.line['name']} — par lot")
        by_lot = {k: a for k, a in aggregate(line.loaded, lambda r: r["lot"] or "").items() if a.daily_reports}
        if not by_lot:
            row = _empty_note(ws, row, "Aucune production validée ce mois-ci.")
        else:
            body = [
                [
                    lot or "Sans lot", ", ".join(sorted(agg.products)) or DASH, min(agg.dates), max(agg.dates),
                    *[agg.semolina.get(q) for q in qualities], agg.mp_t, agg.regrind_t, agg.fab_t, agg.water_l, agg.hours, agg.kg_per_hour,
                ]
                for lot, agg in sorted(by_lot.items(), key=lambda item: (item[0] == "", min(item[1].dates), item[0]))
            ]
            row = _table(ws, row, lot_headers, lot_units, body)
    _widths(ws, [12, 12, 14, 14, 14, 14, 14, 12, 10, 12, 10, 24, 12, 12])
    ws.freeze_panes = "A4"


def build_packing_consumption_sheet(wb: Workbook, data: MonthRecapData) -> None:
    ws = wb.create_sheet("Conso conditionnement")
    row = _title(
        ws, 1, 15, f"Consommation pendant le conditionnement — {month_phrase(data.month)}",
        "Film, cartons, scotch et ruban consommés, paquets comptés et déchets de conditionnement, par jour puis par produit et par lot.",
    )
    for line in data.lines:
        units_of = line.loaded.packaging_units
        film_u, carton_u, scotch_u, ruban_u = (units_of.get(k) or "" for k in ("film", "carton", "scotch", "ruban"))
        headers = [
            "Date", "Jour", "Conditionné (T)", "Paquets", f"Cartons ({carton_u})".replace(" ()", ""), "Cartons déchet",
            f"Film ({film_u})".replace(" ()", ""), f"Scotch ({scotch_u})".replace(" ()", ""), f"Ruban ({ruban_u})".replace(" ()", ""),
            "Déchets emballage (kg)", "Film / T", "Cartons / T", "Paquets / carton", "Lots",
        ]
        units: list[str | None] = [None, None, "T", "ea", carton_u or None, carton_u or None, film_u or None, scotch_u or None, ruban_u or None, "kg", "kg/T", "ea/T", "ea/carton", None]

        def _line(label_a, label_b, agg: Agg, lots: str) -> list:
            return [
                label_a, label_b, agg.finished_t, agg.packets, agg.carton, agg.waste_carton, agg.film, agg.scotch, agg.ruban,
                agg.packaging_waste_kg, ratio(agg.film, agg.finished_t), ratio(agg.good_carton, agg.finished_t),
                ratio(agg.packets, agg.good_carton), lots,
            ]

        # A day with a mould change packs several formats; a row per product keeps each
        # row's cartons/T and packets/carton to one format instead of a blend.
        for title, key_of, label_of in (
            (
                "par jour et par produit",
                lambda r: (r["date"], r.get("product_name") or ""),
                lambda k, a: (k[0], f"{DAYS_FR[k[0].weekday()]} · {k[1] or 'Sans produit'}"),
            ),
            ("par produit", lambda r: r.get("product_name") or "", lambda k, a: (k or "Sans produit", f"{len(a.dates)} jour(s)")),
            ("par lot", lambda r: r["lot"] or "", lambda k, a: (k or "Sans lot", ", ".join(sorted(a.products)) or DASH)),
        ):
            row = _heading(ws, row, len(headers), f"{line.tag} · {line.line['name']} — {title}")
            buckets = {k: a for k, a in aggregate(line.loaded, key_of).items() if a.packing_reports}
            if not buckets:
                row = _empty_note(ws, row, "Aucun conditionnement validé ce mois-ci.")
                continue
            ordered = sorted(buckets.items(), key=lambda item: (item[0] == "", min(item[1].dates), str(item[0])))
            body = [_line(*label_of(k, a), a, ", ".join(sorted(a.lots)) or DASH) for k, a in ordered]
            total = Agg()
            for agg in buckets.values():
                total.merge(agg)
            totals = _line(None, f"{len(buckets)} ligne(s)", total, f"{len(total.lots)} lot(s)")
            row = _table(ws, row, headers, units, body, total=totals)
    _widths(ws, [14, 32, 14, 12, 12, 12, 12, 12, 12, 14, 10, 10, 12, 30])
    ws.freeze_panes = "A4"


def build_energy_sheet(wb: Workbook, data: MonthRecapData) -> None:
    ws = wb.create_sheet("Énergie")
    headers = [
        "Date", "Jour", "Électricité (kWh)", "Fuel chaudière (l)", "Gasoil groupe (l)", "Heures groupe (h)",
        "Fabrication (T)", "Heures prod.", "kWh / T", "Fuel l / T", "Gasoil l / h groupe", "kWh / h prod.",
    ]
    units: list[str | None] = [None, None, "kWh", "l", "l", "h", "T", "h", "kWh/T", "l/T", "l/T", "kWh/T"]
    row = _title(
        ws, 1, len(headers), f"Consommation d'énergie — {month_phrase(data.month)}",
        "L'énergie est saisie par shift et partagée entre ses passages au prorata des heures de production.",
    )

    def _energy_line(a: Agg, label_a, label_b) -> list:
        return [
            label_a, label_b, a.kwh, a.fuel_l, a.gasoil_l, a.generator_h, a.fab_t, a.hours, a.per_tonne(a.kwh),
            a.per_tonne(a.fuel_l), ratio(a.gasoil_l, a.generator_h), ratio(a.kwh, a.hours),
        ]

    plant_rows = []
    plant = Agg()
    for line in data.lines:
        row = _heading(ws, row, len(headers), f"{line.tag} · {line.line['name']} — par jour")
        by_day = {d: a for d, a in aggregate(line.loaded, lambda r: r["date"]).items() if a.daily_reports}
        total = Agg()
        for agg in by_day.values():
            total.merge(agg)
        plant.merge(total)
        plant_rows.append(_energy_line(total, f"{line.tag} · {line.line['name']}", f"{len(by_day)} jour(s)"))
        if not by_day:
            row = _empty_note(ws, row, "Aucune production validée ce mois-ci.")
            continue
        body = [_energy_line(agg, day, DAYS_FR[day.weekday()]) for day, agg in sorted(by_day.items())]
        row = _table(ws, row, headers, units, body, total=_energy_line(total, None, f"{len(by_day)} jour(s)"))

    row = _heading(ws, row, len(headers), "Usine — synthèse par ligne")
    row = _table(ws, row, ["Ligne", "Jours", *headers[2:]], units, plant_rows, total=_energy_line(plant, None, ""), total_label="Usine")
    _widths(ws, [24, 14, 16, 16, 16, 14, 14, 12, 10, 10, 14, 12])
    ws.freeze_panes = "A4"


def build_stops_sheet(wb: Workbook, data: MonthRecapData) -> None:
    ws = wb.create_sheet("Arrêts")
    row = _title(
        ws, 1, 8, f"Arrêts machine — {month_phrase(data.month)}",
        "Chaque arrêt saisi sur un rapport validé, regroupé par motif, puis le taux d'arrêt jour par jour.",
    )
    for line in data.lines:
        reports = {r["id"]: r for r in line.loaded.reports if line.loaded.facts_of(r["id"]) is not None}
        by_motif: dict[tuple[str, str], list[float]] = {}
        for report_id, stops in line.loaded.stops.items():
            report = reports.get(report_id)
            if report is None:
                continue
            side = "Production" if report["type"] == "daily" else "Conditionnement"
            for motif, downtime_type, _classification, minutes in stops:
                key = (side, data.motif_labels.get(motif or "", motif or "Sans motif"))
                by_motif.setdefault(key, []).append(minutes)
        row = _heading(ws, row, 8, f"{line.tag} · {line.line['name']} — par motif")
        total_minutes = sum(sum(v) for v in by_motif.values())
        if not by_motif:
            row = _empty_note(ws, row, "Aucun arrêt enregistré sur les rapports validés.")
        else:
            body = [
                [side, motif, len(minutes), sum(minutes), sum(minutes) / 60, ratio(sum(minutes), total_minutes, 100), sum(minutes) / len(minutes)]
                for (side, motif), minutes in sorted(by_motif.items(), key=lambda item: -sum(item[1]))
            ]
            count = sum(len(v) for v in by_motif.values())
            row = _table(
                ws, row, ["Étape", "Motif", "Nb d'arrêts", "Minutes", "Heures", "Part des arrêts", "Durée moyenne (min)"],
                [None, None, "n", "min", "h", "%", "min"], body,
                total=[None, "", count, total_minutes, total_minutes / 60, 100.0 if total_minutes else None, total_minutes / count if count else None],
            )

        row = _heading(ws, row, 8, f"{line.tag} · {line.line['name']} — par jour")
        by_day = {d: a for d, a in aggregate(line.loaded, lambda r: r["date"]).items() if a.daily_reports}
        if not by_day:
            row = _empty_note(ws, row, "Aucune production validée ce mois-ci.")
            continue
        body = [
            [day, DAYS_FR[day.weekday()], agg.hours, agg.downtime_hours, agg.downtime_pct, agg.kg_per_hour, ", ".join(sorted(agg.teams)) or DASH]
            for day, agg in sorted(by_day.items())
        ]
        total = Agg()
        for agg in by_day.values():
            total.merge(agg)
        row = _table(
            ws, row, ["Date", "Jour", "Heures prod.", "Heures d'arrêt", "Taux d'arrêt", "kg/h", "Équipes"],
            [None, None, "h", "h", "%", "kg/h", None], body,
            total=[None, f"{len(by_day)} jour(s)", total.hours, total.downtime_hours, total.downtime_pct, total.kg_per_hour, f"{len(total.teams)} équipe(s)"],
        )
    _widths(ws, [16, 44, 14, 14, 12, 14, 20, 12])
    ws.freeze_panes = "A4"


def build_waste_sheet(wb: Workbook, data: MonthRecapData) -> None:
    ws = wb.create_sheet("Déchets")
    row = _title(
        ws, 1, 7, f"Déchets — {month_phrase(data.month)}",
        "Pâtes perdues en kilos -- par étape de production et produit perdu au conditionnement -- et le poids par tonne "
        "fabriquée ; les déchets d'emballage (film) à part, car ce ne sont pas des pâtes.",
    )
    for line in data.lines:
        total = line_total(line.loaded)
        row = _heading(ws, row, 7, f"{line.tag} · {line.line['name']} — par étape")
        product_label = data.waste_labels.get("finished_product_conditioning") or WASTE_LABELS_FR["finished_product_conditioning"]
        body = [
            ["Production", data.waste_labels.get(category, category), kilos, "kg", total.per_tonne(kilos)]
            for category, kilos in sorted(total.waste_kg.items(), key=lambda item: -item[1])
        ]
        body += [
            ["Conditionnement", f"{product_label} · {name or DASH}", quantity, "kg", total.per_tonne(quantity)]
            for (category, name, _unit), quantity in sorted(total.packing_waste.items(), key=lambda item: -item[1])
            if category == PRODUCT_WASTE
        ]
        if not body:
            row = _empty_note(ws, row, "Aucun déchet enregistré sur les rapports validés.")
        else:
            row = _table(
                ws, row, ["Étape", "Type de déchet", "Quantité", "Unité", "kg par tonne fabriquée"],
                [None, None, "kg", None, "kg/T"], body,
                total=[None, "Total déchets", total.waste_total_kg, "kg", total.per_tonne(total.waste_total_kg)],
            )
        packaging = [
            [f"Déchet {data.waste_labels.get(category, category).lower()} · {name or DASH}", quantity, unit or ""]
            for (category, name, unit), quantity in sorted(total.packing_waste.items(), key=lambda item: -item[1])
            if category != PRODUCT_WASTE
        ]
        if packaging:
            row = _heading(ws, row, 7, f"{line.tag} · {line.line['name']} — déchets d'emballage (hors total déchets)")
            row = _table(
                ws, row, ["Article perdu", "Quantité", "Unité"], [None, "kg", None], packaging,
                total=["Total déchets emballage", total.packaging_waste_kg, "kg"],
            )
        row = _heading(ws, row, 7, f"{line.tag} · {line.line['name']} — par jour")
        by_day = {
            d: a for d, a in aggregate(line.loaded, lambda r: r["date"]).items() if a.waste_total_kg or a.packaging_waste_kg
        }
        if not by_day:
            row = _empty_note(ws, row, "Aucun déchet enregistré ce mois-ci.")
            continue
        body = [
            [day, DAYS_FR[day.weekday()], agg.production_waste_kg, agg.packed_product_waste_kg, agg.waste_total_kg,
             agg.fab_t, agg.per_tonne(agg.waste_total_kg), agg.packaging_waste_kg]
            for day, agg in sorted(by_day.items())
        ]
        day_total = Agg()
        for agg in by_day.values():
            day_total.merge(agg)
        row = _table(
            ws, row,
            ["Date", "Jour", "Déchets production (kg)", "Produit perdu au cond. (kg)", "Total déchets (kg)",
             "Fabrication (T)", "kg par tonne", "Déchets emballage (kg)"],
            [None, None, "kg", "kg", "kg", "T", "kg/T", "kg"], body,
            total=[None, f"{len(by_day)} jour(s)", day_total.production_waste_kg, day_total.packed_product_waste_kg,
                   day_total.waste_total_kg, day_total.fab_t, day_total.per_tonne(day_total.waste_total_kg),
                   day_total.packaging_waste_kg],
        )
    _widths(ws, [18, 40, 22, 24, 18, 16, 12, 20])
    ws.freeze_panes = "A4"


def build_teams_sheet(wb: Workbook, data: MonthRecapData) -> None:
    ws = wb.create_sheet("Équipes")
    headers = [
        "Équipe", "Rapports", "Jours", "Fabrication (T)", "Heures prod.", "kg/h", "Heures d'arrêt", "Taux d'arrêt",
        "Conditionné (T)", "Paquets", "Déchets prod. (kg)", "Déchets (kg/T)", "Eau (l/T)", "kWh / T",
    ]
    units: list[str | None] = [None, "n", "n", "T", "h", "kg/h", "h", "%", "T", "ea", "kg", "kg/T", "l/T", "kWh/T"]
    row = _title(
        ws, 1, len(headers), f"Performance par équipe — {month_phrase(data.month)}",
        "Ce que chaque équipe a fabriqué et conditionné sur ses shifts validés, et à quel rythme.",
    )
    for line in data.lines:
        row = _heading(ws, row, len(headers), f"{line.tag} · {line.line['name']}")
        by_team = aggregate(line.loaded, lambda r: r["team"] or "")
        if not by_team:
            row = _empty_note(ws, row, "Aucun rapport validé pour cette ligne ce mois-ci.")
            continue

        def _team_line(label, a: Agg) -> list:
            return [
                label, a.reports, len(a.dates), a.fab_t, a.hours, a.kg_per_hour, a.downtime_hours, a.downtime_pct, a.finished_t,
                a.packets, a.waste_total_kg, a.per_tonne(a.waste_total_kg), a.per_tonne(a.water_l), a.per_tonne(a.kwh),
            ]

        body = [_team_line(team or "Sans équipe", agg) for team, agg in sorted(by_team.items(), key=lambda item: -item[1].fab_t)]
        total = line_total(line.loaded)
        row = _table(ws, row, headers, units, body, total=_team_line(None, total), highlight_cols=(5,))
    _widths(ws, [22, 10, 8, 14, 12, 10, 14, 12, 14, 12, 16, 12, 10, 10])
    ws.freeze_panes = "A4"


def build_trend_sheet(wb: Workbook, data: MonthRecapData) -> None:
    ws = wb.create_sheet("Tendance")
    headers = ["Date", "Jour", "Fabrication (T)", "Conditionné (T)", "Heures prod.", "Heures d'arrêt", "kg/h", "Rendement", "kWh / T", "Lots"]
    units: list[str | None] = [None, None, "T", "T", "h", "h", "kg/h", "%", "kWh/T", None]
    row = _title(
        ws, 1, len(headers), f"Tendance du mois — {month_phrase(data.month)}",
        "Jour par jour : tonnes fabriquées et conditionnées, heures, cadence, rendement ; les graphiques se lisent à droite des tableaux.",
    )
    chart_anchor_col = get_column_letter(len(headers) + 2)
    for line in data.lines:
        row = _heading(ws, row, len(headers), f"{line.tag} · {line.line['name']}")
        by_day = {d: a for d, a in aggregate(line.loaded, lambda r: r["date"]).items() if a.reports}
        if not by_day:
            row = _empty_note(ws, row, "Aucun rapport validé pour cette ligne ce mois-ci.")
            continue
        body = [
            [day, DAYS_FR[day.weekday()], agg.fab_t, agg.finished_t, agg.hours, agg.downtime_hours, agg.kg_per_hour,
             agg.yield_pct, agg.per_tonne(agg.kwh), ", ".join(sorted(agg.lots)) or DASH]
            for day, agg in sorted(by_day.items())
        ]
        total = Agg()
        for agg in by_day.values():
            total.merge(agg)
        first_data_row = row + 1
        last_data_row = row + len(body)
        row = _table(
            ws, row, headers, units, body,
            total=[None, f"{len(by_day)} jour(s)", total.fab_t, total.finished_t, total.hours, total.downtime_hours,
                   total.kg_per_hour, total.yield_pct, total.per_tonne(total.kwh), f"{len(total.lots)} lot(s)"],
        )

        tonnage = BarChart()
        tonnage.type = "col"
        tonnage.grouping = "clustered"
        tonnage.title = f"{line.tag} — tonnes fabriquées et conditionnées par jour"
        tonnage.y_axis.title = "T"
        tonnage.add_data(Reference(ws, min_col=3, max_col=4, min_row=first_data_row - 1, max_row=last_data_row), titles_from_data=True)
        tonnage.set_categories(Reference(ws, min_col=1, min_row=first_data_row, max_row=last_data_row))
        tonnage.height, tonnage.width = 7.5, 22
        ws.add_chart(tonnage, f"{chart_anchor_col}{first_data_row - 1}")

        rate = LineChart()
        rate.title = f"{line.tag} — production horaire (kg/h)"
        rate.y_axis.title = "kg/h"
        rate.add_data(Reference(ws, min_col=7, max_col=7, min_row=first_data_row - 1, max_row=last_data_row), titles_from_data=True)
        rate.set_categories(Reference(ws, min_col=1, min_row=first_data_row, max_row=last_data_row))
        rate.height, rate.width = 7.5, 22
        ws.add_chart(rate, f"{chart_anchor_col}{first_data_row + 15}")
        # Leave room under the table for both charts.
        row = max(row, first_data_row + 32)
    _widths(ws, [12, 12, 14, 14, 12, 12, 10, 12, 10, 30])
    ws.freeze_panes = "A4"


def build_month_recap_workbook(data: MonthRecapData) -> bytes:
    wb = Workbook()
    wb.remove(wb.active)
    build_recap_sheet(wb, data)
    build_lot_sheet(wb, data)
    build_day_sheets(wb, data)
    build_production_consumption_sheet(wb, data)
    build_packing_consumption_sheet(wb, data)
    build_energy_sheet(wb, data)
    build_stops_sheet(wb, data)
    build_waste_sheet(wb, data)
    build_teams_sheet(wb, data)
    build_trend_sheet(wb, data)
    for ws in wb.worksheets:
        ws.sheet_view.showGridLines = False
        ws.sheet_properties.tabColor = _NAVY if ws.title in ("Récap", "Récap par lot") else None
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def workbook_filename(month: datetime.date) -> str:
    return f"recap-production-{month.strftime('%Y-%m')}.xlsx"


def days_of_month(month: datetime.date) -> int:
    return calendar.monthrange(month.year, month.month)[1]
