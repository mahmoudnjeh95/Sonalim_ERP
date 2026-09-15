from __future__ import annotations

import calendar
import datetime
import io

from openpyxl import Workbook

from core.domain.exchange_rate import BASE_CURRENCY
from modules.production.api.consumption_report_export import (
    build_fuel_sheet,
    build_packaging_sheet,
    build_rub_scotch_sheet,
)
from modules.production.api.consumption_report_service import ConsumptionReportService
from modules.production.api.finished_goods_service import FinishedGoodsService
from modules.production.api.landed_cost import average_landed_cost_by_product
from modules.production.api.mp_consumption_service import MaterialConsumptionService
from modules.production.api.xlsx_report_style import BOLD, autofit, data_row, header_row, title_row, total_row

# The plant's monthly workbook (Charge production sheet) tracks twelve fixed
# costs as manual monthly entries. Three of them -- Électricité Usine/admin and
# Gasoil/Fuel -- are deliberately excluded from the "retenu pour le coût de
# production" subtotal below: this export already prices what was actually
# *consumed* that period from validated reports (see the Gasoil/Fuel/Film/
# Carton sheets), so summing both here would double-count. The remaining seven
# (Salaire, Salaire temporaire, Amortissement, Impôts, Frais communication,
# Dotation carburant, Frais de distribution) have no other sheet pricing them,
# so those are what "Coût de production" actually allocates.
_CHARGE_LINES = (
    "Électricité Usine",
    "Électricité administration",
    "Gasoil ORYX",
    "Gasoil MA",
    "Fuel",
    "Salaire",
    "Salaire de temporaire",
    "Amortissement d'usine",
    "Impôts",
    "Frais communication",
    "Dotation des responsables en carburant",
    "Frais de distribution",
)
_CHARGE_LINES_RETAINED = _CHARGE_LINES[5:]  # Salaire .. Frais de distribution

_MONTHS_FR = (
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
)


def day_phrase(date_iso: str) -> str:
    """"la journée du 10 septembre 2026" -- the day-scoped equivalent of
    consumption_report_export._period_label's monthly phrase, both completing
    the same "... pour {phrase}" sheet-title template."""
    d = datetime.date.fromisoformat(date_iso)
    return f"la journée du {d.day} {_MONTHS_FR[d.month - 1]} {d.year}"


def week_phrase(date_from: str, date_to: str) -> str:
    start, end = datetime.date.fromisoformat(date_from), datetime.date.fromisoformat(date_to)
    if start.month == end.month:
        return f"la semaine du {start.day} au {end.day} {_MONTHS_FR[end.month - 1]} {end.year}"
    return f"la semaine du {start.day} {_MONTHS_FR[start.month - 1]} au {end.day} {_MONTHS_FR[end.month - 1]} {end.year}"


def month_phrase(date_from: str) -> str:
    d = datetime.date.fromisoformat(date_from)
    return f"le mois de {_MONTHS_FR[d.month - 1]} {d.year}"


def resolve_period(period: str, anchor_date: str) -> tuple[str, str, str, int]:
    """(date_from, date_to, period_phrase, period_days) for the requested
    period mode, anchored on any date inside it. "week" is the ISO week
    (Monday-Sunday) containing `anchor_date`; "month" is the calendar month
    containing it."""
    d = datetime.date.fromisoformat(anchor_date)
    if period == "day":
        return anchor_date, anchor_date, day_phrase(anchor_date), 1
    if period == "week":
        start = d - datetime.timedelta(days=d.weekday())
        end = start + datetime.timedelta(days=6)
        return start.isoformat(), end.isoformat(), week_phrase(start.isoformat(), end.isoformat()), 7
    if period == "month":
        start = d.replace(day=1)
        last_day = calendar.monthrange(d.year, d.month)[1]
        end = d.replace(day=last_day)
        return start.isoformat(), end.isoformat(), month_phrase(start.isoformat()), last_day
    raise ValueError(f"period must be one of 'day', 'week', 'month', got {period!r}")


def fetch_period_rows(
    connection, *, tenant_id: str, date_from: str, date_to: str, receipt_lines: list[dict] | None = None
) -> tuple[list[dict], list[dict], list[dict]]:
    """MP/packaging/finished-goods rows for one date range -- the three
    queries every sheet in this workbook (and the analytics dashboard in
    production_analytics_service.py) is built from. Kept here rather than in
    each caller so both share the exact same grouping/costing logic.

    `receipt_lines` is MaterialConsumptionService's own tenant-wide (not
    date-scoped) purchase history -- a caller that already fetched it once for
    several periods (a trend, or an export's per-day breakdown) can pass it
    through to skip re-fetching it here on every call."""
    mp_rows = MaterialConsumptionService(connection).list_consumption(
        tenant_id=tenant_id, date_from=date_from, date_to=date_to, receipt_lines=receipt_lines
    )
    packaging_rows = ConsumptionReportService(connection).list_monthly_consumption_by_supplier(
        tenant_id=tenant_id, date_from=date_from, date_to=date_to
    )
    finished_goods_rows = FinishedGoodsService(connection).list_finished_goods(tenant_id=tenant_id, date_from=date_from, date_to=date_to)
    return mp_rows, packaging_rows, finished_goods_rows


def _designation(product_id: str | None, product_names: dict[str, str]) -> str:
    return product_names.get(product_id, "—") if product_id else "—"


def _supplier(supplier_id: str | None, supplier_names: dict[str, str]) -> str:
    return supplier_names.get(supplier_id, "—") if supplier_id else "—"


def build_finished_goods_sheet(wb: Workbook, rows: list[dict], *, period_phrase: str, product_names: dict[str, str]) -> None:
    ws = wb.create_sheet("Produit fini")
    headers = ["Désignation", "PC/PL", "Nb de paquets", "Qté (tonne)"]
    title_row(ws, 1, len(headers), f"Produits finis pour {period_phrase}")
    row = 3
    header_row(ws, row, headers)
    row += 1

    total_packets = 0.0
    total_qty = 0.0
    for item in sorted(rows, key=lambda r: _designation(r["product_id"], product_names)):
        data_row(
            ws, row,
            [_designation(item["product_id"], product_names), item["pc_pl"] or "—", item["packets_counted"], item["quantity"]],
            money_cols=set(),
        )
        row += 1
        total_packets += item["packets_counted"]
        total_qty += item["quantity"]

    total_row(ws, row, len(headers), "Total", 2, [total_packets, total_qty], money_cols=set())
    autofit(ws, [30, 8, 16, 14])


def build_mp_consumption_sheet(wb: Workbook, rows: list[dict], *, period_phrase: str, product_names: dict[str, str]) -> None:
    ws = wb.create_sheet("Consommation MP")
    headers = ["Désignation", "Qté (tonne)", "Coût unitaire (CFA/tonne)", "Coût total (CFA)"]
    title_row(ws, 1, len(headers), f"Consommation MP pour {period_phrase}")
    row = 3
    header_row(ws, row, headers)
    row += 1

    total_qty = 0.0
    total_cost = 0.0
    priced = True
    for item in sorted(rows, key=lambda r: _designation(r["product_id"], product_names)):
        unit_cost = item["unit_cost"] if item["priced"] else "—"
        cost = item["cost"] if item["priced"] else "—"
        data_row(ws, row, [_designation(item["product_id"], product_names), item["quantity"], unit_cost, cost], money_cols={3, 4})
        row += 1
        total_qty += item["quantity"]
        if item["priced"]:
            total_cost += item["cost"]
        else:
            priced = False

    total_row(ws, row, len(headers), "Total", 1, [total_qty, "", total_cost if priced else "—"], money_cols={2, 4})
    autofit(ws, [30, 14, 22, 16])


def build_unit_cost_sheet(
    wb: Workbook, *, mp_rows: list[dict], packaging_rows: list[dict], product_names: dict[str, str]
) -> None:
    """"Cout unitaire pour tous les articles", each in its own natural unit --
    tonne for MP, kg for film, piece for carton/ruban/scotch -- matching the
    "per item's natural unit" convention this export follows throughout (see
    consumption_report_export.py for the film/carton/ruban/scotch costing this
    reuses, and mp_consumption_service.py for MP's own landed-cost pricing)."""
    ws = wb.create_sheet("Coût unitaire")
    headers = ["Catégorie", "Désignation", "Unité", "Coût unitaire (CFA)"]
    title_row(ws, 1, len(headers), "Coût unitaire par article")
    row = 3
    header_row(ws, row, headers)
    row += 1

    entries: list[tuple[str, str, str, object]] = []
    for item in mp_rows:
        if item["priced"]:
            entries.append(("MP", _designation(item["product_id"], product_names), "tonne", item["unit_cost"]))
    seen_packaging: set[tuple[str, str | None]] = set()
    unit_by_category = {"film": "kg", "carton": "pièce", "scotch": "pièce", "ruban": "pièce"}
    for item in packaging_rows:
        if item["category"] not in unit_by_category or not item["priced"]:
            continue
        key = (item["category"], item["product_id"])
        if key in seen_packaging:
            continue
        seen_packaging.add(key)
        entries.append((
            item["category"].capitalize(), _designation(item["product_id"], product_names),
            unit_by_category[item["category"]], item["unit_price"],
        ))

    for category, designation, unit, unit_cost in sorted(entries, key=lambda e: (e[0], e[1])):
        data_row(ws, row, [category, designation, unit, unit_cost], money_cols={4})
        row += 1

    autofit(ws, [14, 30, 10, 20])


def build_purchase_detail_sheet(
    wb: Workbook, sheet_title: str, receipt_lines: list[dict], product_ids: set[str],
    *, product_names: dict[str, str], supplier_names: dict[str, str],
) -> None:
    """A landed-cost purchase ledger for one product category -- the plant's
    "BD MP"/"Consomable" sheets: every confirmed receipt line for a product in
    this category, its landed cost/unit, and whether it priced anomalously
    high against that product's own history (see
    PurchaseOrderService.list_confirmed_receipt_line_details). Not filtered to
    the export's own period: purchasing rarely lines up with a single day's
    consumption (semoule is bought in bulk, not daily), so this is the full
    purchase history behind the unit costs used elsewhere in this workbook."""
    ws = wb.create_sheet(sheet_title)
    headers = ["Fournisseur", "Désignation", "Date facture", "Quantité", "Coût total (CFA)", "Coût unitaire (CFA)", "Majoration"]
    title_row(ws, 1, len(headers), f"{sheet_title} -- historique des réceptions confirmées")
    row = 3
    header_row(ws, row, headers)
    row += 1

    items = [line for line in receipt_lines if line["product_id"] in product_ids]
    total_qty = 0.0
    total_cost = 0.0
    for item in sorted(items, key=lambda r: r["invoice_date"] or "", reverse=True):
        data_row(
            ws, row,
            [
                _supplier(item["supplier_id"], supplier_names), _designation(item["product_id"], product_names),
                item["invoice_date"], item["quantity"], item["total_cost_base"], item["cost_per_unit_base"],
                "⚠" if item["is_cost_anomaly"] else "",
            ],
            money_cols={5, 6},
        )
        row += 1
        total_qty += item["quantity"]
        total_cost += item["total_cost_base"]

    total_row(ws, row, len(headers), "Total", 3, [total_qty, total_cost], money_cols={5})
    autofit(ws, [26, 30, 14, 12, 18, 18, 10])


def build_charge_sheet(wb: Workbook) -> str:
    """Fixed monthly plant charges (Salaire, Amortissement, Impôts, ...), typed
    in by hand each period -- these live nowhere in the app yet, so unlike
    every other sheet in this workbook they are not computed. `Quote-part`
    (column C) is always a *daily* live formula (=B/365) regardless of the
    export's own period, so it can be reused unscaled by each day's own
    "CP <date>" sheet (see build_daily_recap_workbook) and scaled by
    build_cost_summary_sheet's charge_multiplier for a week/month total --
    editing a monthly figure after the file is opened immediately updates
    every sheet that reads it. Returns the subtotal cell's cross-sheet
    reference (e.g. "'Charge production'!C20")."""
    ws = wb.create_sheet("Charge production")
    headers = ["Désignation", "Montant mensuel (CFA)", "Quote-part (1 j) (CFA)"]
    title_row(ws, 1, len(headers), "Charges fixes liées à la production (saisie manuelle)")
    row = 3
    header_row(ws, row, headers)
    row += 1

    first_data_row = row
    for label in _CHARGE_LINES:
        ws.cell(row=row, column=1, value=label)
        cell = ws.cell(row=row, column=3, value=f'=IFERROR(B{row}/365,"")')
        cell.number_format = "#,##0"
        row += 1

    retained_first = first_data_row + _CHARGE_LINES.index(_CHARGE_LINES_RETAINED[0])
    retained_last = first_data_row + _CHARGE_LINES.index(_CHARGE_LINES_RETAINED[-1])
    subtotal_row = row + 1
    ws.cell(row=subtotal_row, column=1, value="Charges retenues pour le coût de production (hors énergie)")
    subtotal_cell = ws.cell(row=subtotal_row, column=3, value=f"=SUM(C{retained_first}:C{retained_last})")
    subtotal_cell.number_format = "#,##0"
    autofit(ws, [46, 20, 20])
    return f"'Charge production'!C{subtotal_row}"


def build_cost_summary_sheet(
    wb: Workbook, *, charge_subtotal_ref: str, period_phrase: str,
    mp_total_cost: float | None, packaging_total_cost: float | None,
    finished_tonnage: float, total_cartons: float, total_packets: float,
    sheet_name: str = "Coût de production", charge_multiplier: int = 1,
) -> None:
    """The numbers the plant actually wants out of this file: coût de
    production per tonne, per carton and per paquet -- all three the same
    numerator (coût MP + coût emballage, already computed from validated
    reports, + charges fixes entered by hand on 'Charge production') divided
    by a different count. Carton/paquet counts come from this same period's
    real Consommation Carton and Produit fini totals rather than the source
    workbook's fixed "÷100" assumption (Recap!E33 = E32/100) -- that ratio
    only holds for one specific packaging format, where this divides by
    what was actually packed. Only the charges term is a live cross-sheet
    formula -- MP/emballage/tonnage/cartons/paquets are this export's own
    snapshot of validated data and are not meant to be hand-edited, so they
    are written as plain values, matching every other sheet in this workbook.

    `charge_multiplier` scales 'Charge production's always-daily quote-part
    up to this sheet's own period -- 1 for a single day (the default, and
    every per-day "CP <date>" sheet in a week/month export), or the number
    of days in the period for a week/month's own total sheet, so its charges
    term is the sum of what each day's own sheet would show."""
    ws = wb.create_sheet(sheet_name)
    title_row(ws, 1, 2, f"Coût de production pour {period_phrase}")

    charges_formula = f"={charge_subtotal_ref}" if charge_multiplier == 1 else f"={charge_subtotal_ref}*{charge_multiplier}"
    rows = [
        ("Coût MP (voir 'Consommation MP')", mp_total_cost if mp_total_cost is not None else "—"),
        ("Coût emballage (Film+Carton+Scotch+Ruban)", packaging_total_cost if packaging_total_cost is not None else "—"),
        ("Charges fixes (voir 'Charge production')", charges_formula),
        ("Tonnage produit (voir 'Produit fini')", finished_tonnage),
        ("Nb de cartons produits (voir 'Carton')", total_cartons),
        ("Nb de paquets produits (voir 'Produit fini')", total_packets),
    ]
    row = 3
    for label, value in rows:
        ws.cell(row=row, column=1, value=label)
        cell = ws.cell(row=row, column=2, value=value)
        cell.number_format = "#,##0"
        row += 1

    results = [
        ("Coût de production / tonne (CFA)", "B6"),
        ("Coût de production / carton (CFA)", "B7"),
        ("Coût de production / paquet (CFA)", "B8"),
    ]
    row += 1
    for label, divisor_cell in results:
        label_cell = ws.cell(row=row, column=1, value=label)
        label_cell.font = BOLD
        result_cell = ws.cell(row=row, column=2, value=f'=IFERROR((B3+B4+B5)/{divisor_cell},"—")')
        result_cell.number_format = "#,##0"
        result_cell.font = BOLD
        row += 1

    autofit(ws, [42, 20])


def fill_unpriced_packaging_from_landed_cost(packaging_rows: list[dict], receipt_lines: list[dict]) -> list[dict]:
    """ConsumptionReportService prices film/carton/scotch/ruban by last price
    paid to the *same supplier the shift recorded* -- and leaves a row
    unpriced when no supplier was named (see its _apply_costs docstring).
    That happens a lot in practice: the daily/conditionnement report only
    asks which fournisseur delivered the batch, and a shift often does not
    know or record it. Rather than let those rows stay permanently blank in
    a workbook meant to give a full cost view, this falls back to the same
    quantity-weighted landed-cost average MaterialConsumptionService uses for
    MP, across every confirmed receipt for that product regardless of
    supplier. A row with no product at all (gasoil/fuel) still has nothing
    to look up and stays unpriced -- that's a real, separate gap (those
    consumables carry no product reference on the report to begin with), not
    something this fallback can paper over."""
    unit_costs = average_landed_cost_by_product(receipt_lines)
    filled = []
    for row in packaging_rows:
        if row["priced"] or not row["product_id"]:
            filled.append(row)
            continue
        unit_cost = unit_costs.get(row["product_id"])
        if unit_cost is None:
            filled.append(row)
            continue
        row = dict(row)
        row.update(unit_price=unit_cost, unit_price_currency=BASE_CURRENCY, cost=row["quantity"] * unit_cost, priced=True)
        filled.append(row)
    return filled


def totals_from_rows(mp_rows: list[dict], packaging_rows: list[dict], finished_goods_rows: list[dict]) -> tuple:
    """The five figures build_cost_summary_sheet needs, computed the same way
    whether they cover a whole export's period or one day within a week/month
    export -- see build_daily_recap_workbook's two call sites below."""
    mp_total_cost = sum(r["cost"] for r in mp_rows if r["priced"]) if mp_rows and all(r["priced"] for r in mp_rows) else None
    packaging_costed = [r for r in packaging_rows if r["category"] in ("film", "carton", "scotch", "ruban")]
    packaging_total_cost = (
        sum(r["cost"] for r in packaging_costed if r["priced"])
        if packaging_costed and all(r["priced"] for r in packaging_costed) else None
    )
    finished_tonnage = sum(r["quantity"] for r in finished_goods_rows)
    total_cartons = sum(r["quantity"] for r in packaging_rows if r["category"] == "carton")
    total_packets = sum(r["packets_counted"] for r in finished_goods_rows)
    return mp_total_cost, packaging_total_cost, finished_tonnage, total_cartons, total_packets


def build_daily_recap_workbook(
    *,
    period_phrase: str,
    period_days: int,
    mp_rows: list[dict],
    packaging_rows: list[dict],
    finished_goods_rows: list[dict],
    receipt_lines: list[dict],
    mp_product_ids: set[str],
    film_product_ids: set[str],
    carton_product_ids: set[str],
    product_names: dict[str, str],
    supplier_names: dict[str, str],
    daily_breakdowns: list[dict] | None = None,
) -> bytes:
    """One workbook covering every sheet the plant's monthly "Sonali rapport
    général" file builds up to its "Coût de production" answer. `mp_rows`/
    `packaging_rows`/`finished_goods_rows` cover the whole requested period
    (a day, a week or a month) -- every sheet except "Coût de production"
    reads only these, so a week/month export shows the *period's* totals in
    Consommation MP/Film/Carton/etc., matching the source workbook's own
    monthly Consomation PL/PC sheets. `packaging_rows` is exactly what
    ConsumptionReportService.list_monthly_consumption_by_supplier returns
    (its grouping collapses correctly for any date range).

    `daily_breakdowns`, when given (week/month mode only -- see router.py),
    is one dict per day that actually had validated production in the
    period: {"date": "2026-09-10", "mp_rows":..., "packaging_rows":...,
    "finished_goods_rows":...}, each shaped exactly like the period-level
    ones above but scoped to that single day. Each becomes its own
    "CP <date>" sheet, and the period-total "Coût de production" sheet's
    charges term is scaled by period_days so it equals the sum of what every
    day's own sheet shows -- "the recap contains the sum," as requested."""
    daily_breakdowns = daily_breakdowns or []
    packaging_rows = fill_unpriced_packaging_from_landed_cost(packaging_rows, receipt_lines)

    wb = Workbook()
    wb.remove(wb.active)

    build_finished_goods_sheet(wb, finished_goods_rows, period_phrase=period_phrase, product_names=product_names)
    build_mp_consumption_sheet(wb, mp_rows, period_phrase=period_phrase, product_names=product_names)
    build_packaging_sheet(
        wb, "Film", [r for r in packaging_rows if r["category"] == "film"],
        period_phrase=period_phrase, product_names=product_names, supplier_names=supplier_names,
    )
    build_packaging_sheet(
        wb, "Carton", [r for r in packaging_rows if r["category"] == "carton"],
        period_phrase=period_phrase, product_names=product_names, supplier_names=supplier_names,
    )
    build_rub_scotch_sheet(wb, packaging_rows, period_phrase=period_phrase, product_names=product_names, supplier_names=supplier_names)
    build_fuel_sheet(wb, "Gasoil", packaging_rows, category="gasoil", period_phrase=period_phrase, supplier_names=supplier_names)
    build_fuel_sheet(wb, "Fuel", packaging_rows, category="fuel", period_phrase=period_phrase, supplier_names=supplier_names)

    build_unit_cost_sheet(wb, mp_rows=mp_rows, packaging_rows=packaging_rows, product_names=product_names)
    # "Achats ..." rather than bare "MP"/"Film"/"Carton": those names already
    # belong to the consumption sheets above, and a collision would otherwise
    # get silently renamed by openpyxl (e.g. "Film" -> "Film1").
    build_purchase_detail_sheet(wb, "Achats MP", receipt_lines, mp_product_ids, product_names=product_names, supplier_names=supplier_names)
    build_purchase_detail_sheet(wb, "Achats Film", receipt_lines, film_product_ids, product_names=product_names, supplier_names=supplier_names)
    build_purchase_detail_sheet(wb, "Achats Carton", receipt_lines, carton_product_ids, product_names=product_names, supplier_names=supplier_names)

    charge_subtotal_ref = build_charge_sheet(wb)

    mp_total_cost, packaging_total_cost, finished_tonnage, total_cartons, total_packets = totals_from_rows(
        mp_rows, packaging_rows, finished_goods_rows
    )
    build_cost_summary_sheet(
        wb, charge_subtotal_ref=charge_subtotal_ref, period_phrase=period_phrase,
        mp_total_cost=mp_total_cost, packaging_total_cost=packaging_total_cost,
        finished_tonnage=finished_tonnage, total_cartons=total_cartons, total_packets=total_packets,
        charge_multiplier=period_days,
    )

    for day in daily_breakdowns:
        day_packaging_rows = fill_unpriced_packaging_from_landed_cost(day["packaging_rows"], receipt_lines)
        day_mp_total, day_packaging_total, day_tonnage, day_cartons, day_packets = totals_from_rows(
            day["mp_rows"], day_packaging_rows, day["finished_goods_rows"]
        )
        build_cost_summary_sheet(
            wb, charge_subtotal_ref=charge_subtotal_ref, period_phrase=day_phrase(day["date"]),
            mp_total_cost=day_mp_total, packaging_total_cost=day_packaging_total,
            finished_tonnage=day_tonnage, total_cartons=day_cartons, total_packets=day_packets,
            sheet_name=f"CP {day['date']}", charge_multiplier=1,
        )

    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()
